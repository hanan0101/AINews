# AI Newsletter System

An editorial platform for producing Arabic AI newsletters. It discovers recent
AI updates, filters weak or duplicate results, uses an AI model for selection
and rewriting, enriches cards with supporting content, and provides a browser
interface for review, publishing, versioning, and PDF export.

## Features

- News discovery through official sources, tool registries, Exa, and SearXNG.
- Course and AI-film recommendations.
- Exact and semantic duplicate detection with Qdrant.
- Editorial selection and rewriting with Gemini or OpenAI-compatible models.
- Editable newsletter layouts with independent mode and level views.
- Published-version separation from the administrator's working draft.
- Version history, PDF import/export, authentication, and role-based access.

## Services

| Service | Purpose |
| --- | --- |
| Application | HTTP API, editorial UI, generation pipeline, and PDF handling |
| PostgreSQL | Newsletter versions, course catalog, and persistent application data |
| Keycloak | Authentication and administrator roles |
| SearXNG | Web search and candidate discovery |
| Qdrant | Semantic duplicate memory |
| MinIO | Object storage used by the deployment stack |

## Quick Start

Requirements:

- Docker Desktop
- API keys configured in `backend/.env`

Create the environment file:

```powershell
Copy-Item backend\.env.example backend\.env
notepad backend\.env
```

Start the stack:

```powershell
docker compose up --build -d
docker compose logs -f ainewsletter
```

Open:

```text
http://127.0.0.1:8000/News.html
```

Keycloak provisions itself automatically on first startup (realm, client, roles,
and a development-only `admin` / `admin123` account). Change all development
credentials before shared or production use. See [Setup](docs/SETUP.md).

## Repository Structure

```text
backend/
  auth/                         Keycloak and local authentication
  config/                       Environment and pipeline settings
  logging/                      Structured pipeline logging
  pipeline/
    fetching/content/           news / courses / films discovery
    filtering/content/          news / courses / films quality rules
    modeling/content/           news / courses / films prompts and selection
    enrichment/content/         news / courses / films card enrichment
    */shared/                   Logic genuinely shared across content types
    tool_discovery/             Tool registry and official-site discovery
  server/                       HTTP routes and PDF services
  services/                     Shared service integrations
  storage/                      PostgreSQL repositories and version management
  tests/                        Automated tests
frontend/                       HTML shell, CSS, and responsibility-based JS files
data/
  news/runtime/                 Editable, published, and model-usage state
  news/diagnostics/             Fetch, candidate, and run reports
  backups/                      Local database and migration backups
docker/                         Images, compose services, and database scripts
docs/                           Setup, architecture, operations, and deployment
scripts/                        Diagnostics and maintenance utilities
```

## Runtime Data

| Path | Purpose |
| --- | --- |
| `data/news/runtime/news.json` | Current editable newsletter |
| `data/news/runtime/news_published.json` | Last published newsletter shown to users |
| `data/news/runtime/newsletter_settings.json` | Title, footer, issue, and date settings |
| `data/news/runtime/model_usage_summary.json` | Model usage and Gemini quota state |
| `data/news/diagnostics/` | Generated pipeline and selection diagnostics |
| `backend/pipeline/fetching/news_fetch_state.json` | Query and source rotation state |
| `backend/pipeline/tool_discovery/monthly_tools-site.json` | Tool and official-site registry |

## Documentation

| Guide | Use |
| --- | --- |
| [Setup](docs/SETUP.md) | First installation and local startup |
| [User Guide](docs/USER_GUIDE.md) | Current editor and viewer workflow |
| [Docker Setup](docs/DOCKER_SETUP.md) | Docker-specific setup and troubleshooting |
| [Architecture](docs/ARCHITECTURE.md) | Components, data flow, and storage design |
| [Maintenance](docs/MAINTENANCE.md) | Logs, backups, restarts, and operations |
| [Deployment](docs/DEPLOYMENT.md) | Production deployment and security |
| [Environment Guide](backend/config/ENVIRONMENT_GUIDE.md) | Environment variables and defaults |
| [Cost Model](docs/COST_MODEL.md) | Workbook assumptions, uncertainty, and verified totals |
| [Changelog](CHANGELOG.md) | Release history |

## Tests

Run the standard-library test suite:

```powershell
python -m unittest discover -s backend/tests -p "test*.py" -v
```
