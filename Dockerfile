# Builds the application container for the AI newsletter backend and frontend.
FROM mcr.microsoft.com/playwright/python:v1.59.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts
COPY README.md .

EXPOSE 8000

# Container command: starts the HTTP server, static frontend, auth checks, and
# the pipeline orchestrator used by Generate/refill routes.
CMD ["python", "-m", "backend.server.http_server"]
