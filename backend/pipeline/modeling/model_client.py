"""Provider switch for JSON-only editorial model calls."""

from __future__ import annotations

from typing import Any

from backend.config.settings import AI_UPDATES_MODEL_PROVIDER, OPENAI_MODEL
from backend.pipeline.modeling import gemini_client, openai_client


MODEL_PROVIDER = AI_UPDATES_MODEL_PROVIDER if AI_UPDATES_MODEL_PROVIDER in {"gemini", "openai"} else "gemini"
MODEL_FLASH_MODEL = OPENAI_MODEL if MODEL_PROVIDER == "openai" else gemini_client.GEMINI_FLASH_MODEL


def model_available() -> bool:
    if MODEL_PROVIDER == "openai":
        return openai_client.openai_available()
    return gemini_client.gemini_available()


def model_quota_remaining() -> int:
    if MODEL_PROVIDER == "openai":
        return 999999
    return gemini_client.gemini_quota_remaining()


def generate_json(system_prompt: str, user_payload: Any, *, model: str | None = None) -> dict[str, Any]:
    selected_model = model or MODEL_FLASH_MODEL
    if MODEL_PROVIDER == "openai":
        return openai_client.generate_json(system_prompt, user_payload, model=selected_model)
    return gemini_client.generate_json(system_prompt, user_payload, model=selected_model)


def model_error_details(exc: Exception) -> dict[str, Any]:
    if MODEL_PROVIDER == "gemini":
        return gemini_client_error_details(exc)
    message = str(exc)
    lowered = message.lower()
    if "rate limit" in lowered or "429" in lowered or "quota" in lowered or "insufficient_quota" in lowered:
        category = "quota_or_billing"
    elif "api key" in lowered or "unauthorized" in lowered or "permission" in lowered:
        category = "invalid_or_unauthorized_key"
    elif "not found" in lowered or "404" in lowered:
        category = "model_not_found"
    elif "missing_openai_api_key" in lowered:
        category = "missing_openai_api_key"
    else:
        category = "openai_request_failed"
    return {
        "provider": "openai",
        "category": category,
        "quota_error_category": "provider_quota_exhausted" if category == "quota_or_billing" else "",
        "error": message,
    }


def gemini_client_error_details(exc: Exception) -> dict[str, Any]:
    if hasattr(exc, "details") and isinstance(getattr(exc, "details"), dict):
        details = dict(getattr(exc, "details"))
        details["error"] = str(exc)
        return details
    message = str(exc)
    lowered = message.lower()
    if "quota" in lowered or "status=429" in lowered or "rate-limit" in lowered:
        category = "quota_or_billing"
    elif "api key not valid" in lowered or "api_key_invalid" in lowered or "permission" in lowered:
        category = "invalid_or_unauthorized_key"
    elif "status=404" in lowered or "not found" in lowered:
        category = "model_not_found"
    elif "missing_gemini_api_key" in lowered:
        category = "missing_gemini_api_key"
    else:
        category = "gemini_request_failed"
    return {
        "provider": "gemini",
        "category": category,
        "quota_error_category": "provider_quota_exhausted" if category == "quota_or_billing" else "",
        "error": message,
    }
