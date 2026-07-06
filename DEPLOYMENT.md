# Deployment Guide

This file covers what is needed to move the project to a server.

## Requirements

- Python 3.11+
- Docker and Docker Compose for the recommended deployment path
- Network access from the server to model/search APIs
- API keys configured in `backend/.env`
- Persistent storage for `data`, PostgreSQL, and Qdrant memory

## Required Environment File

Create `backend/.env` from `backend/config/.env.example`, then review `backend/config/ENVIRONMENT_GUIDE.md`.

At minimum, configure model/search keys, host settings, Keycloak values, and PostgreSQL credentials.

## Docker Deployment

From the project root:

```powershell
docker compose up -d --build
```

Main containers:

- `ainewsletter`: runs `python -m backend.server.http_server`.
- `postgres`: stores newsletter versions and scheduled backups.
- `searxng`: local metasearch used by discovery.
- `keycloak`: authentication provider.

Check status:

```powershell
docker compose ps
docker compose logs -f ainewsletter
```

Open `http://SERVER_HOST:8000/News.html`.

## Persistent Data

Keep these mounted or backed up:

- `data`: generated newsletter state and exported files.
- `postgres_data`: version records.
- `postgres_backups`: SQL backups.
- `qdrant_data`: semantic-memory vectors.
- `backend/.env`: secrets and runtime settings.

## Manual Python Deployment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m backend.server.http_server
```

You still need PostgreSQL, Keycloak, and SearXNG reachable through `backend/.env`.

## Post-Deployment Checks

```powershell
python -m unittest backend.tests.test_course_fetchers
```

Then confirm login, `/News.html`, Generate progress, version export, and `NEWS_JSON_PATH` output.
