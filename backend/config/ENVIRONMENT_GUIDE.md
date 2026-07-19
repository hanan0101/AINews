# Environment Guide

Create `backend/.env` from `backend/config/.env.example`.

## Core Server

- `HOST`: bind address. Default local value is `127.0.0.1`; use `0.0.0.0` in Docker/server deployments.
- `GENERATOR_TIMEOUT`: maximum Generate wait time in seconds. Default: `600`. Increase only for slow API/network conditions.
- `AUTO_FETCH_COOLDOWN`: minimum seconds between automatic fetches. Default: `300`.

## Model Keys

- `OPENAI_API_KEY`: enables OpenAI model calls.
- `AI_UPDATES_OPENAI_MODEL`: OpenAI model name. Default in code: `gpt-5.2`.
- `GEMINI_API_KEY` or `GOOGLE_API_KEY`: enables Gemini model calls.
- `AI_UPDATES_MODEL_PROVIDER`: active provider. Default delivery mode: `gemini`.
- `GEMINI_NEWS_MODEL`: Gemini model for newsletter selection. Free-tier default: `gemini-2.5-flash`.
- `GEMINI_REWRITE_MODEL`: Gemini model for rewrite endpoints. Free-tier default: `gemini-2.5-flash`.
- `GEMINI_FLASH_MODEL`: Gemini model used by all JSON model calls. Free-tier default: `gemini-2.5-flash`.
- `GEMINI_DAILY_REQUEST_BUDGET`: local daily Gemini request budget. Default: `18`, leaving room under the observed 20-request free-tier cap.
- `GEMINI_FULL_RUN_REQUEST_BUDGET`: maximum Gemini model calls per run. Default: `6`.
- `GEMINI_MIN_SECONDS_BETWEEN_CALLS`: minimum delay between Gemini calls. Default: `6`.
- `GEMINI_STOP_ON_QUOTA`: stop cleanly when local or provider quota is exhausted. Default: `1`.

Gemini free-tier limits are project-level, not key-level; changing only the API key may not reset quota if it belongs to the same Google Cloud project.

## Search And Discovery

- `AI_UPDATES_SEARXNG_URL`: SearXNG base URL. Docker default: `http://searxng:8080`.
- `EXA_API_KEY`: enables Exa search.
- `AI_UPDATES_LOOKBACK_DAYS`: how far back news searches look. Default: `7`.
- `AI_UPDATES_SEARXNG_QUERY_LIMIT`: max SearXNG queries per run. Default: `40`.
- `AI_UPDATES_EXA_QUERY_LIMIT`: max Exa queries per run. Default: `28`.
- `AI_UPDATES_TOOL_DISCOVERY_ENABLED`: enables tool registry discovery. Default: `1`.

## Newsletter Size

- `AI_UPDATES_VISIBLE_COUNT`: visible news cards. Default: `4`.
- `AI_UPDATES_BACKUP_COUNT`: hidden replacement news cards. Default: `8`.
- `AI_UPDATES_COURSES_VISIBLE_COUNT`: visible courses. Default: `2`.
- `AI_UPDATES_MOVIES_VISIBLE_COUNT`: visible films. Default: `1`.
- `AI_UPDATES_MIN_NEWS_SAVE_COUNT`: minimum news cards allowed for a partial save. Default: `6`.

## Supporting Content

- `AI_UPDATES_REFRESH_SUPPORTING_CONTENT`: refresh courses/films after Generate. Default: `1`.
- `AI_UPDATES_SUPPORTING_COURSE_FETCH_POOL`: course candidate pool. Default: `24`.
- `AI_UPDATES_SUPPORTING_MOVIE_FETCH_POOL`: film candidate pool. Default: `40`.

## Memory

- `AI_UPDATES_MEMORY_ENABLED`: enables memory checks.
- `AI_UPDATES_SEMANTIC_MEMORY_ENABLED`: enables Qdrant semantic duplicate checks.
- `AI_UPDATES_QDRANT_URL`: Qdrant HTTP URL. Docker default: `http://qdrant:6333`. Leave empty for local embedded fallback.
- `AI_UPDATES_QDRANT_API_KEY`: optional Qdrant API key for secured deployments.
- `AI_UPDATES_QDRANT_COLLECTION`: Qdrant collection name. Default: `content_memory`.
- `AI_UPDATES_SEMANTIC_DUPLICATE_SCORE`: old-story duplicate threshold. Default: `0.925`.
- `AI_UPDATES_SAME_RUN_SEMANTIC_SCORE`: same-run duplicate threshold. Default: `0.90`.
- `AI_UPDATES_MEMORY_EXACT_LIMIT`: maximum exact-memory records loaded. Default: `3000`.

## Output Paths

- `NEWS_JSON_PATH`: newsletter JSON output. Default: `data/news/runtime/news.json`.
- `PREVIOUS_NEWS_JSON_PATH`: previous output snapshot path.
- `AI_UPDATES_RUN_REPORT_PATH`: model/run report output. Default: `data/news/diagnostics/ai_updates_run_report.json`.
- `MODEL_USAGE_SUMMARY_PATH`: model/quota state. Default: `data/news/runtime/model_usage_summary.json`.
- `VERSIONS_BACKUP_DIR`: version backup directory.

## Auth And Database

- `KEYCLOAK_SERVER_URL`: Keycloak URL.
- `KEYCLOAK_REALM`: realm name.
- `KEYCLOAK_CLIENT_ID`: app client id.
- `KEYCLOAK_CLIENT_SECRET`: app client secret.
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`: PostgreSQL version-store settings.
