# Provides the OpenAI client helpers used by the pipeline.

import json
import re
from typing import Any

from openai import OpenAI

from backend.config.settings import AI_UPDATES_EMBED_MODEL, OPENAI_API_KEY, OPENAI_MODEL

_openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


# Returns whether OpenAI calls can be attempted.
def openai_available() -> bool:
    return _openai_client is not None


# Extracts a JSON object from model text.
def _extract_json(text: str = "") -> dict[str, Any]:
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


# Generates JSON through OpenAI when Gemini is unavailable or out of quota.
def generate_json(system_prompt: str, user_payload: Any, *, model: str | None = None) -> dict[str, Any]:
    if _openai_client is None:
        raise RuntimeError("missing_openai_api_key")
    selected_model = (model or OPENAI_MODEL or "gpt-5.2").strip()
    user_text = user_payload if isinstance(user_payload, str) else json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))
    response = _openai_client.responses.create(
        model=selected_model,
        input=[
            {
                "role": "system",
                "content": f"{system_prompt}\n\nReturn valid JSON only. Do not wrap the JSON in markdown.",
            },
            {"role": "user", "content": f"INPUT:\n{user_text}"},
        ],
        text={"format": {"type": "json_object"}},
    )
    parsed = _extract_json(response.output_text or "")
    usage = getattr(response, "usage", None)
    if isinstance(parsed, dict) and usage:
        usage_data = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage or {})
        parsed["__model_usage"] = {
            "provider": "openai",
            "model": selected_model,
            "input_tokens": usage_data.get("input_tokens"),
            "output_tokens": usage_data.get("output_tokens"),
            "total_tokens": usage_data.get("total_tokens"),
            "raw": usage_data,
        }
    return parsed


# Creates embeddings for semantic-memory duplicate checks.
def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts or _openai_client is None:
        return []
    try:
        response = _openai_client.embeddings.create(model=AI_UPDATES_EMBED_MODEL, input=texts)
        return [item.embedding for item in response.data]
    except Exception as exc:
        print(f"[AI Updates] semantic embeddings skipped: {exc}", flush=True)
        return []
