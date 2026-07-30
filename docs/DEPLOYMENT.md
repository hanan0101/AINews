# Deployment Guide

This walks through moving the project from your machine onto a server. It assumes you've already gone through [SETUP.md](SETUP.md) once locally and know what the moving parts are — this guide focuses on what's different about a real server: multiple people accessing it, secrets that need to stay secret, and data that needs to survive a restart.

## What the server needs

- Docker and Docker Compose. That's the whole recommended path — see [Step 1](#step-1--set-up-the-environment-file) below. A manual, Docker-free path exists too, covered near the end, but you're on your own for standing up PostgreSQL/Keycloak/SearXNG yourself if you go that route.
- Outbound internet access to Gemini in the checked configuration, plus the
  external discovery services you enable (such as Exa and TMDb). OpenAI is
  contacted only when selected as the active provider.
- Somewhere durable to keep `data/` and the PostgreSQL/Qdrant volumes, so a redeploy doesn't wipe out newsletter history.

## Step 1 — Set up the environment file

Same as local setup: copy the template and fill in real values.

```bash
cp backend/.env.example backend/.env
```

For a server, pay attention to these in particular:

- The active model/search API keys. The checked configuration requires
  `GEMINI_API_KEY`; `OPENAI_API_KEY`, `EXA_API_KEY`, and `TMDB_API_KEY` are
  conditional on the integrations you enable.
- `HOST=0.0.0.0` — without this, the server only listens on localhost and nothing outside the container can reach it
- The PostgreSQL credentials, if you're not using the defaults

The full variable list, with what each one does, is in [backend/config/ENVIRONMENT_GUIDE.md](../backend/config/ENVIRONMENT_GUIDE.md).

## Step 2 — Bring the stack up

The root `docker-compose.yml` is intentionally thin — it just lists which service files to run together. Each service lives in its own file under `docker/compose/`, and that's where you'd go to change something specific to one service (its port, image version, volumes):

- `docker/compose/app.yml` → the app itself, runs `python -m backend.server.http_server`
- `docker/compose/postgres.yml` → PostgreSQL
- `docker/compose/keycloak.yml` → the login/authentication provider
- `docker/compose/searxng.yml` → the metasearch engine discovery runs against
- `docker/compose/qdrant.yml` → the vector store that remembers what's already been published

You don't need to touch any of that to bring the stack up — the commands are the same as always, run from the project root:

```bash
docker compose up -d --build
```

Check that everything actually started:

```bash
docker compose ps
docker compose logs -f ainewsletter
```

Then open `http://<server-host>:8000/News.html` from a browser that can reach the server.

## Step 3 — Harden Keycloak before anyone else can reach it

This is the step that's easy to skip locally and genuinely matters on a server. Realm/client/role/user provisioning is automatic (`backend/auth/keycloak_bootstrap.py` runs on app startup — see [SETUP.md, Step 4](SETUP.md#step-4--log-in)), but it provisions everything with **development defaults**, which is fine on your own machine and not fine on a server anyone else can reach: admin login `admin` / `admin123`, a bootstrap app user with the same `admin` / `admin123` credentials, a client secret that defaults to the literal string `dev-local-secret`, and Keycloak started in `start-dev` mode.

Do these, in this order, before the server is reachable by anyone but you:

1. **Edit `docker/compose/keycloak.yml`** to replace the hardcoded
   `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` development values. The
   Keycloak service does not read `backend/.env`.
2. **Set `KEYCLOAK_BOOTSTRAP_ADMIN_USER` and
   `KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD`** in `backend/.env` to the same new
   Keycloak master-realm credentials so application bootstrap can authenticate.
3. **Set `KEYCLOAK_CLIENT_SECRET`** in `backend/.env` to a real generated secret before the first startup on this environment — bootstrap provisions the `newsletter-app` client with whatever this resolves to, so it must not be left at the `dev-local-secret` default.
4. **Set `KEYCLOAK_BOOTSTRAP_USER_PASSWORD`** in `backend/.env` to something other than `admin123` before the first startup — this is the password bootstrap gives the one auto-created app admin account.
5. **Move off `start-dev`** once you're past initial evaluation — switch to a real production Keycloak run mode (`start`, with a configured hostname and TLS). See Keycloak's own [production configuration guide](https://www.keycloak.org/server/configuration-production).
6. **Set `AUTH_COOKIE_SECURE=1`** in `backend/.env` once the server is behind HTTPS, so login cookies require TLS and can't be read over plain HTTP.

These bootstrap credentials affect a fresh Keycloak volume/realm. If Keycloak
has already initialized with the defaults, change the existing credentials and
client through the admin console; editing configuration alone does not rewrite
the stored users or client secret.

## Step 4 — Make sure the right things survive a restart

A few paths hold everything that would be painful to lose. Back these up, or at minimum make sure they're not on ephemeral storage:

- `data/` — generated newsletter state and exported files (bind-mounted into the container at `/app/data`)
- the `postgres_data` volume — the actual version history
- the `qdrant_data` volume — semantic memory of what's already been published
- `backend/.env` — this one is *not* in any Docker volume and *not* in git, so back it up yourself, somewhere secure. Losing it means recreating every secret from scratch.

## Step 5 — Confirm it actually works

Run the automated checks first:

```bash
python -m unittest discover -s backend/tests -p "test*.py"
```

Then walk through it by hand, the same way a real user would:

1. Open `/News.html` and confirm it loads.
2. Log in twice — once with a Keycloak `admin` user, once with the local `news` / `news123` viewer — and confirm both work.
3. Click **إنشاء النشرة** / **Generate Newsletter** and watch the progress timeline move through all its stages.
4. Click **حفظ ونشر** and confirm the saved title matches the current
   newsletter issue/month metadata.
5. Download the current view as PDF and verify the file.
6. Confirm the new JSON version appears on `/versions.html` and the output landed where `NEWS_JSON_PATH` says it should.

If all six pass, the deployment smoke test is complete. External API,
PostgreSQL, Keycloak, and PDF behavior still depend on that environment's
credentials and services.

## Running without Docker

Only use this if the server genuinely cannot run Docker. You take on standing up PostgreSQL, Keycloak, and SearXNG yourself, and pointing `backend/.env` at wherever they end up living:

```bash
python -m venv venv
source venv/bin/activate   # venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt
python -m playwright install chromium
python -m backend.server.http_server
```
