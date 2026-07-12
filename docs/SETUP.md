# Setup & Running Guide

This walks you through getting the AI Newsletter app running on a machine that has never seen it before, from an empty folder to a working login. Follow the steps in order — each one assumes the one before it is done. It should take about 15 minutes, most of it waiting for Docker to download images the first time.

Already set up and just need to operate it day to day? See [MAINTENANCE.md](MAINTENANCE.md) instead — this guide is for the first run only.

## What you need before you start

- **Docker Desktop**, installed and running. This is the recommended way to run the project — it starts the app together with the database, search engine, auth server, and vector store it depends on, all wired together correctly. Get it at [docker.com](https://www.docker.com/products/docker-desktop/).
- **Four API keys**, or as many as you have — you can start with fewer and add the rest later:
  - `OPENAI_API_KEY` — used for duplicate-detection embeddings, and optionally as the editorial AI model.
  - `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) — the default editorial AI model that picks and rewrites newsletter cards.
  - `EXA_API_KEY` — powers live news and course discovery. Without it, the app has nothing to fetch.
  - `TMDB_API_KEY` — optional, only needed for the AI-film suggestion feature.

(Python 3.11+ is only needed if you skip Docker entirely — that path is covered near the end, in [Running without Docker](#running-without-docker-only-if-you-need-to).)

## Step 1 — Get the code

```powershell
git clone <repository-url> AINewsletter
cd AINewsletter
```

Every command below assumes you're standing in this folder.

## Step 2 — Add your API keys

The app reads all of its configuration — API keys included — from one file: `backend/.env`. That file is deliberately excluded from git (check `.gitignore`), so it doesn't exist yet on a fresh clone. Create it from the template and fill it in:

```powershell
copy backend\config\.env.example backend\.env
notepad backend\.env
```

In the file that opens, find the four keys listed above and paste your real values in. Save and close. Everything else in that file can stay at its default for now — if you want the full list of what each setting does, it's in [backend/config/ENVIRONMENT_GUIDE.md](../backend/config/ENVIRONMENT_GUIDE.md).

Never commit this file or send it to anyone — it holds live credentials.

## Step 3 — Start everything with Docker

One command brings up the whole stack: the app itself, PostgreSQL (stores newsletter version history), SearXNG (the search engine discovery runs on), Keycloak (handles login), and Qdrant (remembers what's already been published, so it doesn't repeat itself).

```powershell
docker compose up --build
```

The first run takes a few minutes while Docker downloads and builds images. Leave the terminal open and watch the logs — when they settle down and stop scrolling, everything is up. Then open:

```text
http://127.0.0.1:8000/News.html
```

You'll see the app, but you can't generate a newsletter yet — that needs a login, which is Step 4.

If you'd rather not keep the terminal attached, run it detached and tail the app's logs separately:

```powershell
docker compose up --build -d
docker compose logs -f ainewsletter
```

To shut everything down later:

```powershell
docker compose down
```

For reference, here's what's now running and where you can reach it directly: the app on port `8000`, SearXNG on `8080`, Keycloak's admin console on `8180`, and Qdrant on `6333`/`6334`. PostgreSQL isn't exposed to your machine directly — only the app talks to it.

## Step 4 — Create your login (one-time, per environment)

There are two ways to log in:

- **`news` / `news123`** works right now, no setup needed. It's **view-only** — you can look around, but the **Generate** button won't do anything for this account.
- A **Keycloak account with the `admin` role** — this is what actually lets you click Generate, edit cards, and export. Keycloak itself is already running (you started it in Step 3), but it comes up empty: no realm, no client, no users. You have to create those once, by hand, the first time you set up any environment. Do that now:

**4.1 — Open the Keycloak admin console** at `http://localhost:8180/` and log in with the built-in admin account: username `admin`, password `admin123`. (These are development defaults, set in `docker/compose/keycloak.yml` — change them before this ever runs somewhere other than your own machine; see [DEPLOYMENT.md](DEPLOYMENT.md).)

**4.2 — Create the realm.** Use the realm dropdown in the top-left corner → **Create realm**. Name it exactly `newsletter` — the app has this name hardcoded (`docker/compose/app.yml`), so it won't recognize any other spelling.

**4.3 — Create the client.** Go to **Clients** → **Create client**:
- Client ID: `newsletter-app` (again, must match exactly — it's hardcoded the same way)
- Turn **Client authentication** on (this makes it a confidential client)
- Under **Capability config**, turn on **Direct access grants** — the app logs people in with a plain username/password form, not a browser redirect, so this flag is required
- Save

**4.4 — Copy the client secret into your `.env` file.** Open the `newsletter-app` client you just made → **Credentials** tab → copy the **Client secret** value. Paste it into `backend/.env`:

```text
KEYCLOAK_CLIENT_SECRET=<paste the secret here>
```

This is the one Keycloak setting that genuinely comes from `.env` — the realm and client ID are fixed by the compose files, but the secret deliberately isn't, since it's sensitive.

**4.5 — Create the two roles.** **Realm roles** → **Create role** → add `admin`, then repeat for `user`.

**4.6 — Create a user for yourself.** **Users** → **Add user** → give it a username → **Create**. Then, still on that user:
- **Credentials** tab → **Set password** → type a password, switch **Temporary** off → **Save**
- **Role mapping** tab → **Assign role** → pick `admin`

**4.7 — Restart the app so it picks up the secret you just added:**

```powershell
docker compose restart ainewsletter
```

That's it — this whole section only needs to be done once per environment, not once per person. Once the realm and roles exist, you can create more Keycloak users for teammates directly (repeat 4.6 for each new person) without touching any of the earlier steps.

## Step 5 — Log in and generate your first newsletter

1. Open `http://127.0.0.1:8000/News.html`.
2. Log in with the Keycloak user you just created (or `news` / `news123` if you only want to look around).
3. Click **Generate**. A progress timeline appears and moves through: fetching sources → filtering and memory checks → AI model selection → saving → courses and films.
4. Once it finishes, review the cards — edit any that need it, replace weak ones, then export when you're happy with it.

A successful run updates a few files, if you ever need to check what actually happened:

- `frontend/news.json` — the newsletter itself (unless `NEWS_JSON_PATH` points somewhere else)
- `frontend/ai_updates_run_report.json` — a report of what the AI model selected and why
- `backend/news_fetch_state.json` — so the next run doesn't repeat the same searches
- `backend/sector_terms_history.json` — terms the app has learned are relevant over time
- the `qdrant` volume — remembers what's already been published, to avoid duplicates

## Running without Docker (only if you need to)

Most people should stop at Step 5. Use this path only if you need the Python process itself running directly on your machine — for example, attaching a debugger during backend development. It's more moving parts: PostgreSQL and Qdrant aren't reachable from outside Docker by default in this project (only SearXNG on `8080` and Keycloak on `8180` are published to `localhost`), so you still run those four supporting services in Docker and only pull the app itself out.

1. Start everything except the app:
   ```powershell
   docker compose up -d postgres keycloak searxng qdrant
   ```
2. Open `backend/.env` and point it at `localhost` instead of the Docker service names, since the app is no longer inside the Docker network:
   ```text
   HOST=127.0.0.1
   AI_UPDATES_SEARXNG_URL=http://localhost:8080
   AI_UPDATES_QDRANT_URL=http://localhost:6333
   KEYCLOAK_SERVER_URL=http://localhost:8180/
   POSTGRES_HOST=127.0.0.1
   ```
   PostgreSQL still won't be reachable at `localhost` unless you add `ports: ["5432:5432"]` to the `postgres` service in `docker/compose/postgres.yml`, or point `POSTGRES_HOST` at a PostgreSQL instance you're running some other way.
3. Set up Python:
   ```powershell
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
   That last line installs the browser engine PDF export needs — the Docker image already has it built in, which is why this step only exists here.
4. Do the Keycloak setup from Step 4, using `http://localhost:8180/` for the admin console (everything else is identical).
5. Start the server:
   ```powershell
   python -m backend.server.http_server
   ```
6. Open `http://127.0.0.1:8000/News.html` — same as the Docker path from here.

To restart a manually-run backend on Windows without doing all that by hand each time:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1
```

Add `-Foreground` to keep the logs attached, or `-NoStart` to just stop it. It expects your virtual environment at `venv\Scripts\python.exe`, matching Step 3 above.

## If something goes wrong on the first run

**Port 8000 is already taken.** Something else is using it — find and stop it:
```powershell
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

**Generate does nothing, and there are no admin controls.** You're logged in as `user`, not `admin`. Log in with the Keycloak account you assigned the `admin` role to in Step 4.6, or go assign it now.

**Keycloak login fails even though the admin console loads fine in your browser.** `KEYCLOAK_SERVER_URL` in `backend/.env` is probably set to `http://localhost:8180/`. That works from your browser, but not from inside the `ainewsletter` container — there, `localhost` means the container itself, not your machine. It needs to be `http://keycloak:8080/`. Fix it, then `docker compose restart ainewsletter`.

**Docker doesn't seem to see your API keys.** Double check `backend/.env` exists and the variable names are spelled exactly right (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `EXA_API_KEY`, `TMDB_API_KEY`), then rebuild:
```powershell
docker compose down
docker compose up --build
```

**Generate runs but finds little or no news.** Check three things in order: your API keys are valid and the machine has internet access; SearXNG is actually running (`docker compose ps`); and `NEWS_JSON_ONLY_MODE` isn't set to `1` in `backend/.env`.

**PDF export fails, but only outside Docker.** You skipped the Playwright browser install from Step 3 of the manual path:
```powershell
python -m playwright install chromium
```
Then restart the server.
