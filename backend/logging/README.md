# Logging

This folder contains pipeline logging he.

## What Gets Logged

- Pipeline run ids and stage nam
- Stage durations for source fetching, filtering, model selection, saving, and supporting conte
- Candidate summaries and model token estimates
- Errors from external services such as Gemini, Exa, SearXNG, Qdrant, or PostgreSQL-adjacent flow

## Where Logs Go

The active JSONL event stream is written under `backend/logs/ai_updates_run.jsonl` unless environment settings change it.


## Why This Exists

The newsletter pipeline depends on external APIs, so every run needs enough trace data to explain why candidates were selected, rejected, delayed, or missing.


