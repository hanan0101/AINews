# Run Guide

Use this guide for normal operation.

## Start Locally

```powershell
python -m backend.server.http_server
```

Open `http://127.0.0.1:8000/News.html`.

## Start With Docker

```powershell
docker compose up -d
docker compose logs -f ainewsletter
```

## Generate A Newsletter

1. Open `News.html`.
2. Sign in as an admin user.
3. Click Generate.
4. Watch the progress timeline: source fetch, filtering and memory, AI model selection, save, courses and films.
5. Review cards, replace weak cards, edit text, and export when ready.

## Run A Focused Backend Test

```powershell
python -m unittest backend.tests.test_course_fetchers
```

## Important Output Files

- `frontend/news.json`: current newsletter output unless `NEWS_JSON_PATH` overrides it.
- `frontend/ai_updates_run_report.json`: latest model/run report unless overridden.
- `backend/news_fetch_state.json`: query rotation and fetch state.
- `backend/sector_terms_history.json`: learned sector-term history.
- `backend/logs/ai_updates_run.jsonl`: pipeline events.

## Common Operations

Restart Docker app: `docker compose restart ainewsletter`.
View logs: `docker compose logs -f ainewsletter`.
Run PostgreSQL backup: `docker compose exec postgres /usr/local/bin/postgres-backup`.
