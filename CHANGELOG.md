# Changelog

## 2026-07-30 — Editorial validation, pipeline split, and audit

- Strengthened news selection/rewrite prompts with event freshness,
  availability, evidence, functional diversity, and Arabic length rules.
- Added deterministic post-model checks for 50–64-word summaries, stale event
  dates, unsupported claims, and diversity caps.
- Unified course-level classification in
  `backend/pipeline/filtering/content/courses/levels.py`; ambiguous courses
  are no longer assigned `Intermediate` by default.
- Removed the experimental future-edition scheduler; generation now uses the
  newsletter's current issue/month metadata when naming a saved version.
- Organized every pipeline stage into explicit `news`, `courses`, and `films`
  content packages, with `shared` reserved for cross-content logic.
- Split the former 3924-line news discovery implementation into source,
  query, normalization, tracking, merge, and runtime modules.
- Reduced `frontend/News.html` to a markup shell and separated CSS and
  JavaScript by responsibility. Renamed `shared.js` to
  `shared-functions.js`.
- Removed dead `model_config.py`, `tool_registry.py`, the unused course-level
  wrapper, and the nonfunctional email-send UI.
- Added editorial acceptance tests and completed the file-by-file review in
  `PROJECT_CODE_AUDIT.md`.
- Reconciled model/cost documentation with the reviewed Excel workbook and the
  active model-role configuration.
- Prevented duplicate saved-version names across new saves, PDF imports, and
  renames. PostgreSQL now enforces the rule with a case-insensitive unique
  index, while the UI asks the administrator to choose another name.

## Earlier stage-based reorganization

- Reorganized the active AI update implementation into stage-based modules under `backend/pipeline`.
- Moved shared configuration to `backend/config/settings.py`.
- Moved pipeline logging to `backend/logging/pipeline_logging.py`.
- Kept Gemini/OpenAI switching support in
  `backend/pipeline/modeling/model_client.py`, with provider clients beside it.
- Removed obsolete `backend/pipeline/ai_update_pipeline` compatibility wrappers after active imports moved to the stage-based pipeline.
- Removed generated `__pycache__` folders from source directories.
- Kept the environment template at `backend/.env.example`.

No OpenAI or Gemini-related code was deleted.
