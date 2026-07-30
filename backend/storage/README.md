# Storage

This folder documents storage ownership. Runtime storage still lives in the mounted paths used by the application and Docker.

## Active Storage Locations

- `data/`: Docker-mounted generated newsletter data and exports.
- `backend/pipeline/fetching/news_fetch_state.json`: query rotation and fetch-state memory used by news, course, and film fetchers.
- `backend/sector_terms_history.json`: historical trace of terms found in selected stories; currently not consumed by query generation.
- `backend/pipeline/tool_discovery/monthly_tools-site.json`: tool registry and official-site seed data.
- `data/news/runtime/newsletter_settings.json`: newsletter title, footer, issue number, and date override.
- `qdrant_data`: Docker volume for Qdrant semantic-memory vectors.
- `postgres_data`: Docker volume for saved newsletter versions, the course catalog, course selection events, and platform rotation state.
- `minio_data`: Docker volume holding the active pgBackRest S3-compatible
  repository, including PostgreSQL backups and WAL archives.
- `postgres_backups`: mounted at `/backups` by the PostgreSQL Compose service,
  but the current pgBackRest configuration uses MinIO (`repo1-type=s3`) and no
  active project script writes SQL backups to this volume. Treat it as a
  compatibility/unused mount until confirmed otherwise.

## Storage Reasoning

Generated state is separated from source code when Docker runs by mounting `/app/data` and named database volumes.

Course history is stored in PostgreSQL rather than long-lived JSON files.
Qdrant remains a secondary semantic-duplicate index for news, courses, and
movies, including manually entered cards when a newsletter is published.
`backend/storage/manage_versions/seeds/initial_versions.db` is read-only seed
data used only when the PostgreSQL versions table is empty.
