# Changelog

## Delivery Preparation Cleanup

- Reorganized the active AI update implementation into stage-based modules under `backend/pipeline`.
- Moved shared configuration to `backend/config/settings.py`.
- Moved pipeline logging to `backend/logging/pipeline_logging.py`.
- Moved Gemini/OpenAI switching support to `backend/interfaces/gemini_client.py`.
- Removed obsolete `backend/pipeline/ai_update_pipeline` compatibility wrappers after active imports moved to the stage-based pipeline.
- Removed generated `__pycache__` folders from source directories.
- Moved `.env.example` into `backend/config/.env.example`.

No OpenAI or Gemini-related code was deleted.
