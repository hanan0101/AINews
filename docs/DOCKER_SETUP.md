# Docker Setup

The root `docker-compose.yml` assembles one Compose file per service from
`docker/compose/`. Run all Docker commands from the repository root.

## Service Map

| Service | Compose file | Purpose |
| --- | --- | --- |
| `ainewsletter` | `docker/compose/app.yml` | Application server, UI, and generation pipeline |
| `postgres` | `docker/compose/postgres.yml` | Versions, course data, and scheduled SQL backups |
| `keycloak` | `docker/compose/keycloak.yml` | Authentication and roles |
| `searxng` | `docker/compose/searxng.yml` | Self-hosted web search |
| `qdrant` | `docker/compose/qdrant.yml` | Semantic duplicate memory |
| `minio` | `docker/compose/minio.yml` | Object storage |

The root `Dockerfile` builds only the application image. PostgreSQL-specific
image and backup scripts are under `docker/postgres/`.

## Start and Stop

```powershell
docker compose up --build -d
docker compose ps
docker compose logs -f ainewsletter
docker compose down
```

## Recreate After Configuration Changes

Environment variables are loaded when a container is created. After editing
`backend/.env` or a Compose file, recreate the affected service:

```powershell
docker compose up -d --force-recreate ainewsletter
```

Rebuild when application dependencies or the root `Dockerfile` change:

```powershell
docker compose up -d --build ainewsletter
```

## Service-Specific Operations

```powershell
docker compose restart searxng
docker compose logs --tail 100 postgres
docker compose exec postgres /usr/local/bin/postgres-backup
```

For first installation, credentials, ports, and Keycloak setup, see
[SETUP.md](SETUP.md). For production hardening, see
[DEPLOYMENT.md](DEPLOYMENT.md).
