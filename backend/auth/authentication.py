# This file is part of the AI newsletter system.
"""Authentication helpers for the custom HTTP server."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
from http.cookies import SimpleCookie
from pathlib import Path

from dotenv import load_dotenv

try:
    from keycloak import KeycloakOpenID
except ImportError:
    KeycloakOpenID = None

from backend.utils.debug_logging import trace

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_LOCAL_FILE = BACKEND_DIR / ".env.local"

# Load in increasing precedence: a real OS/container env var always wins,
# then backend/.env, then backend/.env.local (where auto-generated
# per-install secrets/passwords are persisted - see _persisted_local_value).
load_dotenv(BACKEND_DIR / ".env", override=False)
load_dotenv(ENV_LOCAL_FILE, override=False)


# Server role: Append a generated key=value line to the untracked local env file.
def _write_env_local_value(key, value):
    ENV_LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = ENV_LOCAL_FILE.read_text(encoding="utf-8") if ENV_LOCAL_FILE.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    ENV_LOCAL_FILE.write_text(existing + f"{key}={value}\n", encoding="utf-8")


# Server role: Resolve a locally-scoped secret/password without ever shipping
# a working hardcoded default. Returns the manually-configured value if one
# exists anywhere (OS env, backend/.env, backend/.env.local); otherwise
# generates one and persists it to backend/.env.local so it is stable across
# restarts but unique per install and never committed.
def _persisted_local_value(env_name, generator):
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    generated = generator()
    _write_env_local_value(env_name, generated)
    os.environ[env_name] = generated
    trace(f"Generated {env_name} and saved it to backend/.env.local (untracked, unique to this install)")
    return generated


def _generate_password():
    return secrets.token_urlsafe(18)


# Server role: Resolve a password that some other process also reads under a
# different variable name (e.g. the Keycloak container reads
# KEYCLOAK_ADMIN_PASSWORD while this app reads KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD
# to log into that same account - the two must be identical). Prefers a value
# already set under either name so they can never drift once resolved; only
# generates fresh (under primary_env_name) if truly neither is set anywhere.
def _persisted_shared_password(primary_env_name, alias_env_name):
    value = os.getenv(primary_env_name, "").strip() or os.getenv(alias_env_name, "").strip()
    if value:
        return value
    return _persisted_local_value(primary_env_name, _generate_password)


# AUTH BLOCK: Refuse to start rather than silently run with a known-bad
# credential. Reason: catches the old hardcoded defaults (or anyone
# reintroducing them by hand, or a stale backend/.env.local from before this
# fix) instead of quietly accepting them.
_KNOWN_DEFAULT_PASSWORDS = {"admin123", "news123", "dev-local-secret"}


def _reject_known_default_password(env_name, value):
    if value.strip().lower() in _KNOWN_DEFAULT_PASSWORDS:
        raise RuntimeError(
            f"{env_name} is set to a known default value that must not be used. "
            "Remove it from backend/.env / backend/.env.local so a random value "
            "is generated automatically, or set your own value."
        )


KEYCLOAK_SERVER_URL = os.getenv("KEYCLOAK_SERVER_URL", "http://localhost:8180/").strip()
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "newsletter").strip()
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "newsletter-app").strip()
# No hardcoded fallback - same reasoning as LOCAL_AUTH_SECRET below. Generated
# once and persisted to backend/.env.local if not set in backend/.env or
# backend/.env.local. backend/auth/keycloak_bootstrap.py provisions (and, on
# every subsequent startup, re-syncs) the Keycloak client with whatever this
# resolves to, so a fresh environment still logs in with zero manual Keycloak
# setup - it just gets a random secret instead of a fixed, publicly-known one.
KEYCLOAK_CLIENT_SECRET = _persisted_local_value("KEYCLOAK_CLIENT_SECRET", _generate_password)
_reject_known_default_password("KEYCLOAK_CLIENT_SECRET", KEYCLOAK_CLIENT_SECRET)
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "access_token").strip() or "access_token"
AUTH_REFRESH_COOKIE_NAME = os.getenv("AUTH_REFRESH_COOKIE_NAME", "refresh_token").strip() or "refresh_token"
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}
AUTH_SESSION_MAX_AGE_SECONDS = int(os.getenv("AUTH_SESSION_MAX_AGE_SECONDS", "31536000") or "31536000")
LOCAL_VIEWER_AUTH_ENABLED = os.getenv("LOCAL_VIEWER_AUTH_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
LOCAL_VIEWER_USERNAME = os.getenv("LOCAL_VIEWER_USERNAME", "news").strip()
LOCAL_VIEWER_PASSWORD = _persisted_local_value("LOCAL_VIEWER_PASSWORD", _generate_password)
_reject_known_default_password("LOCAL_VIEWER_PASSWORD", LOCAL_VIEWER_PASSWORD)
LOCAL_AUTH_SECRET = _persisted_local_value("LOCAL_AUTH_SECRET", lambda: secrets.token_hex(32))
LOCAL_VIEWER_TOKEN_TTL_SECONDS = int(
    os.getenv("LOCAL_VIEWER_TOKEN_TTL_SECONDS", str(AUTH_SESSION_MAX_AGE_SECONDS))
    or str(AUTH_SESSION_MAX_AGE_SECONDS)
)


def _b64url_encode(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value):
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _local_token_signature(payload):
    return _b64url_encode(
        hmac.new(
            LOCAL_AUTH_SECRET.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    )


def _local_access_token(username):
    payload = _b64url_encode(json.dumps({
        "username": username,
        "exp": int(time.time()) + LOCAL_VIEWER_TOKEN_TTL_SECONDS,
        "kind": "local_viewer",
    }, separators=(",", ":")).encode("utf-8"))
    return f"local.{payload}.{_local_token_signature(payload)}"


# AUTH BLOCK: Local viewer tokens can never carry the admin role.
# Reason: A local token only proves the holder knew LOCAL_AUTH_SECRET (or
# guessed the local viewer password); it must never be trusted for anything
# beyond the fixed "user" role, no matter what a signed payload claims.
# Real admin access only ever comes from a Keycloak-introspected token.
def _local_user_from_token(token):
    if not LOCAL_VIEWER_AUTH_ENABLED:
        return None
    if not token or not str(token).startswith("local."):
        return None
    try:
        _, payload, signature = str(token).split(".", 2)
        expected = _local_token_signature(payload)
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_b64url_decode(payload).decode("utf-8"))
    except Exception:
        return None
    if int(data.get("exp") or 0) < int(time.time()):
        return None
    username = str(data.get("username") or "")
    return {
        "username": username,
        "roles": ["user"],
        "is_admin": False,
        "is_user": True,
    }


# AUTH BLOCK: Keep Keycloak client creation in one place for all HTTP routes.
# Reason: The current application is http.server-based, so handlers call these
# helpers directly instead of using FastAPI dependencies.
def keycloak_client():
    if KeycloakOpenID is None:
        raise RuntimeError("python-keycloak is not installed. Run pip install -r requirements.txt")
    return KeycloakOpenID(
        server_url=KEYCLOAK_SERVER_URL,
        client_id=KEYCLOAK_CLIENT_ID,
        realm_name=KEYCLOAK_REALM,
        client_secret_key=KEYCLOAK_CLIENT_SECRET,
    )


# AUTH BLOCK: Authenticate username/password and return tokens.
# Reason: Login stores only the access token in an httponly cookie.
def authenticate(username, password):
    if (
        LOCAL_VIEWER_AUTH_ENABLED
        and username == LOCAL_VIEWER_USERNAME
        and password == LOCAL_VIEWER_PASSWORD
    ):
        return {
            "access_token": _local_access_token(username),
            "expires_in": LOCAL_VIEWER_TOKEN_TTL_SECONDS,
        }
    return keycloak_client().token(username, password)


# Performs the refresh token helper step.
def refresh_token(refresh_token_value):
    return keycloak_client().refresh_token(refresh_token_value)


# Performs the cookie value helper step.
def _cookie_value(headers):
    cookie_header = headers.get("Cookie", "") if headers else ""
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return ""
    morsel = cookie.get(AUTH_COOKIE_NAME)
    return morsel.value if morsel else ""


# Performs the access token from headers helper step.
def access_token_from_headers(headers):
    token = _cookie_value(headers)
    if token:
        return token
    auth_header = headers.get("Authorization", "") if headers else ""
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return ""


# Performs the refresh token from headers helper step.
def refresh_token_from_headers(headers):
    cookie_header = headers.get("Cookie", "") if headers else ""
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return ""
    morsel = cookie.get(AUTH_REFRESH_COOKIE_NAME)
    return morsel.value if morsel else ""


# Performs the realm roles helper step.
def _realm_roles(token_info):
    roles = token_info.get("realm_access", {}).get("roles", [])
    if roles:
        return roles
    return token_info.get("realm_access.roles", []) or []


# Performs the resource roles helper step.
def _resource_roles(token_info):
    resource_access = token_info.get("resource_access") or {}
    client_roles = resource_access.get(KEYCLOAK_CLIENT_ID, {}).get("roles", [])
    if client_roles:
        return client_roles
    return []


# AUTH BLOCK: Convert a Keycloak token into the small user object the UI needs.
# Reason: Route protection and admin-control visibility both depend on roles.
def user_from_access_token(token):
    if not token:
        return None
    local_user = _local_user_from_token(token)
    if local_user:
        return local_user
    try:
        token_info = keycloak_client().introspect(token)
    except Exception:
        return None
    if not token_info.get("active"):
        return None
    roles = sorted(set(_realm_roles(token_info) + _resource_roles(token_info)))
    username = (
        token_info.get("preferred_username")
        or token_info.get("username")
        or token_info.get("sub")
        or ""
    )
    return {
        "username": username,
        "roles": roles,
        "is_admin": "admin" in roles,
        "is_user": "user" in roles or "admin" in roles,
    }


# Performs the user from headers helper step.
def user_from_headers(headers):
    return user_from_access_token(access_token_from_headers(headers))


# Performs the user from headers with refresh helper step.
def user_from_headers_with_refresh(headers):
    user = user_from_headers(headers)
    if user:
        return user, None
    refresh_value = refresh_token_from_headers(headers)
    if not refresh_value:
        return None, None
    try:
        token = refresh_token(refresh_value)
    except Exception:
        return None, None
    user = user_from_access_token(token.get("access_token", ""))
    if not user:
        return None, None
    return user, token


# Performs the require user helper step.
def require_user(user):
    return bool(user and (user.get("is_user") or user.get("is_admin")))


# Performs the require admin helper step.
def require_admin(user):
    return bool(user and user.get("is_admin"))


# AUTH BLOCK: Build secure cookie headers without framework-specific response APIs.
# Reason: The custom HTTP handler writes headers manually.
def access_token_cookie(access_token, max_age=None):
    parts = [
        f"{AUTH_COOKIE_NAME}={urllib.parse.quote(access_token or '')}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if AUTH_COOKIE_SECURE:
        parts.append("Secure")
    if max_age is not None:
        parts.append(f"Max-Age={int(max_age)}")
    return "; ".join(parts)


# Performs the refresh token cookie helper step.
def refresh_token_cookie(refresh_token_value, max_age=None):
    parts = [
        f"{AUTH_REFRESH_COOKIE_NAME}={urllib.parse.quote(refresh_token_value or '')}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if AUTH_COOKIE_SECURE:
        parts.append("Secure")
    if max_age is not None:
        parts.append(f"Max-Age={int(max_age)}")
    return "; ".join(parts)


# Performs the auth token cookies helper step.
def auth_token_cookies(token, session_cookie=False):
    configured_max_age = AUTH_SESSION_MAX_AGE_SECONDS if AUTH_SESSION_MAX_AGE_SECONDS > 0 else None
    access_max_age = None if session_cookie else configured_max_age or token.get("expires_in")
    refresh_max_age = None if session_cookie else configured_max_age or token.get("refresh_expires_in")
    cookies = [access_token_cookie(token.get("access_token", ""), access_max_age)]
    if token.get("refresh_token"):
        cookies.append(refresh_token_cookie(token.get("refresh_token", ""), refresh_max_age))
    return cookies


# Performs the clear access token cookie helper step.
def clear_access_token_cookie():
    parts = [
        f"{AUTH_COOKIE_NAME}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=0",
    ]
    if AUTH_COOKIE_SECURE:
        parts.append("Secure")
    return "; ".join(parts)


# Performs the clear refresh token cookie helper step.
def clear_refresh_token_cookie():
    parts = [
        f"{AUTH_REFRESH_COOKIE_NAME}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=0",
    ]
    if AUTH_COOKIE_SECURE:
        parts.append("Secure")
    return "; ".join(parts)


# Performs the clear auth cookies helper step.
def clear_auth_cookies():
    return [clear_access_token_cookie(), clear_refresh_token_cookie()]


# TODO: When Ministry IT provides Azure AD credentials:
# 1. Go to Keycloak Admin -> Identity Providers -> Add Microsoft
# 2. Enter: Client ID, Client Secret, Tenant ID from IT
# 3. Add login button: "Login with Work Account"
# No code changes needed in this file.
