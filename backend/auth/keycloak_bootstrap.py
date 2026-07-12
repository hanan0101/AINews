# This file is part of the AI newsletter system.
"""One-time Keycloak provisioning for a fresh environment.

A brand-new Keycloak volume comes up with no realm, no client, and no
users - SETUP.md Step 4 previously had to be done by hand, by someone
clicking through the admin console, on every fresh environment (a
collaborator's machine, a wiped volume, etc). This does the same steps
through Keycloak's Admin REST API instead, so a fresh environment is
usable immediately after `docker compose up`.

Idempotent: checks whether the realm already exists first, and does
nothing if so - safe to call on every server startup.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from backend.auth.authentication import (
    KEYCLOAK_CLIENT_ID,
    KEYCLOAK_CLIENT_SECRET,
    KEYCLOAK_REALM,
    KEYCLOAK_SERVER_URL,
)
from backend.utils.debug_logging import trace

BOOTSTRAP_ADMIN_URL = os.getenv("KEYCLOAK_ADMIN_URL", KEYCLOAK_SERVER_URL).strip().rstrip("/")
BOOTSTRAP_ADMIN_USERNAME = os.getenv("KEYCLOAK_BOOTSTRAP_ADMIN_USER", "admin").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.getenv("KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD", "admin123").strip()
BOOTSTRAP_USER_USERNAME = os.getenv("KEYCLOAK_BOOTSTRAP_USER", "admin").strip()
BOOTSTRAP_USER_PASSWORD = os.getenv("KEYCLOAK_BOOTSTRAP_USER_PASSWORD", "admin123").strip()
BOOTSTRAP_WAIT_SECONDS = int(os.getenv("KEYCLOAK_BOOTSTRAP_WAIT_SECONDS", "60") or "60")


def _request(method: str, path: str, token: str = "", body: dict | None = None) -> tuple[int, dict]:
    url = f"{BOOTSTRAP_ADMIN_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            payload = json.loads(raw) if raw else {}
            return response.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {}
        return exc.code, payload


def _wait_for_keycloak() -> bool:
    deadline = time.time() + BOOTSTRAP_WAIT_SECONDS
    while time.time() < deadline:
        try:
            status, _ = _request("GET", "/realms/master")
            if status == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _master_admin_token() -> str:
    url = f"{BOOTSTRAP_ADMIN_URL}/realms/master/protocol/openid-connect/token"
    form = urllib.parse.urlencode({
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": BOOTSTRAP_ADMIN_USERNAME,
        "password": BOOTSTRAP_ADMIN_PASSWORD,
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read()).get("access_token", "")


def bootstrap_keycloak_if_missing() -> None:
    # This runs at server startup, before the HTTP server itself is listening -
    # any unhandled exception here (e.g. Keycloak's container process has
    # started but isn't accepting connections yet, which is normal since
    # depends_on only waits for "started", not "healthy") would crash the
    # whole app before it ever serves a request. Never let that happen: this
    # function only skips the one-time provisioning on failure, it must not
    # take the server down with it.
    try:
        _bootstrap_keycloak_if_missing_unsafe()
    except Exception as exc:
        trace(f"Keycloak bootstrap failed, continuing without it: {exc}")


def _bootstrap_keycloak_if_missing_unsafe() -> None:
    if not KEYCLOAK_SERVER_URL or not KEYCLOAK_REALM or not KEYCLOAK_CLIENT_ID:
        return
    if not _wait_for_keycloak():
        trace("Keycloak bootstrap skipped: server did not become reachable in time")
        return

    status, _ = _request("GET", f"/realms/{KEYCLOAK_REALM}/.well-known/openid-configuration")
    if status == 200:
        return  # Already provisioned - the common case on every restart.

    try:
        token = _master_admin_token()
    except Exception as exc:
        trace(f"Keycloak bootstrap skipped: could not get master admin token: {exc}")
        return
    if not token:
        trace("Keycloak bootstrap skipped: master admin token was empty")
        return

    status, _ = _request("POST", "/admin/realms", token, {"realm": KEYCLOAK_REALM, "enabled": True})
    if status not in (201, 409):
        trace(f"Keycloak bootstrap: realm creation returned {status}, continuing anyway")

    # A realm created through this minimal Admin API call (vs. the admin
    # console UI) doesn't register its required-action providers correctly
    # in this Keycloak version - any password-grant login then fails with
    # "resolve_required_actions" even though the user/credentials are fine
    # (confirmed 2026-07-12: same failure from the raw token endpoint, not a
    # library quirk). None of these actions (email verification, OTP, etc.)
    # are used by this app's simple username/password login, so disabling
    # them removes the broken check without touching actual auth (the
    # username/password + role check that matters stays fully enforced).
    status, actions = _request("GET", f"/admin/realms/{KEYCLOAK_REALM}/authentication/required-actions", token)
    if status == 200:
        for action in actions or []:
            alias = action.get("alias")
            if not alias or not action.get("enabled"):
                continue
            action["enabled"] = False
            _request("PUT", f"/admin/realms/{KEYCLOAK_REALM}/authentication/required-actions/{alias}", token, action)

    # Whatever KEYCLOAK_CLIENT_SECRET currently resolves to (env var, or the
    # dev-local-secret default in authentication.py) - the app authenticates
    # with that exact value, so the client must be provisioned with it too.
    status, _ = _request("POST", f"/admin/realms/{KEYCLOAK_REALM}/clients", token, {
        "clientId": KEYCLOAK_CLIENT_ID,
        "enabled": True,
        "publicClient": False,
        "clientAuthenticatorType": "client-secret",
        "secret": KEYCLOAK_CLIENT_SECRET,
        "directAccessGrantsEnabled": True,
        "standardFlowEnabled": True,
        "serviceAccountsEnabled": False,
    })
    if status not in (201, 409):
        trace(f"Keycloak bootstrap: client creation returned {status}, continuing anyway")

    for role in ("admin", "user"):
        status, _ = _request("POST", f"/admin/realms/{KEYCLOAK_REALM}/roles", token, {"name": role})
        if status not in (201, 409):
            trace(f"Keycloak bootstrap: role '{role}' creation returned {status}, continuing anyway")

    status, user_body = _request("POST", f"/admin/realms/{KEYCLOAK_REALM}/users", token, {
        "username": BOOTSTRAP_USER_USERNAME,
        "enabled": True,
        "credentials": [{"type": "password", "value": BOOTSTRAP_USER_PASSWORD, "temporary": False}],
    })
    if status == 201:
        _, users = _request("GET", f"/admin/realms/{KEYCLOAK_REALM}/users?username={BOOTSTRAP_USER_USERNAME}", token)
        user_id = users[0]["id"] if users else None
        _, admin_role = _request("GET", f"/admin/realms/{KEYCLOAK_REALM}/roles/admin", token)
        if user_id and admin_role.get("id"):
            _request(
                "POST", f"/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/role-mappings/realm", token,
                [{"id": admin_role["id"], "name": "admin"}],
            )
        trace(
            f"Keycloak bootstrap: created realm '{KEYCLOAK_REALM}', client '{KEYCLOAK_CLIENT_ID}', "
            f"and admin user '{BOOTSTRAP_USER_USERNAME}' (password from KEYCLOAK_BOOTSTRAP_USER_PASSWORD, default admin123)"
        )
    elif status != 409:
        trace(f"Keycloak bootstrap: user creation returned {status}, continuing anyway")
