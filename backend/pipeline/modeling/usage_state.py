"""Thread-safe helpers for the combined model usage state file."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable, TypeVar

from backend.config.settings import safe_write_json


_USAGE_STATE_LOCK = threading.RLock()
T = TypeVar("T")


def load_usage_state(path: Path) -> dict:
    """Load the shared usage document without exposing partial writes."""
    with _USAGE_STATE_LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def update_usage_state(path: Path, update: Callable[[dict], T]) -> T:
    """Update one section while preserving every other section in the file."""
    with _USAGE_STATE_LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        result = update(data)
        safe_write_json(path, data)
        return result
