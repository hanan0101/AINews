# Deployment Guide

This walks through moving the project from your machine onto a server. It assumes you've already gone through [SETUP.md](SETUP.md) once locally and know what the moving parts are — this guide focuses on what's different about a real server: multiple people accessing it, secrets that need to stay secret, and data that needs to survive a restart.

## What the server needs

- Docker and Docker Compose. That's the whole recommended path — see [Step 1](#step-1--set-up-the-environment-file) below. A manual, Docker-free path exists too, covered near the end, but you're on your own for standing up PostgreSQL/Keycloak/SearXNG yourself if you go that route.
- Outbound internet access, specifically to OpenAI/Gemini, Exa, and TMDb — the app calls all three.
- Somewhere durable to keep `data/` and the PostgreSQL/Qdrant volumes, so a redeploy doesn't wipe out newsletter history.

## Step 1 — Set up the environment file

Same as local setup: copy the template and fill in real values.

```bash
cp backend/config/.env.example backend/.env
```

For a server, pay attention to these in particular:

- The model/search API keys (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `EXA_API_KEY`, `TMDB_API_KEY`)
- `HOST=0.0.0.0` — without this, the server only listens on localhost and nothing outside the container can reach it
- The PostgreSQL credentials, if you're not using the defaults

The full variable list, with what each one does, is in [backend/config/ENVIRONMENT_GUIDE.md](../backend/config/ENVIRONMENT_GUIDE.md).

## Step 2 — Bring the stack up

The root `docker-compose.yml` is intentionally thin — it just lists which service files to run together. Each service lives in its own file under `docker/compose/`, and that's where you'd go to change something specific to one service (its port, image version, volumes):

- `docker/compose/app.yml` → the app itself, runs `python -m backend.server.http_server`
- `docker/compose/postgres.yml` → PostgreSQL 15, with scheduled SQL backups baked into the same container
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

This is the step that's easy to skip locally and genuinely matters on a server. `docker/compose/keycloak.yml` ships with development defaults — admin login `admin` / `admin123`, and started in `start-dev` mode, which isn't meant to be exposed publicly.

Do these, in this order, before the server is reachable by anyone but you:

1. **Change the Keycloak admin password**, or put Keycloak behind a network boundary only your team can reach — don't leave `admin`/`admin123` facing the internet.
2. **Create the realm, client, and roles**, the same way you did locally: walk through [SETUP.md, Step 4](SETUP.md#step-4--create-your-login-one-time-per-environment). This isn't automated and there's no realm-export file in the repo, so it has to be done by hand once per environment — including this one.
3. **Put the client secret in `backend/.env`** as `KEYCLOAK_CLIENT_SECRET`, from the client's **Credentials** tab. (The realm name and client ID are already fixed correctly in `docker/compose/app.yml` — only the secret needs to come from you.)
4. **Move off `start-dev`** once you're past initial evaluation — switch to a real production Keycloak run mode (`start`, with a configured hostname and TLS). See Keycloak's own [production configuration guide](https://www.keycloak.org/server/configuration-production).
5. **Set `AUTH_COOKIE_SECURE=1`** in `backend/.env` once the server is behind HTTPS, so login cookies require TLS and can't be read over plain HTTP.

## Step 4 — Make sure the right things survive a restart

A few paths hold everything that would be painful to lose. Back these up, or at minimum make sure they're not on ephemeral storage:

- `data/` — generated newsletter state and exported files (bind-mounted into the container at `/app/data`)
- the `postgres_data` volume — the actual version history
- the `postgres_backups` volume — daily SQL dumps, kept for 7 days automatically (see [MAINTENANCE.md](MAINTENANCE.md) for how to trigger one manually or restore from one)
- the `qdrant_data` volume — semantic memory of what's already been published
- `backend/.env` — this one is *not* in any Docker volume and *not* in git, so back it up yourself, somewhere secure. Losing it means recreating every secret from scratch.

## Step 5 — Confirm it actually works

Run the automated check first:

```bash
python -m unittest backend.tests.test_course_fetchers
```

Then walk through it by hand, the same way a real user would:

1. Open `/News.html` and confirm it loads.
2. Log in twice — once with a Keycloak `admin` user, once with the local `news` / `news123` viewer — and confirm both work.
3. Click **Generate** and watch the progress timeline move through all its stages.
4. Export a version as PDF and confirm it shows up on `/versions.html`.
5. Confirm the output landed where `NEWS_JSON_PATH` says it should.

If all five pass, the deployment is good.

## Running without Docker

Only use this if the server genuinely cannot run Docker. You take on standing up PostgreSQL, Keycloak, and SearXNG yourself, and pointing `backend/.env` at wherever they end up living:

```bash
python -m venv venv
source venv/bin/activate   # venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt
python -m playwright install chromium
python -m backend.server.http_server
```
