# Maintenance Guide

Day-to-day operation, backups, and troubleshooting for an already-deployed instance. For first-time setup, see [SETUP.md](SETUP.md).

## Daily Operation

Generate a newsletter:

1. Open `News.html` and log in as an admin user.
2. Click **إنشاء النشرة** / **Generate Newsletter**.
3. Watch the progress timeline: source fetch → filtering/memory → selection and Arabic rewrite → save → courses and films.
4. Review cards, choose the current level/count/mode view, and edit or replace weak content.
5. Click **حفظ ونشر** to create/publish the current version, then download PDF if needed.

See [USER_GUIDE.md](USER_GUIDE.md) for the exact current interface workflow.

Common Docker commands:

```bash
docker compose restart ainewsletter      # restart only the app
docker compose logs -f ainewsletter      # tail app logs
docker compose ps                        # container status
```

Restarting a manually-run (non-Docker) backend on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1              # restart
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1 -Foreground  # restart, keep logs attached
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1 -NoStart     # stop only
```

## Logs

If something went wrong during a run, start with `backend/logs/ai_updates_run.jsonl` — it has the run id, how long each stage took, candidate summaries, token estimates, and any errors from Gemini, Exa, SearXNG, or Qdrant. It's the most detailed record of what actually happened.

For the surrounding process itself rather than the pipeline logic, use the container logs:

```bash
docker compose logs -f ainewsletter   # the app's own stdout/stderr
docker compose logs -f postgres       # database output
```

See [backend/logging/README.md](../backend/logging/README.md) for more on what gets logged and why.

## Backups

The bundled stack does not configure PostgreSQL backups. Back up the
`postgres_data` volume using the database backup approach appropriate for your
deployment. Also back up `backend/.env` separately (it holds secrets and is
not covered by any Docker volume) and the `data/` folder (generated newsletter
state and exports).

## Rotating API Keys

1. Update the key in `backend/.env`.
2. Restart the app so it re-reads the file:
   ```bash
   docker compose restart ainewsletter
   ```
   (Environment variables loaded via `env_file` are only re-read on container start — editing `backend/.env` alone does not hot-reload a running container.)

## Rotating the Keycloak Admin Password

The default `admin` / `admin123` Keycloak admin login is meant for local development only. Change it under the Keycloak admin console (**Users** → `admin` → **Credentials**) on any shared or production environment. See [DEPLOYMENT.md, Step 3](DEPLOYMENT.md#step-3--harden-keycloak-before-anyone-else-can-reach-it).

## Resetting Pipeline Memory / State

A few files quietly accumulate state between runs. Clearing any of them is safe — the pipeline just regenerates them on the next run — but do it on purpose, since you're throwing away learned history, not fixing a bug:

- `backend/pipeline/fetching/news_fetch_state.json` — resets query rotation, so the next run re-scans everything from a clean slate
- `backend/sector_terms_history.json` — clears the historical sector-term trace; current query generation does not consume it
- the Qdrant collection (`AI_UPDATES_QDRANT_COLLECTION`, default `content_memory`) — clears semantic duplicate memory, so previously-used stories may resurface

## Running Tests

```bash
python -m unittest discover -s backend/tests -p "test*.py"
```

Run this after dependency upgrades or before promoting a change to production, alongside the manual checks in [DEPLOYMENT.md, Step 5](DEPLOYMENT.md#step-5--confirm-it-actually-works). To run one module on its own (e.g. while debugging just that area): `python -m unittest backend.tests.test_course_fetchers`.

## Updating Dependencies

```bash
pip install -r requirements.txt          # local/manual environment
docker compose build --no-cache ainewsletter   # Docker image
```

`requirements.txt` pins both direct and transitive dependencies so Docker builds and local installs resolve to the same versions — update pins deliberately, not with a floating `pip install -U`.

## Troubleshooting

**Port 8000 already in use**
```powershell
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

**Generate button does nothing / no admin controls**
The logged-in user doesn't have the `admin` role. Log in with `admin` / `admin123` (auto-provisioned — see [SETUP.md, Step 4](SETUP.md#step-4--log-in)), or assign the `admin` role to the account you're using.

**Docker does not pick up new API keys**
```powershell
docker compose down
docker compose up --build
```

**Generation finds little or no news**
- Confirm API keys are valid and the server has internet access.
- Confirm SearXNG is running: `docker compose ps`.
- Confirm `NEWS_JSON_ONLY_MODE` is not set to `1` in `backend/.env`.

**PDF export fails**
Outside Docker: `python -m playwright install chromium`, then restart the server. Inside Docker this is already installed in the base image.

**Gemini calls stop working**
Check the provider error and the local controls `GEMINI_DAILY_REQUEST_BUDGET`,
`GEMINI_FULL_RUN_REQUEST_BUDGET`, and `GEMINI_STOP_ON_QUOTA` in
[ENVIRONMENT_GUIDE.md](../backend/config/ENVIRONMENT_GUIDE.md). The checked
configuration tracks 120 requests/day, disables the per-run cap with `0`, and
does not enforce the local stop flag. These are local controls, not a promise
of provider quota. `backend/pipeline/modeling/.gemini_rate_limit` stores the
last local request timestamp; operational usage is recorded in
`data/news/runtime/model_usage_summary.json`.

**Cost baseline after prompt changes**
The workbook averages predate the 2026-07-30 news/course prompt changes. After
the next successful full run, compare the measured role usage with
[COST_MODEL.md](COST_MODEL.md) before replacing any planning assumption.
