# Storage

This folder documents storage ownership. Runtime storage still lives in the mounted paths used by the application and Docker.

## Active Storage Locations

- `data/`: Docker-mounted generated newsletter data and exports.
- `backend/news_fetch_state.json`: query rotation and fetch-state memory.
- `backend/sector_terms_history.json`: learned sector terms for future query quality.
- `backend/monthly_tools-site.json`: tool registry and official-site seed data.
- `qdrant_data`: Docker volume for Qdrant semantic-memory vectors.
- `postgres_data`: Docker volume for saved newsletter versions.
- `postgres_backups`: Docker volume for PostgreSQL SQL backups.

## Storage Reasoning

Generated state is separated from source code when Docker runs by mounting `/app/data` and named database volumes.

Small JSON state files remain under `backend/` because the current pipeline reads them directly during local development and Docker bind mounts.
