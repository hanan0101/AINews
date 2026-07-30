# Environment Guide

Create `backend/.env` from `backend/.env.example`, then restart the backend or
container after every change. `backend/.env` contains secrets and must never be
committed. The example file contains names and safe defaults only.

## Required integrations for the complete pipeline

| Variable | Current role | Why it is needed |
|---|---|---|
| `GEMINI_API_KEY` | Gemini authentication | Required while `AI_UPDATES_MODEL_PROVIDER=gemini`. It is used by selection, Arabic rewriting, supporting-content selection, embeddings, and AI tool discovery. Use this exact variable name. |
| `EXA_API_KEY` | Exa Search authentication | Used for live news discovery, course discovery, recent-page verification, tracker discovery, and official-site/tool discovery. Without it, Exa lanes are skipped and discovery relies on the remaining sources. |
| `TMDB_API_KEY` | TMDB authentication | Used by `backend/pipeline/fetching/content/films/discovery.py` to discover AI-related films. Without it, the TMDB film lane is skipped. |

`OPENAI_API_KEY` is not required in the checked configuration because the active
provider is Gemini. It is needed only after explicitly setting
`AI_UPDATES_MODEL_PROVIDER=openai`.

## Model names used now

| Variable | Checked value | Used for |
|---|---|---|
| `AI_UPDATES_MODEL_PROVIDER` | `gemini` | Selects the active model provider. |
| `GEMINI_SELECTION_MODEL` | `gemini-3.5-flash` | News selection and supporting-content selection. |
| `GEMINI_REWRITE_MODEL` | `gemini-3.1-pro-preview` | Arabic editorial rewriting. This role can require paid quota on the configured Google project. |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Semantic-memory embeddings. |
| `GEMINI_FLASH_MODEL` | `gemini-3.5-flash` | Default Gemini JSON model when a call does not request a more specific role. |
| `AI_UPDATES_OPENAI_MODEL` | `gpt-5.2` | OpenAI provider model; inactive while the provider remains `gemini`. |

The model names above match both the checked `backend/.env` profile and the
current code. Model aliases and provider quotas are external settings; if a
provider removes an alias, update the environment value rather than hardcoding a
different model elsewhere.

## Checked generation profile

These values intentionally differ from some Python defaults. They reproduce the
current working environment:

| Variable | Checked value | Why it is present |
|---|---:|---|
| `SINGLE_REFILL_SECONDS` | `90` | Progress target for a single news/course/film replacement. It is not a forced thread timeout. |
| `AI_UPDATES_VISIBLE_COUNT` | `4` | News cards shown in the default newsletter view. |
| `NEWS_BACKUP_COUNT` | `14` | Replacement cards retained by the server store. |
| `AI_UPDATES_BACKUP_COUNT` | `14` | Replacement cards requested from the generation pipeline. Keep it equal to `NEWS_BACKUP_COUNT`. |
| `AI_UPDATES_OUTPUT_LIMIT` | `18` | Complete news-bank target: 4 visible + 14 backup cards. |
| `AI_UPDATES_MIN_NEWS_SAVE_COUNT` | `12` | Minimum acceptable news count before replacing the previous newsletter. The complete target remains 18. |
| `AI_UPDATES_GPT_SHORTLIST_LIMIT` | `72` | Maximum filtered candidates sent to model selection. |
| `AI_UPDATES_GPT_COMPACT_LIMIT` | `72` | Maximum compact candidate payload used by the full selection call. |
| `AI_UPDATES_SEARXNG_TIMEOUT` | `16` | Per-request SearXNG timeout in seconds. |
| `AI_UPDATES_GENERAL_NEWS_LAYER_ENABLED` | `1` | Enables the additional general-news discovery lane. |
| `AI_UPDATES_SEMANTIC_DUPLICATE_SCORE` | `0.90` | Semantic threshold used to reject previously covered stories. |
| `GEMINI_MIN_SECONDS_BETWEEN_CALLS` | `6` | Local pacing between Gemini calls. |

The two backup-count variables have different readers and are both necessary:
`NEWS_BACKUP_COUNT` controls server persistence, while
`AI_UPDATES_BACKUP_COUNT` controls the pipeline target.

