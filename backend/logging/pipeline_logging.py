# This file is part of the AI newsletter system.
"""Structured run logging for the AI updates pipeline.

This module helps developers and operators diagnose generation failures,
slow stages, and the items that moved through the news pipeline. Editorial
selection does not depend on these logs, so logging can be disabled with
AI_UPDATES_RUN_LOG_ENABLED=0.

Deletion note: this module is functionally optional, but do not delete this
file while pipeline.py, fetchers.py, model.py, filters.py, and enrichment.py
still import its functions. Remove those imports and calls, or replace them
with a no-op logging interface first; otherwise the package will fail with
ImportError.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backend.config.settings import BACKEND_DIR, env_bool, utc_now

RUN_LOG_ENABLED = env_bool("AI_UPDATES_RUN_LOG_ENABLED", "1")
RUN_LOG_TO_STDOUT = env_bool("AI_UPDATES_RUN_LOG_STDOUT", "1")
RUN_LOG_FILE = Path(os.getenv("AI_UPDATES_RUN_LOG_FILE", str(BACKEND_DIR / "logs" / "ai_updates_run.jsonl")))

_state = threading.local()
_write_lock = threading.Lock()


# Create a unique identifier that links all events from one pipeline run.
def new_run_id(prefix: str = "run") -> str:
    """Return a timestamped unique identifier for one pipeline run."""
    return f"{prefix}-{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


# Store the run identifier and mode per thread so concurrent runs do not mix.
def set_run_context(run_id: str, mode: str = "") -> None:
    """Attach a run identifier and mode to the current thread."""
    _state.run_id = run_id
    _state.mode = mode


# Return the current thread's run identifier, or an empty string when unset.
def get_run_id() -> str:
    """Return the run identifier associated with the current thread."""
    return getattr(_state, "run_id", "") or ""


# Return the current run mode, such as full or single, for log records.
def get_mode() -> str:
    """Return the pipeline mode associated with the current thread."""
    return getattr(_state, "mode", "") or ""


# Convert non-JSON-serializable values to text instead of breaking logging.
def _json_default(value: Any) -> str:
    """Provide a safe string fallback for values JSON cannot serialize."""
    try:
        return str(value)
    except Exception:
        return "<unserializable>"


# Trim logged data so long strings and lists do not inflate the log file.
def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Trim large payload values and remove None fields before logging."""
    clean = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str):
            clean[key] = value[:1200]
        elif isinstance(value, list):
            clean[key] = value[:80]
        elif isinstance(value, dict):
            clean[key] = value
        else:
            clean[key] = value
    return clean


# Write a structured event to stdout and ai_updates_run.jsonl safely across threads.
def log_event(event: str, **payload: Any) -> None:
    """Write one structured pipeline event when run logging is enabled."""
    if not RUN_LOG_ENABLED:
        return
    record = {
        "ts": utc_now().isoformat(),
        "event": event,
        "run_id": payload.pop("run_id", None) or get_run_id(),
        "mode": payload.pop("mode", None) or get_mode(),
        **_clean_payload(payload),
    }
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    with _write_lock:
        if RUN_LOG_TO_STDOUT:
            stdout_line = f"[RUNLOG] {line}"
            encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
            safe_line = stdout_line.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")
            print(safe_line, flush=True)
        try:
            RUN_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(RUN_LOG_FILE, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass


# Time a stage and log started, finished, or failed when an exception occurs.
@contextmanager
# Performs the timed stage helper step.
def timed_stage(event: str, **payload: Any):
    """Measure a code block and log its start, completion, or failure."""
    started = time.time()
    log_event(f"{event}.started", **payload)
    try:
        yield
    except Exception as exc:
        log_event(f"{event}.failed", seconds=round(time.time() - started, 2), error=str(exc), **payload)
        raise
    else:
        log_event(f"{event}.finished", seconds=round(time.time() - started, 2), **payload)


# Return file existence, size, and modification time for diagnostics.
def file_status(path: Path) -> dict[str, Any]:
    """Return diagnostic existence, size, and modification data for a file."""
    if not path.exists():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "bytes": stat.st_size,
        "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
    }


# Reduce news items to key fields so run logs stay compact and readable.
def summarize_items(items: list[dict], limit: int = 12) -> list[dict]:
    """Return a compact diagnostic summary of candidate or selected items."""
    summary = []
    for item in (items or [])[:limit]:
        if not isinstance(item, dict):
            continue
        summary.append({
            "title": item.get("title") or item.get("tool") or item.get("company") or "",
            "company": item.get("company") or item.get("company_name") or item.get("owner_key") or "",
            "source": item.get("fetch_source") or item.get("source") or item.get("source_domain") or "",
            "sector": item.get("sector") or item.get("sector_hint") or item.get("tool_sector_hint") or "",
            "url": item.get("url") or item.get("official_url") or "",
        })
    return summary

