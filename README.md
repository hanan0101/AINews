# AI Newsletter System

An editorial workflow that discovers recent AI product updates, filters out duplicates and weak sources, uses an AI model to select and rewrite cards, enriches them with logos and metadata, and serves the result through a review UI for Arabic editorial output.

## What It Does

- Finds AI updates from tool registries, official sites, Exa, and SearXNG.
- Fetches supporting courses and AI-themed films.
- Filters stale, duplicate, low-quality, or off-topic candidates (including semantic dedup via Qdrant).
- Uses OpenAI- or Gemini-compatible model calls for editorial selection and rewriting.
- Saves the newsletter JSON consumed by the frontend.
- Stores versions and PDF exports through the backend server.

## Where to go next

Pick whichever matches what you're trying to do right now:

- **Never run this before, want it working on your machine?** Start at [docs/SETUP.md](docs/SETUP.md). It walks through every step in order — cloning, API keys, Docker, and the one-time login setup — with the exact command for each one.
- **Trying to understand how the code fits together?** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) covers the folder layout, what happens when you click Generate, and where to start reading.
- **Already running it and need to operate it day to day?** [docs/MAINTENANCE.md](docs/MAINTENANCE.md) has restarts, logs, backups, key rotation, and the common things that go wrong.
- **Putting this on a server?** [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) covers what's different from a local run — securing Keycloak, persisting data, and confirming a deployment actually works.
- **Need one specific environment variable?** The full list is in [backend/config/ENVIRONMENT_GUIDE.md](backend/config/ENVIRONMENT_GUIDE.md).
- **Curious what changed recently, or what a run costs?** [CHANGELOG.md](CHANGELOG.md) and [docs/COST_ESTIMATE.md](docs/COST_ESTIMATE.md).

## Quick Start

If you just want to see it running and will read [docs/SETUP.md](docs/SETUP.md) for anything that doesn't work:

```powershell
copy backend\config\.env.example backend\.env
notepad backend\.env
docker compose up --build
```

Then open `http://127.0.0.1:8000/News.html`. Note that Generate won't work yet at this point — that needs the one-time Keycloak login setup, which is Step 4 in [docs/SETUP.md](docs/SETUP.md).

## Project Structure

```text
backend/
  pipeline/        # discovery -> fetching -> filtering -> modeling -> enrichment
  server/          # HTTP API, auth, versioning, PDF export
  auth/            # Keycloak + local-viewer login
  config/          # environment defaults and shared settings
  logging/         # pipeline run logging
  interfaces/      # external model (OpenAI/Gemini) interfaces
frontend/          # review UI (News.html) and static assets
prompts/           # isolated model prompts for news, courses, films
docker/
  compose/        # one file per service (app, postgres, keycloak, searxng, qdrant), assembled by docker-compose.yml
  postgres/       # PostgreSQL image + backup/entrypoint scripts
docs/              # setup, architecture, deployment, maintenance guides
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how these pieces fit together at runtime.
