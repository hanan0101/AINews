"""Provider switch for JSON-only editorial model calls."""

from __future__ import annotations

from typing import Any

from backend.config.settings import AI_UPDATES_MODEL_PROVIDER, OPENAI_MODEL
from backend.pipeline.modeling import gemini_client, openai_client


MODEL_PROVIDER = AI_UPDATES_MODEL_PROVIDER if AI_UPDATES_MODEL_PROVIDER in {"gemini", "openai"} else "gemini"
MODEL_FLASH_MODEL = OPENAI_MODEL if MODEL_PROVIDER == "openai" else gemini_client.GEMINI_FLASH_MODEL

# Role -> model resolution for the 3-model split (selection / rewrite /
# embedding). OpenAI keeps using one model for every role (it is not the
# focus of this split); Gemini gets a distinct model per role so the cheaper,
# higher-quota model handles the higher-frequency rewrite work while the
# stronger model is reserved for the harder editorial-judgment (selection) work.
_ROLE_MODELS_GEMINI = {
    "selection": gemini_client.GEMINI_SELECTION_MODEL,
    "rewrite": gemini_client.GEMINI_REWRITE_MODEL,
}


def model_for_role(role: str) -> str:
    if MODEL_PROVIDER == "openai":
        return OPENAI_MODEL
    return _ROLE_MODELS_GEMINI.get(role, MODEL_FLASH_MODEL)


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


# Role-based entry point (role in {"selection", "rewrite"}) - resolves the
# model via model_for_role() instead of the caller having to know which env
# var/constant backs each role.
def generate_json_for_role(role: str, system_prompt: str, user_payload: Any) -> dict[str, Any]:
    selected_model = model_for_role(role)
    if MODEL_PROVIDER == "gemini" and role == "rewrite":
        return gemini_client.generate_json(
            system_prompt,
            user_payload,
            model=selected_model,
            max_output_tokens=gemini_client.GEMINI_REWRITE_MAX_OUTPUT_TOKENS,
        )
    return generate_json(system_prompt, user_payload, model=selected_model)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if MODEL_PROVIDER == "openai":
        return openai_client.embed_texts(texts)
    return gemini_client.embed_texts(texts)


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
    message = str(exc)
    lowered = message.lower()
    if "quota" in lowered or "status=429" in lowered or "rate-limit" in lowered:
        category = "quota_or_billing"
    elif (
        "api key not valid" in lowered
        or "api_key_invalid" in lowered
        or "permission" in lowered
        or "access_token_type_unsupported" in lowered
        or "unauthenticated" in lowered
        or "invalid authentication credentials" in lowered
    ):
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
