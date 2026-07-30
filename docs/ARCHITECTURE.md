# Architecture

Read this to understand how the code is organized and how a request or a "Generate" run flows through the system. For setup instructions, see [SETUP.md](SETUP.md). For the file-by-file reading order, jump to [How to Read the Code](#how-to-read-the-code).

## System Overview

The system is a Python backend plus a static HTML/JS frontend that produces an Arabic AI newsletter. The backend owns discovery, filtering, model selection, card enrichment, persistence, authentication, versioning, and PDF export. The frontend (`frontend/News.html`) reads the generated newsletter JSON and lets editors review, edit, replace, reorder, and export cards.

The generation pipeline is stage-based: each stage has one job and passes plain dictionaries/lists to the next stage. There is no heavyweight framework in the pipeline itself.

## Services

| Service | Role | Required for |
| --- | --- | --- |
| `ainewsletter` (this app) | HTTP server, pipeline orchestration, UI serving | Everything |
| PostgreSQL | Stores newsletter versions and the durable course catalog/selection history | Version history, export tracking, long-term course rotation |
| Keycloak | Authentication provider (roles: `admin`, `user`); self-provisions its realm/client/roles/admin user on first startup | Login, admin-gated actions like Generate |
| SearXNG | Self-hosted metasearch used by discovery | News/course source fetching |
| Qdrant | Vector database | Semantic duplicate detection across runs |
| Exa API (external) | Live news/course search | News/course discovery |
| TMDb API (external) | Film metadata | Optional AI-film suggestions |
| Gemini API (active configuration) | Selection, Arabic rewrite, and embeddings | Editorial judgment, rewriting, semantic duplicate memory |
| OpenAI API (optional provider) | Alternative editorial model and embeddings | Used only when `AI_UPDATES_MODEL_PROVIDER=openai` |

## Request / Generation Flow

1. `backend/server/http_server.py` serves the UI and the HTTP API.
2. The **Generate** action calls `backend/pipeline/orchestrator.py`.
3. The orchestrator runs the pipeline stages in order: tool discovery → fetching → filtering → modeling (selection and rewrite) → enrichment.
4. Enrichment saves the newsletter JSON and a run report.
5. The server exposes the saved state to the frontend, plus version history and PDF export routes.

## Data Flow (inside a Generate run)

1. **Tool discovery** builds query rows from the tool registry and official-site data.
2. **Fetching** collects raw candidates from SearXNG, Exa, course sources, and TMDb.
3. **Filtering** normalizes candidates, deduplicates them (including semantic dedup via Qdrant), removes weak candidates, and checks memory of previously-used items.
4. **Modeling** sends compact candidate summaries to the configured provider.
   News and supporting-content selection use the selection role; Arabic news
   rewriting uses the rewrite role. Deterministic checks then reject stale
   events, unsupported claims, and summaries outside 50–64 Arabic words.
5. **Enrichment** converts selected updates into frontend-ready cards: identity, logos, sector tags, and supporting course/film content.
6. The server persists edits, versions and course selection history (PostgreSQL), and exports (PDF). Published manual cards are also indexed in Qdrant.

## Folder-to-Stage Map

| Folder | Responsibility |
| --- | --- |
| `backend/pipeline/tool_discovery` | Query construction, tool registry management, official-site lookup, diagnostics |
| `backend/pipeline/fetching/content/{news,courses,films}` | Live source calls and candidate normalization, separated by content type |
| `backend/pipeline/filtering/content/{news,courses,films}` | Content-specific recency, quality, level, and rejection rules |
| `backend/pipeline/filtering/shared` | Duplicate memory and rules shared by courses and films |
| `backend/pipeline/modeling/content/{news,courses,films}` | Content-specific prompts and model-selection entry points |
| `backend/pipeline/modeling/shared` | Course/film selection infrastructure shared by both types |
| `backend/pipeline/enrichment/content/{news,courses,films}` | Final card assembly separated by content type |
| `backend/pipeline/enrichment/shared` | Logo and course/film enrichment used by multiple content types |
| `backend/pipeline/orchestrator.py` | Execution order, timings, retries, progress callbacks, audit file writes |
| `news.py`, `courses.py`, `films.py` (one per stage folder) | Compatibility entrypoints; new code should use the matching `content/<type>` package |
| `backend/config` | Environment parsing and shared constants (`settings.py`, `.env.example`, `ENVIRONMENT_GUIDE.md`) |
| `backend/logging` | Run ids, JSONL event logging, stage timing, summary helpers |
| `backend/pipeline/modeling/{gemini_client,openai_client,model_client}.py` | External model interfaces and role/provider switching |
| `backend/auth` | Keycloak integration plus the local view-only fallback login |
| `backend/server` | HTTP routes, auth enforcement, store mutation, version routes, PDF export, single-card refill |
| `backend/utils` | Shared text cleanup, debug timeline helpers, PDF rendering helpers |
| `frontend/News.html` | Markup shell only; it no longer embeds the application CSS or JavaScript |
| `frontend/news.css` | Newsletter page and editor styles |
| `frontend/newsletter-core.js` | API client, authentication state, shared page state, and basic actions |
| `frontend/newsletter-rendering.js` | Card and newsletter rendering and view filters |
| `frontend/newsletter-card-actions.js` | Edit, replace, navigate, drag/drop, and logo actions |
| `frontend/newsletter-export-history.js` | PDF/export, undo/redo, pinning, and settings |
| `frontend/newsletter-generation.js` | Generate progress, state loading, and page boot |
| `frontend/shared-functions.js` | Small browser helpers shared by `News.html` and `versions.html` |
| `docker` | Container and Compose support |

## Key Technical Decisions

- Stage folders mirror the real workflow so new contributors can follow data movement from discovery to a saved card without needing a framework-level map.
- The checked deployment configuration uses Gemini. OpenAI support is retained
  as an explicit runtime alternative through `AI_UPDATES_MODEL_PROVIDER`; it is
  not included in the Gemini cost workbook.
- Gemini roles are separate: selection uses `GEMINI_SELECTION_MODEL`, rewrite
  uses `GEMINI_REWRITE_MODEL`, and embeddings use
  `GEMINI_EMBEDDING_MODEL` directly in the Gemini client.
- Saved-version titles come from the newsletter's explicit requested title
  when present, otherwise from its current issue number and month metadata.
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
2. `backend/pipeline/fetching/content/news/` — news queries, source adapters, dates, normalization, merge, tracker, and runtime
3. `backend/pipeline/fetching/content/courses/` and `content/films/` — supporting-content discovery
4. `backend/pipeline/filtering/content/{news,courses,films}/` — rules for the relevant content type
5. `backend/pipeline/filtering/shared/memory.py` — duplicate and semantic-memory removal
6. `backend/pipeline/modeling/content/{news,courses,films}/` — active prompts and selection entry points
7. `backend/pipeline/modeling/content/news/selection.py` — detailed news selection and deterministic validation
8. `backend/pipeline/enrichment/content/{news,courses,films}/` — final JSON/card assembly
9. `backend/storage/newsletter_store.py` — editable/published state and edition date
10. `backend/storage/manage_versions/versions_db.py` — version persistence and title helpers
11. `backend/server/http_server.py` — API routes and UI integration
