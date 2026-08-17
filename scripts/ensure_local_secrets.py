"""Generate the per-install secrets/passwords this project used to ship as
hardcoded defaults (LOCAL_AUTH_SECRET, LOCAL_VIEWER_PASSWORD, the Keycloak
bootstrap admin/user passwords), and save them to the untracked
backend/.env.local.

Run this once before the very first `docker compose up`:

    python -m scripts.ensure_local_secrets

Why this has to run before `docker compose up` and not just rely on the app
generating things itself: KEYCLOAK_ADMIN_PASSWORD is read directly by the
Keycloak container at startup (docker/compose/keycloak.yml), and
KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD is read by the app container to log into
that same account - both containers start before the app's own Python code
ever runs, so the value has to already be on disk first. Everything else
here (LOCAL_AUTH_SECRET, LOCAL_VIEWER_PASSWORD, KEYCLOAK_BOOTSTRAP_USER_PASSWORD)
is only ever read by the app itself, so backend/auth/authentication.py would
generate those the same way on first run even without this script - running
it upfront just means every credential is ready at once instead of
appearing gradually.

Idempotent and safe to re-run: existing values in backend/.env.local (or
backend/.env, or a real environment variable) are never overwritten - this
only fills in what's missing.
"""

from __future__ import annotations

import secrets
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
ENV_LOCAL_FILE = BACKEND_DIR / ".env.local"

# KEYCLOAK_ADMIN_PASSWORD (read by the Keycloak container itself) and
# KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD (read by the app to log into that same
# account) must be identical - see the comment in keycloak_bootstrap.py.
SHARED_ADMIN_PASSWORD_KEYS = ("KEYCLOAK_ADMIN_PASSWORD", "KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD")
OTHER_GENERATED_KEYS = ("LOCAL_AUTH_SECRET", "LOCAL_VIEWER_PASSWORD", "KEYCLOAK_BOOTSTRAP_USER_PASSWORD")


def _parse_env_file(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def main() -> None:
    existing_text = ENV_LOCAL_FILE.read_text(encoding="utf-8") if ENV_LOCAL_FILE.exists() else ""
    values = _parse_env_file(existing_text)

    new_lines = []

    shared_admin_password = values.get("KEYCLOAK_ADMIN_PASSWORD") or values.get("KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD")
    for key in SHARED_ADMIN_PASSWORD_KEYS:
        if key in values:
            continue
        if shared_admin_password is None:
            shared_admin_password = secrets.token_urlsafe(18)
        new_lines.append(f"{key}={shared_admin_password}")
        print(f"Generated {key}")

    for key in OTHER_GENERATED_KEYS:
        if key in values:
            continue
        value = secrets.token_hex(32) if key == "LOCAL_AUTH_SECRET" else secrets.token_urlsafe(18)
        new_lines.append(f"{key}={value}")
        print(f"Generated {key}")

    if not new_lines:
        print(f"Nothing to do - every value already present in {ENV_LOCAL_FILE}")
        return

    ENV_LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    text = existing_text
    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n".join(new_lines) + "\n"
    ENV_LOCAL_FILE.write_text(text, encoding="utf-8")
    print(f"Saved to {ENV_LOCAL_FILE} (untracked, unique to this install - do not commit it)")


if __name__ == "__main__":
    main()