## Search and supporting content

- `AI_UPDATES_SEARXNG_URL`: SearXNG base URL. Docker sets
  `http://searxng:8080`; use `http://localhost:8080` only when the backend runs
  outside Docker and SearXNG is exposed locally.
- `AI_UPDATES_LOOKBACK_DAYS`: news freshness window. Python default: `7`.
- `AI_UPDATES_EXA_QUERY_LIMIT`: maximum full-run Exa query count. Python
  default: `28`.
- `AI_UPDATES_SEARXNG_QUERY_LIMIT`: maximum full-run SearXNG query count.
  Python default: `40`.
- `AI_UPDATES_REFRESH_SUPPORTING_CONTENT`: refresh courses and films during a
  full generation. Default: `1`.
- `AI_UPDATES_SUPPORTING_COURSE_FETCH_POOL`: course candidate-pool size.
  Default: `24`.
- `AI_UPDATES_SUPPORTING_MOVIE_FETCH_POOL`: film candidate-pool size.
  Default: `40`.
- `AI_UPDATES_MOVIE_ROTATION_MAX_PAGE`: TMDB page-rotation ceiling. Default:
  `6`.

The detailed tuning variables remain in `backend/.env.example`. Leave them
commented unless a measured run shows a reason to override the code default.

## Semantic memory

- `AI_UPDATES_MEMORY_ENABLED`: enables exact publication-memory checks.
- `AI_UPDATES_SEMANTIC_MEMORY_ENABLED`: enables semantic duplicate checks.
- `AI_UPDATES_QDRANT_URL`: Qdrant HTTP URL. Docker uses
  `http://qdrant:6333`; an empty value uses the local embedded fallback.
- `AI_UPDATES_QDRANT_API_KEY`: required only for a secured external Qdrant.
- `AI_UPDATES_QDRANT_COLLECTION`: collection name. Default:
  `content_memory`.
- `AI_UPDATES_SAME_RUN_SEMANTIC_SCORE`: same-run duplicate threshold. Default:
  `0.90`.
- `AI_UPDATES_MEMORY_EXACT_LIMIT`: maximum exact-memory records loaded.
  Default: `3000`.

## Server and generated files

- `HOST`: local default `127.0.0.1`; Docker sets `0.0.0.0`.
- `AUTO_FETCH_COOLDOWN`: minimum interval between automatic fetch starts.
  Default: `300` seconds.
- `NEWS_JSON_ONLY_MODE`: set `1` only to disable live generation and serve the
  stored newsletter.
- `NEWS_JSON_PATH`: current newsletter JSON path.
- `PREVIOUS_NEWS_JSON_PATH`: previous-newsletter snapshot path.
- `AI_UPDATES_RUN_REPORT_PATH`: diagnostic run report.
- `MODEL_USAGE_SUMMARY_PATH`: local model usage/quota state.

The paths are normally left unset because local execution and Docker already
provide the correct locations.

## Authentication and database

Docker supplies the service hostnames. Set these manually only when the backend
runs outside the Compose stack:

- `KEYCLOAK_SERVER_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, and
  `KEYCLOAK_CLIENT_SECRET`.
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and
  `POSTGRES_PASSWORD`.
- `AI_UPDATES_QDRANT_URL`.

For a shared or production deployment, replace all development passwords and
secrets, set `AUTH_COOKIE_SECURE=1` behind HTTPS, and align
`KEYCLOAK_BOOTSTRAP_ADMIN_USER` / `KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD` with the
Keycloak service credentials.

`SQLITE_VERSIONS_PATH` is not part of normal runtime. It is read only by the
one-time `backend/storage/manage_versions/migrate_versions_to_postgres.py`
migration script.

## What should stay out of Git

- `backend/.env`
- API keys for Gemini, Exa, TMDB, OpenAI, or Qdrant
- Keycloak client/bootstrap secrets and user passwords
- PostgreSQL passwords
- local authentication signing secrets

Commit `backend/.env.example` and this guide; keep actual values only in the
local/server environment or a secrets manager.
