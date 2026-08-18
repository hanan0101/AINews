# This file is part of the AI newsletter system.
"""Authentication helpers for the custom HTTP server."""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from http.cookies import SimpleCookie

try:
    from keycloak import KeycloakOpenID
except ImportError:
    KeycloakOpenID = None


KEYCLOAK_SERVER_URL = os.getenv("KEYCLOAK_SERVER_URL", "http://localhost:8180/").strip()
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "newsletter").strip()
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "newsletter-app").strip()
# "dev-local-secret" is a real usable default, not a placeholder to fill in -
# backend/auth/keycloak_bootstrap.py provisions the Keycloak client with
# this exact same default when KEYCLOAK_CLIENT_SECRET isn't set in .env, so
# a fresh environment logs in successfully with zero manual Keycloak setup.
# Set a real KEYCLOAK_CLIENT_SECRET in backend/.env before this ever runs
# somewhere other than your own machine.
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "dev-local-secret").strip()
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "access_token").strip() or "access_token"
AUTH_REFRESH_COOKIE_NAME = os.getenv("AUTH_REFRESH_COOKIE_NAME", "refresh_token").strip() or "refresh_token"
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}
LOCAL_VIEWER_AUTH_ENABLED = os.getenv("LOCAL_VIEWER_AUTH_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
LOCAL_VIEWER_USERNAME = os.getenv("LOCAL_VIEWER_USERNAME", "news").strip()
LOCAL_VIEWER_PASSWORD = os.getenv("LOCAL_VIEWER_PASSWORD", "news123").strip()
LOCAL_AUTH_SECRET = (
    os.getenv("LOCAL_AUTH_SECRET", "")
    or KEYCLOAK_CLIENT_SECRET
    or "local-newsletter-viewer-secret"
).strip()
LOCAL_VIEWER_TOKEN_TTL_SECONDS = int(os.getenv("LOCAL_VIEWER_TOKEN_TTL_SECONDS", "43200") or "43200")


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
        "roles": ["user"],
        "exp": int(time.time()) + LOCAL_VIEWER_TOKEN_TTL_SECONDS,
        "kind": "local_viewer",
    }, separators=(",", ":")).encode("utf-8"))
    return f"local.{payload}.{_local_token_signature(payload)}"


def _local_user_from_token(token):
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
    roles = sorted(set(data.get("roles") or []))
    username = str(data.get("username") or "")
    return {
        "username": username,
        "roles": roles,
        "is_admin": "admin" in roles,
        "is_user": "user" in roles or "admin" in roles,
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
def auth_token_cookies(token, session_cookie=True):
    access_max_age = None if session_cookie else token.get("expires_in")
    refresh_max_age = None if session_cookie else token.get("refresh_expires_in")
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

