# AI Newsletter System

This project builds and serves an AI-newsletter workflow for Arabic editorial review. It discovers recent AI product updates, filters duplicates and weak sources, asks the configured model to select and rewrite cards, enriches the cards with logos/metadata, and serves the result through a local web UI.

## What The System Does

- Finds AI updates from tool registries, official sites, Exa, and SearXNG.
- Fetches supporting courses and AI-themed films.
- Filters stale, duplicate, low-quality, or off-topic candidates.
- Uses OpenAI or Gemini-compatible model calls for editorial selection and rewriting.
- Saves the newsletter JSON consumed by the frontend.
- Stores versions and PDF exports through the backend server.

## Main Folders

- `backend/pipeline/tool_discovery`: tool registry, official-site lookup, query building, diagnostics.
- `backend/pipeline/fetching`: live candidate fetching for news, courses, and films.
- `backend/pipeline/filtering`: quality filtering, deduplication, and memory checks.
- `backend/pipeline/modeling`: prompt construction and model-based selection.
- `backend/pipeline/enrichment`: final newsletter card shaping and JSON saving.
- `backend/pipeline/courses`, `backend/pipeline/films`, `backend/pipeline/news`: content-type entrypoints for each stage.
- `backend/pipeline/orchestrator.py`: runs the full pipeline in order.
- `prompts`: isolated model prompts for courses, films, and news.
- `backend/config`: environment defaults and shared settings.
- `backend/logging`: pipeline run logging.
- `backend/interfaces`: external model/client interfaces.
- `backend/server`: HTTP API, auth, versioning, PDF export, and frontend serving.
- `frontend`: review UI and static assets.
- `docker`: container support, including PostgreSQL backup scripts.

## Quick Start

1. Create `backend/.env` from `backend/config/.env.example`.
2. Install dependencies: `pip install -r requirements.txt`.
3. Start the server: `python -m backend.server.http_server`.
4. Open `http://127.0.0.1:8000/News.html`.

For daily operating steps, see `RUN_GUIDE.md`. For server deployment, see `DEPLOYMENT.md`.
