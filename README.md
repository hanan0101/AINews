# AINewsletter_v0.1

Arabic user setup guide: [README_USER_AR.md](README_USER_AR.md)

AINewsletter_v0.1 is an Arabic newsletter generation platform focused on AI product updates for culture, creative work, work productivity, and everyday-life tools. It uses a monthly AI-tools layer, sector/use-case classification, live Exa and SearXNG searches, GPT editorial selection, semantic memory, logo enrichment, supporting courses and films, and an editable browser UI for review and PDF export.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Usage](#usage)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [Contact](#contact)

## Overview

**What is this?** AINewsletter_v0.1 solves the problem of producing a polished Arabic newsletter about practical AI product updates without manually browsing dozens of sites, tracking AI-product trends, checking which tools are popular or relevant, rewriting summaries, removing duplicates, finding company logos, and arranging cards in a printable design. The newsletter is intentionally focused on three editorial areas: cultural and creative fields, tools that support work productivity, and tools that help everyday life. It was built as more than a simple RSS reader because it combines a saved monthly tools layer, tool usage classification, live search, tool-aware query generation, semantic memory, GPT-based editorial selection, company logo enrichment, course and movie support cards, manual UI editing, and PDF export.

The system starts from AI products stored in `backend/monthly_tools.json`, `backend/tool_sector_map.json`, and the maintained `backend/tools_scored.json` cache. Each tool can be classified as `general_market` or `culture_creative`, with metadata such as `tool_type`, `sector`, `sector_hint`, and `cultural_applications`. General tools such as ChatGPT, Claude, Gemini, Copilot, and Perplexity are treated as multi-use products and searched for updates connected to productivity, learning, research, writing, daily tasks, and cultural use. Specialized tools such as Runway, Adobe Firefly, Canva, ElevenLabs, Luma, and similar creative products are searched with sector-aware terms such as video creation, design, audio, fashion, writing, archives, architecture, and learning.

**Key features:**
- Live AI-news discovery through Exa and local SearXNG.
- One active backend server at `backend/server.py`.
- Modular active pipeline in `backend/ai_update_pipeline/`.
- Monthly tools layer that feeds the search system with known AI products.
- Tool classification for `general_market` and `culture_creative` products.
- Sector/use-case hints for culture, creative work, productivity, education, research, and daily-life assistants.
- Tool-aware query generation that searches for recent AI updates by product name.
- Full-run query mix: tool-driven queries, specialized sector queries, and broad AI-update queries.
- Maintained tool-score cache support through `tools_scored.json`.
- GPT editorial selection with Arabic writing rules.
- Large-scan run: broad fetch, in-memory shortlist, then final 6 visible news cards plus backups.
- Semantic memory with local Qdrant storage and OpenAI embeddings.
- Supporting course cards from Exa restricted to approved course domains.
- Supporting movie card from TMDb restricted to films directly about AI.
- Transparent logo resolution using Simple Icons, local static assets, and verified fallback candidates.
- Browser UI for editing, replacing, resizing logos, previewing, exporting PDF, and sending email.

## Prerequisites

Before you begin, make sure you have the following installed:

| Tool | Version | Notes |
|---|---:|---|
| Python | 3.11+ | The current local virtual environment is `venv/` and uses Windows paths. |
| Microsoft Edge or Chromium | Current desktop version | Used by Playwright during server-side PDF export. |
| SearXNG | Optional local service | Defaults to `http://localhost:8080`; Exa can still fetch when SearXNG is unavailable. |
| OpenAI API key | Active billing/quota required | Used for GPT selection/writing and embeddings. |
| Exa API key | Active key required for best results | Used for news and course discovery. |
| TMDb API key | Active key required for movie card | Used for the AI-related film card. |

**Required API keys:**

- `OPENAI_API_KEY` - GPT selection, Arabic rewriting, and semantic-memory embeddings.
- `EXA_API_KEY` - live AI news and course search.
- `TMDB_API_KEY` - AI-related movie discovery and poster data.

## Setup

```bash
# 1. Enter the project directory
cd C:\AINewsletter_v0.1

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install the browser used by Playwright PDF export
python -m playwright install chromium

# 5. Create the active environment file
copy backend\.env.example backend\.env

# 6. Edit backend\.env and add real API keys
notepad backend\.env
```

The active server loads `backend/.env`. The optional `backend/.env.ai_updates` file is only for focused pipeline overrides and takes priority over `backend/.env` when present.

## Usage

### Basic Run

```bash
cd C:\AINewsletter_v0.1
venv\Scripts\python.exe backend\server.py
```

Then open:

```text
http://127.0.0.1:8000/UI.html
```

Expected output:

```text
[AI Updates] Background daemon disabled
Running: http://127.0.0.1:8000/UI.html
[server HH:MM:SS] Serving static files from C:\AINewsletter_v0.1\frontend
[server HH:MM:SS] API base /api; pipeline backend\ai_update_pipeline
```

### Restart Helper

```bash
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1
```

This stops any existing `backend/server.py` Python process, starts the backend in the background, checks `/api/news?auto=0`, and prints the UI URL.

### Foreground Restart

```bash
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1 -Foreground
```

Use this when you want to see logs directly in the terminal.

### Stop Backend Only

```bash
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1 -NoStart
```

Use this when port `8000` is busy or you want to cleanly stop the local backend.

### Generate From UI

1. Open `http://127.0.0.1:8000/UI.html`.
2. Click **Generate**.
3. The UI calls `POST /api/refill`.
4. The server runs `backend/ai_update_pipeline.run_pipeline(write_news_json=True)`.
5. The backend writes `frontend/news.json` and `frontend/ai_updates_run_report.json`.

### Expected Output Files

- `frontend/news.json` - the primary UI state and newsletter content.
- `frontend/ai_updates_run_report.json` - diagnostics, GPT selection report, and timing.
- `backend/news_fetch_state.json` - latest fetch performance and diversity counters.
- `frontend/generated/logos/` - locally cached transparent logo files.
- `backend/qdrant_db/` - local Qdrant semantic-memory storage.

## Architecture

High-level flow:

```text
[backend/.env]
    -> (API keys + runtime limits)
[backend/server.py]
    -> (HTTP API + static UI)
[frontend/UI.html]
    -> (Generate / edit / replace / export requests)
[backend/ai_update_pipeline/config.py]
    -> (paths + env-derived settings)
[monthly_tools.json + tool_sector_map.json + tools_scored.json]
    -> (tool names + tool group + sector hints + scores)
[query builder in fetchers.py]
    -> (Exa queries + SearXNG queries)
[parallel fetch: Exa + SearXNG]
    -> (raw news candidates)
[filters.py]
    -> (exact dedupe + same-story dedupe + Qdrant cosine semantic dedupe)
[pipeline.py large scan]
    -> (scan pool + GPT shortlist)
[model.py GPT selector]
    -> (12 selected updates: 6 visible + backup when available)
[enrichment.py]
    -> (frontend card schema + logos + courses + movie)
[frontend/news.json]
    -> (UI render + PDF export + manual editing)
```

The backend serves static files from `frontend/` and API routes under `/api`. The old `Generator.py` route is no longer the active generation path; the active generation path is the modular package `backend/ai_update_pipeline`.

## Configuration

All configuration is handled with environment variables. The main file is `backend/.env`; `backend/.env.ai_updates` is optional and overrides pipeline-specific values.

| Variable | Required | Default | Used by |
|---|---:|---|---|
| `OPENAI_API_KEY` | Yes | empty | GPT selection, rewriting, embeddings |
| `EXA_API_KEY` | Yes | empty | Exa news and course search |
| `TMDB_API_KEY` | Yes for movies | empty | TMDb movie fetch |
| `AI_UPDATES_SEARXNG_URL` | No | `http://localhost:8080` | SearXNG search endpoint |
| `SINGLE_REFILL_SECONDS` | No | `45` server default, example uses `90` | Single card replacement target |
| `NEWS_JSON_ONLY_MODE` | No | `0` | Blocks live generation when set to `1` |
| `NEWS_BACKUP_COUNT` | No | `6` | Server hidden replacement pool count |
| `AI_UPDATES_VISIBLE_COUNT` | No | `6` | Visible news cards |
| `AI_UPDATES_BACKUP_COUNT` | No | `6` | Pipeline backup news count |
| `AI_UPDATES_COURSES_VISIBLE_COUNT` | No | `2` | Visible course cards |
| `AI_UPDATES_MOVIES_VISIBLE_COUNT` | No | `1` | Visible movie card |
| `AI_UPDATES_LOOKBACK_DAYS` | No | `14` | News recency window |
| `AI_UPDATES_OUTPUT_LIMIT` | No | visible + backup | GPT final news target |
| `AI_UPDATES_SCAN_POOL_LIMIT` | No | `120` | Temporary large-scan pool size |
| `AI_UPDATES_GPT_SHORTLIST_LIMIT` | No | `60` | Candidates sent into GPT selection stage |
| `AI_UPDATES_GPT_COMPACT_LIMIT` | No | `48` | Compact candidate cap inside `model.py` |
| `AI_UPDATES_OPENAI_MODEL` | No | `gpt-5.2` | GPT model for news/courses/movies |
| `AI_UPDATES_EXA_QUERY_LIMIT` | No | `40` | Full Exa query count |
| `AI_UPDATES_EXA_RESULTS_PER_QUERY` | No | `5` | Exa results per query |
| `AI_UPDATES_SEARXNG_QUERY_LIMIT` | No | `40` | Full SearXNG query count |
| `AI_UPDATES_SEARXNG_RESULTS_PER_QUERY` | No | `8` | SearXNG results per query |
| `AI_UPDATES_COURSE_QUERY` | No | `new AI course launched 2026 beginners creators` | Exa course search |
| `AI_UPDATES_COURSE_START_PUBLISHED_DATE` | No | `2026-01-01` | Course Exa date lower bound |
| `AI_UPDATES_COURSE_NUM_RESULTS` | No | `10` | Exa course result request size |
| `AI_UPDATES_MEMORY_ENABLED` | No | `1` | Enables Qdrant memory |
| `AI_UPDATES_SEMANTIC_MEMORY_ENABLED` | No | `1` | Enables embedding cosine checks |
| `AI_UPDATES_EMBED_MODEL` | No | `text-embedding-3-small` | OpenAI embedding model |
| `AI_UPDATES_QDRANT_COLLECTION` | No | `content_memory` | Qdrant collection name |
| `PDF_EXPORT_PROFILE` | No | `whatsapp` | Server-side PDF export profile |
| `PDF_EXPORT_WHATSAPP_JPEG_QUALITY` | No | `82` | PDF image compression quality |
| `PDF_EXPORT_WHATSAPP_MAX_MB` | No | `5` | WhatsApp-oriented PDF size target |
| `SMTP_HOST` | No | empty | Email sending |
| `SMTP_PORT` | No | `587` | Email sending |
| `SMTP_USER` | No | empty | Email sending |
| `SMTP_PASSWORD` | No | empty | Email sending |
| `SMTP_FROM_EMAIL` | No | `SMTP_USER` | Email sending |

## Project Structure

```text
/
|-- README.md                         # Project usage and architecture guide
|-- requirements.txt                  # Active Python dependencies
|-- DOCUMENTATION.md                  # Extended engineering documentation
|-- backend/
|   |-- .env.example                  # Safe main env template
|   |-- .env.ai_updates.example       # Optional pipeline override template
|   |-- server.py                     # Main backend entrypoint and HTTP API
|   |-- monthly_tools.json            # Monthly/current tool cache
|   |-- tool_sector_map.json          # Tool classification cache
|   |-- tools_scored.json             # Maintained tool-score cache
|   |-- sector_terms_history.json     # Learned sector terms
|   |-- news_fetch_state.json         # Last run timing/diversity state
|   |-- newsletter_settings.json      # Saved UI/newsletter settings
|   |-- qdrant_db/                    # Local Qdrant semantic memory
|   `-- ai_update_pipeline/
|       |-- __init__.py               # Public package entrypoint
|       |-- config.py                 # Paths, env values, shared utilities
|       |-- fetchers.py               # Exa, SearXNG, course, and movie fetchers
|       |-- filters.py                # Quality filters, dedupe, Qdrant memory
|       |-- model.py                  # GPT prompts and structured selection
|       `-- enrichment.py             # Card conversion, logos, JSON output
|-- frontend/
|   |-- UI.html                       # Browser UI
|   |-- news.json                     # Active rendered newsletter data
|   |-- ai_updates_run_report.json    # Latest run diagnostics
|   |-- generated/logos/              # Cached logo files
|   |-- image/                        # Static ministry/brand/UI assets
|   `-- fonts/                        # Effra font files used by the design
|-- scripts/
|   `-- restart_backend.ps1           # Stop/start helper for local backend
`-- docs/
    |-- system_architecture.png       # Architecture image
    |-- news-workflow.svg             # Workflow diagram
    `-- Business_Documentation.md     # Additional business documentation
```

## Contributing

1. Create a new branch:

   ```bash
   git checkout -b feature/your-feature
   ```

2. Make focused changes in the active path:

   ```text
   backend/server.py
   backend/ai_update_pipeline/
   frontend/UI.html
   frontend/news.json
   ```

3. Run syntax checks:

   ```bash
   python -m py_compile backend\server.py backend\ai_update_pipeline\config.py backend\ai_update_pipeline\fetchers.py backend\ai_update_pipeline\filters.py backend\ai_update_pipeline\model.py backend\ai_update_pipeline\enrichment.py backend\ai_update_pipeline\pipeline.py
   ```

4. Start the backend and verify the UI:

   ```bash
   python backend\server.py
   ```

5. Open a pull request or keep a local backup branch after confirming Generate, single refill, PDF export, and manual card editing still work.

Before submitting, make sure no real API keys are committed and no generated cache folders are accidentally included.

## Contact

| Role | Name | Contact |
|---|---|---|
| Project Owner | Local AINewsletter_v0.1 owner | Stored outside the repository |
| Technical Maintainer | Local backend maintainer | Stored outside the repository |

Last updated: 2026-06-01 - Codex
