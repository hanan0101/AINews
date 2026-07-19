# Architecture

Read this to understand how the code is organized and how a request or a "Generate" run flows through the system. For setup instructions, see [SETUP.md](SETUP.md). For the file-by-file reading order, jump to [How to Read the Code](#how-to-read-the-code).

## System Overview

The system is a Python backend plus a static HTML/JS frontend that produces an Arabic AI newsletter. The backend owns discovery, filtering, model selection, card enrichment, persistence, authentication, versioning, and PDF export. The frontend (`frontend/News.html`) reads the generated newsletter JSON and lets editors review, edit, replace, reorder, and export cards.

The generation pipeline is stage-based: each stage has one job and passes plain dictionaries/lists to the next stage. There is no heavyweight framework in the pipeline itself.

## Services

| Service | Role | Required for |
| --- | --- | --- |
| `ainewsletter` (this app) | HTTP server, pipeline orchestration, UI serving | Everything |
| PostgreSQL | Stores newsletter versions, the durable course catalog/selection history, and scheduled SQL backups | Version history, export tracking, long-term course rotation |
| Keycloak | Authentication provider (roles: `admin`, `user`) | Login, admin-gated actions like Generate |
| SearXNG | Self-hosted metasearch used by discovery | News/course source fetching |
| Qdrant | Vector database | Semantic duplicate detection across runs |
| Exa API (external) | Live news/course search | News/course discovery |
| TMDb API (external) | Film metadata | Optional AI-film suggestions |
| OpenAI / Gemini API (external) | Embeddings + editorial model | Duplicate detection, card selection/rewriting |

## Request / Generation Flow

1. `backend/server/http_server.py` serves the UI and the HTTP API.
2. The **Generate** action calls `backend/pipeline/orchestrator.py`.
3. The orchestrator runs the pipeline stages in order: tool discovery → fetching → filtering → modeling (AI selection) → enrichment.
4. Enrichment saves the newsletter JSON and a run report.
5. The server exposes the saved state to the frontend, plus version history and PDF export routes.

## Data Flow (inside a Generate run)

1. **Tool discovery** builds query rows from the tool registry and official-site data.
2. **Fetching** collects raw candidates from SearXNG, Exa, course sources, and TMDb.
3. **Filtering** normalizes candidates, deduplicates them (including semantic dedup via Qdrant), removes weak candidates, and checks memory of previously-used items.
4. **Modeling** sends compact candidate summaries to the configured model (OpenAI or Gemini) for selection and rewriting.
5. **Enrichment** converts selected updates into frontend-ready cards: identity, logos, sector tags, and supporting course/film content.
6. The server persists edits, versions and course selection history (PostgreSQL), and exports (PDF). Published manual cards are also indexed in Qdrant.

## Folder-to-Stage Map

| Folder | Responsibility |
| --- | --- |
| `backend/pipeline/tool_discovery` | Query construction, tool registry management, official-site lookup, diagnostics |
| `backend/pipeline/fetching` | Live source calls and candidate normalization for news, courses, and films |
| `backend/pipeline/filtering` | Recency checks, duplicate detection, memory filtering, supporting-content filtering, level balancing |
| `backend/pipeline/modeling` | Prompt text, token estimates, model calls, output validation, diversity balancing, report saving |
| `backend/pipeline/enrichment` | Final card identity, logo candidates, newsletter JSON saving, supporting course/film application |
| `backend/pipeline/orchestrator.py` | Execution order, timings, retries, progress callbacks, audit file writes |
| `backend/pipeline/news`, `backend/pipeline/courses`, `backend/pipeline/films` | Content-type entrypoints for each stage |
| `prompts/` | Isolated model prompts for courses, films, and news |
| `backend/config` | Environment parsing and shared constants (`settings.py`, `.env.example`, `ENVIRONMENT_GUIDE.md`) |
| `backend/logging` | Run ids, JSONL event logging, stage timing, summary helpers |
| `backend/interfaces` | External model interfaces (Gemini client; OpenAI switching logic) |
| `backend/auth` | Keycloak integration plus the local view-only fallback login |
| `backend/server` | HTTP routes, auth enforcement, store mutation, version routes, PDF export, single-card refill |
| `backend/utils` | Shared text cleanup, debug timeline helpers, PDF rendering helpers |
| `frontend` | Review UI (`News.html`) and static assets |
| `docker` | Container support, including the PostgreSQL backup image |

## Key Technical Decisions

- Stage folders mirror the real workflow so new contributors can follow data movement from discovery to a saved card without needing a framework-level map.
- Both OpenAI and Gemini support are retained because model switching (`AI_UPDATES_MODEL_PROVIDER`) is a supported runtime choice, not a one-off migration.
- Docker runs the application as one container because Generate progress, server state, and frontend APIs are coupled at runtime. Search (SearXNG), auth (Keycloak), and the database (PostgreSQL) are separate containers because they are independent services.
- Hardcoded thresholds are centralized in `backend/config/settings.py`, documented near the value an operator would actually change.
- Authentication has two paths by design: Keycloak for real roles/admin access, and a local username/password fallback (`news` / `news123`, `user` role only) so the UI is viewable without standing up Keycloak first.

## Runtime Outputs

| Output | Path (default) |
| --- | --- |
| Editable newsletter JSON | `NEWS_JSON_PATH` (default `data/news/runtime/news.json`) |
| Published newsletter JSON | `data/news/runtime/news_published.json` |
| Model usage and quota state | `data/news/runtime/model_usage_summary.json` |
| Newsletter display settings | `data/news/runtime/newsletter_settings.json` |
| Latest model/run report | `AI_UPDATES_RUN_REPORT_PATH` (default `data/news/diagnostics/ai_updates_run_report.json`) |
| Candidate + course-selection audit | `data/news/diagnostics/ai_updates_candidate_audit.json` |
| Structured pipeline events | `backend/logs/ai_updates_run.jsonl` |
| Query rotation / fetch memory | `backend/pipeline/fetching/news_fetch_state.json` |
| Sector term historical trace (not currently consumed by queries) | `backend/sector_terms_history.json` |
| Tool discovery registry | `backend/pipeline/tool_discovery/monthly_tools-site.json` |
| Saved versions, export metadata, course catalog and course selection events | PostgreSQL |
| Semantic duplicate memory | Qdrant volume/directory |

More detail: [backend/storage/README.md](../backend/storage/README.md) (storage ownership) and [backend/logging/README.md](../backend/logging/README.md) (what gets logged).

## How to Read the Code

Start with `backend/pipeline/orchestrator.py` — it shows the whole flow in order. Then read the stage modules only as you need detail:

1. `backend/pipeline/tool_discovery` — query sources
2. `backend/pipeline/fetching/news_discovery.py` — external APIs and candidate shape (renamed from `sources.py` 2026-07)
3. `backend/pipeline/filtering/memory.py` — why items get removed (dedup/semantic memory)
4. `backend/pipeline/modeling/selection.py` — prompts and model output requirements
5. `backend/pipeline/enrichment/news.py` — final JSON shape consumed by the frontend
6. `backend/server/http_server.py` — API routes and UI integration
