# This file is part of the AI newsletter system.
"""Shared JSON-from-model-text extraction, used by every provider adapter."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(text: str = "") -> dict[str, Any]:
    """Parse a JSON object out of raw model output, stripping markdown fences if present."""
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise
        return json.loads(match.group(0))
