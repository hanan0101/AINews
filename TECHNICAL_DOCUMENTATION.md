# Technical Documentation

## Technical System Overview

The system is a Python backend plus static frontend for producing an Arabic AI newsletter. The backend owns discovery, filtering, model selection, card enrichment, persistence, authentication checks, versioning, and PDF export. The frontend reads the generated newsletter JSON and lets editors review, edit, replace, reorder, and export cards.

The pipeline is intentionally stage-based now. Each stage has one clear job and passes plain dictionaries/lists to the next stage. This keeps the code understandable without introducing a heavy framework.

## Architecture

1. `backend/server/http_server.py` serves the UI and API.
2. Generate calls `backend/pipeline/orchestrator.py`.
3. The orchestrator calls discovery/fetch/filter/model/enrichment stages in order.
4. Enrichment saves newsletter JSON and run reports.
5. The server exposes the saved state to the frontend and version/PDF routes.

## Data Flow

1. Tool discovery builds query rows from the tool registry and official-site data.
2. Fetching collects raw candidates from SearXNG, Exa, course sources, and TMDB.
3. Filtering normalizes, deduplicates, removes weak candidates, and checks memory.
4. Modeling sends compact candidates to OpenAI/Gemini-compatible selection routines.
5. Enrichment converts selected updates into frontend cards and applies logos, ids, sectors, and supporting content.
6. The server persists edits, versions, and exports.

## Folder-To-Stage Map

- `backend/pipeline/tool_discovery`: query construction, tool registry management, official-site lookup, and diagnostics.
- `backend/pipeline/fetching`: live source calls and candidate normalization for news, courses, and films.
- `backend/pipeline/filtering`: recency checks, duplicate detection, memory filtering, supporting-content filtering, and level balancing.
- `backend/pipeline/modeling`: prompt text, token estimates, model calls, output validation, diversity balancing, and report saving.
- `backend/pipeline/enrichment`: final card identity, logo candidates, newsletter JSON saving, supporting course/film application.
- `backend/pipeline/orchestrator.py`: execution order, timings, retries, progress callbacks, and audit file writes.
- `backend/config`: environment parsing and shared constants.
- `backend/logging`: run ids, JSONL events, stage timing, and summary helpers.
- `backend/interfaces`: external model interfaces. Gemini is here, and OpenAI-related model switching remains preserved.
- `backend/server`: HTTP routes, auth, store mutation, version routes, PDF export, and single-card refill.
- `backend/utils`: shared text cleanup, debug timeline helpers, and PDF rendering helpers.

## Key Technical Decisions

- Stage folders mirror the real workflow, so new contributors can follow data movement from discovery to saved card.
- OpenAI and Gemini support is retained because model switching is a planned capability.
- Obsolete compatibility wrappers under `backend/pipeline/ai_update_pipeline` were removed after active code moved to the new paths.
- Docker remains one application container for the backend because Generate progress, server state, and frontend APIs are coupled at runtime. Search, auth, and database are separate containers because they are independent services.
- Hardcoded thresholds are centralized in `backend/config/settings.py` where possible and documented near the value that operators would change.

## Runtime Outputs

- `NEWS_JSON_PATH`: final frontend newsletter JSON.
- `AI_UPDATES_RUN_REPORT_PATH`: latest model/run report.
- `backend/logs/ai_updates_run.jsonl`: structured pipeline events.
- `backend/news_fetch_state.json`: query rotation and fetch memory.
- `backend/sector_terms_history.json`: sector term learning state.
- PostgreSQL: saved versions and export metadata.
- Qdrant directory/volume: semantic duplicate memory.

## How To Read The Code

Start with `backend/pipeline/orchestrator.py`. It shows the whole flow in order. Then read the stage modules only when you need details:

1. `tool_discovery` to understand query sources.
2. `fetching/sources.py` to understand external APIs and candidate shape.
3. `filtering/candidates.py` to understand why items are removed.
4. `modeling/selection.py` to understand prompts and model output requirements.
5. `enrichment/cards.py` to understand the final JSON shape used by the frontend.
6. `server/http_server.py` to understand API routes and UI integration.
