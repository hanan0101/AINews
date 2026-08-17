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

- The complete checked pipeline uses `GEMINI_API_KEY` for model calls,
  `EXA_API_KEY` for Exa news/course discovery, and `TMDB_API_KEY` for film
  discovery. `OPENAI_API_KEY` is needed only if
  `AI_UPDATES_MODEL_PROVIDER=openai`.
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

This is the step that's easy to skip locally and genuinely matters on a server. Realm/client/role/user provisioning is automatic (`backend/auth/keycloak_bootstrap.py` runs on app startup — see [SETUP.md, Step 4](SETUP.md#step-4--log-in)). None of the credentials it provisions with are fixed defaults anymore — `LOCAL_VIEWER_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`/`KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD`, `KEYCLOAK_BOOTSTRAP_USER_PASSWORD`, and `KEYCLOAK_CLIENT_SECRET` are all either set by you in `backend/.env`/`backend/.env.local`, or auto-generated once (`python -m scripts.ensure_local_secrets`, or the app's own first-run fallback) into the untracked `backend/.env.local`. The app refuses to start if any of them is ever set back to one of the old hardcoded values (`admin123`, `news123`, `dev-local-secret`). `KEYCLOAK_CLIENT_SECRET` specifically is also re-synced to the Keycloak client on *every* startup, not just the first — so even a client that was already provisioned with an old secret gets corrected automatically the next time the app starts, no admin-console edit needed.

Do these, in this order, before the server is reachable by anyone but you:

1. **Confirm `backend/.env.local` was generated with this server's own random values** — don't copy it over from your laptop. If you're reusing an existing `backend/.env.local` (e.g. redeploying the same environment), that's fine; just don't let a shared/default one slip in from a template or another machine.
2. **Move off `start-dev`** once you're past initial evaluation — switch to a real production Keycloak run mode (`start`, with a configured hostname and TLS). See Keycloak's own [production configuration guide](https://www.keycloak.org/server/configuration-production).
3. **Set `AUTH_COOKIE_SECURE=1`** in `backend/.env` once the server is behind HTTPS, so login cookies require TLS and can't be read over plain HTTP.

The bootstrap admin/user accounts themselves (usernames, not just passwords)
are only created once per realm - if Keycloak already has them from an
earlier run, changing `KEYCLOAK_BOOTSTRAP_ADMIN_USER`/`KEYCLOAK_BOOTSTRAP_USER`
afterward does not rename or recreate anyone; use the admin console for that.
The client secret is the one credential here that self-heals on every
startup, as described above.

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
2. Log in twice — once with a Keycloak `admin` user, once with the local `news` viewer (see `backend/.env.local` for both passwords) — and confirm both work.
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
