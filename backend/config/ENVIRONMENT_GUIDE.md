# Environment Guide

Create `backend/.env` from `backend/.env.example`.

## Core Server

- `HOST`: bind address. Default local value is `127.0.0.1`; use `0.0.0.0` in Docker/server deployments.
- `GENERATOR_TIMEOUT`: maximum Generate wait time in seconds. Default: `600`. Increase only for slow API/network conditions.
- `AUTO_FETCH_COOLDOWN`: minimum seconds between automatic fetches. Default: `300`.

## Model Keys

- `OPENAI_API_KEY`: enables OpenAI model calls.
- `AI_UPDATES_OPENAI_MODEL`: OpenAI model name. Default in code: `gpt-5.2`.
- `GEMINI_API_KEY` or `GOOGLE_API_KEY`: enables Gemini model calls.
- `AI_UPDATES_MODEL_PROVIDER`: active provider. Default delivery mode: `gemini`.
- `GEMINI_NEWS_MODEL`: compatibility/news model value. Default: `gemini-flash-latest`.
- `GEMINI_SELECTION_MODEL`: model used for news and supporting-content selection. Code default: `gemini-flash-lite-latest`; the checked runtime overrides it with `gemini-flash-latest`.
- `GEMINI_REWRITE_MODEL`: model used for Arabic rewriting. Code default: `gemini-flash-latest`; the checked runtime overrides it with `gemini-3.1-pro-preview`.
- `GEMINI_EMBEDDING_MODEL`: model used directly by the Gemini embedding client. Default: `gemini-embedding-001`.
- `GEMINI_FLASH_MODEL`: fallback model for Gemini JSON calls without an explicit role. Default: `gemini-flash-latest`.
- `GEMINI_DAILY_REQUEST_BUDGET`: local tracking threshold. Current code and checked runtime default: `120`.
- `GEMINI_FULL_RUN_REQUEST_BUDGET`: optional per-run threshold. `0` disables the per-run cap; this is the current default.
- `GEMINI_MIN_SECONDS_BETWEEN_CALLS`: minimum delay between Gemini calls. Default: `6`.
- `GEMINI_STOP_ON_QUOTA`: enforce the local budget thresholds when `1`. Current default: `0`; provider-side quota errors are still reported.

The local budget values are operational controls, not statements of a
provider's current quota. Provider limits and model aliases can change and must
be checked separately.

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
- `AI_UPDATES_COURSES_VISIBLE_COUNT`: visible courses. Default: `6`.
- `AI_UPDATES_MOVIES_VISIBLE_COUNT`: visible films. Default: `2`.
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

- `KEYCLOAK_SERVER_URL`: Keycloak URL. Docker default: `http://keycloak:8080/`.
- `KEYCLOAK_REALM`: realm name. Default: `newsletter`.
- `KEYCLOAK_CLIENT_ID`: app client id. Default: `newsletter-app`.
- `KEYCLOAK_CLIENT_SECRET`: app client secret. Default: `dev-local-secret` — change before any shared/production use, since bootstrap provisions the Keycloak client with whatever this resolves to.
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`: PostgreSQL version-store settings.

### Keycloak bootstrap (`backend/auth/keycloak_bootstrap.py`)

A fresh Keycloak volume comes up empty; this runs automatically on app startup and provisions the realm, client, `admin`/`user` roles, and one ready-to-use admin account through Keycloak's Admin REST API. It's idempotent — it checks whether the realm already exists first, so it's a no-op on every subsequent startup.

- `KEYCLOAK_ADMIN_URL`: Admin REST API base URL used only by bootstrap. Default: same as `KEYCLOAK_SERVER_URL`.
- `KEYCLOAK_BOOTSTRAP_ADMIN_USER` / `KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD`: credentials bootstrap uses to authenticate against Keycloak's master realm to do the provisioning. Default: `admin` / `admin123` — matches `docker/compose/keycloak.yml`'s `KEYCLOAK_ADMIN`/`KEYCLOAK_ADMIN_PASSWORD`.
- `KEYCLOAK_BOOTSTRAP_USER` / `KEYCLOAK_BOOTSTRAP_USER_PASSWORD`: the one app-level admin account bootstrap creates in the new realm, with the `admin` role. Default: `admin` / `admin123`.
- `KEYCLOAK_BOOTSTRAP_WAIT_SECONDS`: how long to poll Keycloak's `/realms/master` before giving up on bootstrap for this startup. Default: `60`.
- `KEYCLOAK_ACCESS_TOKEN_LIFESPAN_SECONDS`: realm access-token lifetime, applied on every startup (not just first bootstrap). Default: `7200` (2 hours).

### Session cookies and local viewer login

- `AUTH_COOKIE_NAME` / `AUTH_REFRESH_COOKIE_NAME`: cookie names for the access/refresh tokens.
- `AUTH_COOKIE_SECURE`: set to `1` once the server is behind HTTPS, so cookies require TLS.
- `LOCAL_VIEWER_AUTH_ENABLED`: enables the non-Keycloak, view-only fallback login. Default on.
- `LOCAL_VIEWER_USERNAME` / `LOCAL_VIEWER_PASSWORD`: credentials for that fallback login. Default: `news` / `news123`.
- `LOCAL_AUTH_SECRET`: signing secret for locally-issued session tokens.
- `LOCAL_VIEWER_TOKEN_TTL_SECONDS`: how long a local-viewer session stays valid.

### Postgres backups (pgBackRest + MinIO)

See [docs/MAINTENANCE.md](../../docs/MAINTENANCE.md#backups--restore) for how these fit together; all are optional and default to working out of the box with the bundled `minio` service.

- `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`: MinIO credentials, also used natively by pgBackRest as its S3 key/secret unless overridden below. Change these for anything beyond local dev.
- `PGBACKREST_REPO1_S3_KEY` / `PGBACKREST_REPO1_S3_KEY_SECRET`: set only if pgBackRest should use a scoped MinIO user instead of the root credentials above.
- `PGBACKREST_CRON_INCR` / `PGBACKREST_CRON_DIFF` / `PGBACKREST_CRON_FULL`: cron schedules for incremental/differential/full backups. Defaults: daily at 02:00, weekly on Sunday at 02:00, monthly on the 1st at 02:00.
- `SQLITE_VERSIONS_PATH`: only used by the one-time `backend/storage/manage_versions/migrate_versions_to_postgres.py` script, which migrated version history out of the legacy SQLite database. Default: `data/versions/versions.db`.
