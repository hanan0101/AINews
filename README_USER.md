# AINewsletter_v02 User Setup Guide

This guide is for users who want to run the project locally. You can run it in two ways:

- With Docker, which is the easiest option if Docker Desktop is installed.
- Without Docker, using Python and a virtual environment.

After the server starts, open the app in your browser:

```text
http://127.0.0.1:8000/News.html
```

## Requirements

Before you start, make sure you have:

- Docker Desktop, if you want to run the project with Docker.
- Or Python 3.11 or newer, if you want to run it without Docker.
- API keys in the environment file:
  - `OPENAI_API_KEY`
  - `EXA_API_KEY`
  - `TMDB_API_KEY`

The main environment file is:

```text
backend/.env
```

If it does not exist, copy it from the example file:

```powershell
copy backend\.env.example backend\.env
```

Then open it and add your real API keys:

```powershell
notepad backend\.env
```

## Run With Docker

This starts the app and the supporting SearXNG service.

1. Open PowerShell in the project folder:

```powershell
cd C:\AINewsletter_v02
```

2. Make sure the environment file exists:

```powershell
copy backend\.env.example backend\.env
notepad backend\.env
```

If `backend\.env` already exists, you do not need to copy it again. Just confirm that the API keys are set.

3. Start the services:

```powershell
docker compose up --build
```

4. Open the app:

```text
http://127.0.0.1:8000/News.html
```

5. To stop the services, press `Ctrl + C` in the PowerShell window.

Or stop them from another terminal:

```powershell
docker compose down
```

### Run Docker in the Background

To run without keeping the logs open:

```powershell
docker compose up --build -d
```

To view logs:

```powershell
docker compose logs -f ainewsletter
```

To stop everything:

```powershell
docker compose down
```

## Run Without Docker

Use this option if you want to run the app directly on your machine.

1. Open PowerShell in the project folder:

```powershell
cd C:\AINewsletter_v02
```

2. Create a virtual environment:

```powershell
python -m venv venv
```

3. Activate the virtual environment:

```powershell
venv\Scripts\activate
```

4. Install dependencies:

```powershell
pip install -r requirements.txt
```

5. Install the Playwright browser required for PDF export:

```powershell
python -m playwright install chromium
```

6. Prepare the environment file:

```powershell
copy backend\.env.example backend\.env
notepad backend\.env
```

7. Start the server:

```powershell
python -m backend.server.http_server
```

8. Open the app:

```text
http://127.0.0.1:8000/News.html
```

## Quick Windows Restart

The project includes a helper script to restart the backend:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1
```

To see logs directly in the terminal:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1 -Foreground
```

To stop the backend only:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1 -NoStart
```

## Using the App

1. Open:

```text
http://127.0.0.1:8000/News.html
```

2. Click **Generate** to generate the newsletter.
3. Wait for fetching, filtering, and AI selection to finish.
4. Edit cards manually from the UI if needed.
5. Export the newsletter as PDF from the UI.

Files updated after generation:

- `frontend/news.json`
- `frontend/ai_updates_run_report.json`
- `backend/news_fetch_state.json`
- `backend/qdrant_db/`

## Common Issues

### Port 8000 Is Already in Use

If the server cannot start because port `8000` is busy, find and stop the old process:

```powershell
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

Replace `<PID>` with the process ID shown by the first command.

### Docker Does Not Read the API Keys

Make sure this file exists:

```text
backend/.env
```

And make sure the variable names are written exactly like this:

```text
OPENAI_API_KEY=...
EXA_API_KEY=...
TMDB_API_KEY=...
```

Then restart Docker:

```powershell
docker compose down
docker compose up --build
```

### Generation Does Not Find Enough News

Check the following:

- The API keys are valid.
- Your internet connection is working.
- SearXNG is running when using Docker.
- `NEWS_JSON_ONLY_MODE=1` is not enabled in `backend/.env`.

### PDF Export Does Not Work Without Docker

Run:

```powershell
python -m playwright install chromium
```

Then restart the server.

## Important Notes

- Do not share `backend/.env`; it contains private API keys.
- When using Docker, the `backend` and `frontend` folders are mounted into the container, so generated files appear directly in the project folder.
- The local app URL is `http://127.0.0.1:8000/News.html`.
- The local SearXNG URL when using Docker is `http://127.0.0.1:8080`.

