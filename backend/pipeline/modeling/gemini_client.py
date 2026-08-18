# This file is part of the AI newsletter system.
"""Small Gemini google-genai adapter for JSON-only model calls."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

try:
    import google.api_core.exceptions as gexc
except Exception:
    gexc = None

from backend.services.gemini_limiter import wait_for_gemini_slot
from backend.config.settings import MODEL_USAGE_SUMMARY_FILE
from backend.pipeline.modeling.json_extract import extract_json_object
from backend.pipeline.modeling.usage_state import load_usage_state, update_usage_state


BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env", override=False)
logger = logging.getLogger(__name__)

# Pin generation models to the versions used by the cost model so quality,
# usage measurements, and provider pricing remain comparable across runs.
# gemini-3.1-pro-preview requires paid quota on the configured Google project;
# provider-side 429 errors remain visible when that quota is unavailable.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_SELECTION_MODEL = os.getenv("GEMINI_SELECTION_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash"
GEMINI_REWRITE_MODEL = os.getenv("GEMINI_REWRITE_MODEL", "gemini-3.1-pro-preview").strip() or "gemini-3.1-pro-preview"
GEMINI_REWRITE_MAX_OUTPUT_TOKENS = max(
    1024,
    min(65536, int(os.getenv("GEMINI_REWRITE_MAX_OUTPUT_TOKENS", "32768") or "32768")),
)
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001").strip() or "gemini-embedding-001"
GEMINI_FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash"
_GEMINI_RATE_LIMIT_LOCK = threading.RLock()
_LAST_GEMINI_CALL_STARTED_AT = 0.0
# Temporary testing limiter: 4 seconds keeps Gemini calls under 15 requests/minute.
_GEMINI_TEST_CALL_INTERVAL_SECONDS = float(
    os.getenv("GEMINI_MIN_SECONDS_BETWEEN_CALLS")
    or os.getenv("GEMINI_TEST_CALL_INTERVAL_SECONDS", "6.0")
    or "6.0"
)
_GEMINI_RATE_LIMIT_FILE = Path(
    os.getenv("GEMINI_RATE_LIMIT_FILE", Path(__file__).resolve().parent / ".gemini_rate_limit")
).resolve()
_GEMINI_RATE_LIMIT_STALE_SECONDS = 60.0
_MODEL_USAGE_STATE_FILE = MODEL_USAGE_SUMMARY_FILE.resolve()
_LEGACY_GEMINI_QUOTA_STATE_FILE = Path(os.getenv("GEMINI_QUOTA_STATE_FILE", ROOT_DIR / "data" / "news" / "gemini_quota_state.json")).resolve()
_GEMINI_QUOTA_STATE_KEY = "gemini_quota_state"
_GEMINI_DAILY_REQUEST_BUDGET = int(os.getenv("GEMINI_DAILY_REQUEST_BUDGET", "120") or "120")
_GEMINI_FULL_RUN_REQUEST_BUDGET = int(os.getenv("GEMINI_FULL_RUN_REQUEST_BUDGET", "0") or "0")
_GEMINI_STOP_ON_QUOTA = os.getenv("GEMINI_STOP_ON_QUOTA", "1").strip().lower() in {"1", "true", "yes", "on"}
_PACIFIC = ZoneInfo("America/Los_Angeles")
# Without an explicit timeout, google-genai passes timeout=None straight
# through to httpx, which waits forever on a stalled connection. That let a
# single hung rewrite call hold GENERATOR_LOCK indefinitely (observed
# 2026-07-30: a run's last log line was "prompt.news_rewrite.started" with no
# matching "finished"/"model_failed" ever following), blocking every
# subsequent Generate click with no visible error.
GEMINI_REQUEST_TIMEOUT_SECONDS = max(10, int(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "120") or "120"))
_GEMINI_HTTP_OPTIONS = types.HttpOptions(timeout=GEMINI_REQUEST_TIMEOUT_SECONDS * 1000)


def _new_gemini_client() -> genai.Client:
    return genai.Client(api_key=GEMINI_API_KEY, http_options=_GEMINI_HTTP_OPTIONS)


class GeminiQuotaError(RuntimeError):
    def __init__(self, message: str, details: dict[str, Any]):
        super().__init__(message)
        self.details = details


class _RetryableGeminiClientError(RuntimeError):
    pass


_RETRYABLE_GEMINI_EXCEPTIONS = (
    genai_errors.ServerError,
    _RetryableGeminiClientError,
    httpx.TimeoutException,
    httpx.ConnectError,
    *((
        gexc.ServiceUnavailable,
        gexc.ResourceExhausted,
        gexc.DeadlineExceeded,
        gexc.InternalServerError,
    ) if gexc else ()),
)


# Performs the gemini available helper step.
def gemini_available() -> bool:
    return bool(GEMINI_API_KEY)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pacific_day() -> str:
    return datetime.now(_PACIFIC).date().isoformat()


def _load_quota_state() -> dict[str, Any]:
    document = load_usage_state(_MODEL_USAGE_STATE_FILE)
    embedded = document.get(_GEMINI_QUOTA_STATE_KEY)
    try:
        state = embedded if isinstance(embedded, dict) else json.loads(_LEGACY_GEMINI_QUOTA_STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except Exception:
        state = {}
    day = _pacific_day()
    if state.get("pacific_day") != day:
        state = {
            "pacific_day": day,
            "requests_today": 0,
            "daily_request_budget": _GEMINI_DAILY_REQUEST_BUDGET,
            "full_run_request_budget": _GEMINI_FULL_RUN_REQUEST_BUDGET,
            "runs": {},
            "last_usage": {},
            "last_error": {},
        }
    state.setdefault("runs", {})
    state["daily_request_budget"] = _GEMINI_DAILY_REQUEST_BUDGET
    state["full_run_request_budget"] = _GEMINI_FULL_RUN_REQUEST_BUDGET
    return state


def _save_quota_state(state: dict[str, Any]) -> None:
    update_usage_state(
        _MODEL_USAGE_STATE_FILE,
        lambda document: document.__setitem__(_GEMINI_QUOTA_STATE_KEY, state),
    )


def _current_run_id() -> str:
    try:
        from backend.logging.pipeline_logging import get_run_id
        return get_run_id() or "manual"
    except Exception:
        return "manual"


def gemini_quota_remaining() -> int:
    if not _GEMINI_STOP_ON_QUOTA:
        return 999999
    with _GEMINI_RATE_LIMIT_LOCK:
        state = _load_quota_state()
        return max(0, _GEMINI_DAILY_REQUEST_BUDGET - int(state.get("requests_today") or 0))


def _quota_details(category: str, model: str, state: dict[str, Any], run: dict[str, Any], run_id: str) -> dict[str, Any]:
    requests_today = int(state.get("requests_today") or 0)
    return {
        "provider": "gemini",
        "category": "quota_or_billing",
        "quota_error_category": category,
        "model": model,
        "request_number_today": requests_today,
        "remaining_daily_requests": max(0, _GEMINI_DAILY_REQUEST_BUDGET - requests_today),
        "daily_request_budget": _GEMINI_DAILY_REQUEST_BUDGET,
        "run_request_budget": _GEMINI_FULL_RUN_REQUEST_BUDGET,
        "run_requests": int(run.get("requests") or 0),
        "run_id": run_id,
    }


def _reserve_gemini_request(model: str) -> dict[str, Any]:
    state = _load_quota_state()
    run_id = _current_run_id()
    run = state.setdefault("runs", {}).setdefault(run_id, {"requests": 0, "started_at": _utc_timestamp()})
    requests_today = int(state.get("requests_today") or 0)
    run_requests = int(run.get("requests") or 0)
    if _GEMINI_STOP_ON_QUOTA and requests_today >= _GEMINI_DAILY_REQUEST_BUDGET:
        details = _quota_details("local_daily_budget_exhausted", model, state, run, run_id)
        state["last_error"] = {"updated_at": _utc_timestamp(), **details, "error": "gemini_daily_quota_budget_exhausted"}
        _save_quota_state(state)
        raise GeminiQuotaError("gemini_daily_quota_budget_exhausted", details)
    if _GEMINI_STOP_ON_QUOTA and _GEMINI_FULL_RUN_REQUEST_BUDGET > 0 and run_requests >= _GEMINI_FULL_RUN_REQUEST_BUDGET:
        details = _quota_details("local_run_budget_exhausted", model, state, run, run_id)
        state["last_error"] = {"updated_at": _utc_timestamp(), **details, "error": "gemini_full_run_request_budget_exhausted"}
        _save_quota_state(state)
        raise GeminiQuotaError("gemini_full_run_request_budget_exhausted", details)
    state["requests_today"] = requests_today + 1
    state["last_request_at"] = _utc_timestamp()
    run["requests"] = run_requests + 1
    run["last_request_at"] = state["last_request_at"]
    quota = {
        "request_number_today": state["requests_today"],
        "remaining_daily_requests": max(0, _GEMINI_DAILY_REQUEST_BUDGET - state["requests_today"]),
        "daily_request_budget": _GEMINI_DAILY_REQUEST_BUDGET,
        "run_request_number": run["requests"],
        "run_request_budget": _GEMINI_FULL_RUN_REQUEST_BUDGET,
        "run_id": run_id,
    }
    state["last_quota"] = quota
    _save_quota_state(state)
    print(f"[AI Updates] Gemini quota remaining: {quota['remaining_daily_requests']}/{_GEMINI_DAILY_REQUEST_BUDGET}", flush=True)
    return quota


def _record_gemini_usage(quota: dict[str, Any], usage: dict[str, Any], model: str) -> None:
    state = _load_quota_state()
    state["last_usage"] = {
        "updated_at": _utc_timestamp(),
        "model": model,
        "quota": quota,
        "usage": usage,
    }
    _save_quota_state(state)


def _record_gemini_error(quota: dict[str, Any], exc: Exception, model: str) -> dict[str, Any]:
    message = str(exc)
    lowered = message.lower()
    quota_error_category = "provider_quota_exhausted" if "resource_exhausted" in lowered or "429" in lowered or "quota" in lowered else "provider_request_failed"
    details = {
        "provider": "gemini",
        "category": "quota_or_billing" if quota_error_category == "provider_quota_exhausted" else "gemini_request_failed",
        "quota_error_category": quota_error_category,
        "model": model,
        "error": message,
        **(quota or {}),
    }
    state = _load_quota_state()
    state["last_error"] = {
        "updated_at": _utc_timestamp(),
        **{key: value for key, value in details.items() if key != "error"},
        "error": message[:2000],
    }
    _save_quota_state(state)
    return details


# Waits before a Gemini request so test runs stay below the free-tier request limit.
def _wait_for_gemini_test_rate_limit() -> None:
    global _LAST_GEMINI_CALL_STARTED_AT
    wait_for_gemini_slot()
    with _GEMINI_RATE_LIMIT_LOCK:
        while True:
            now = time.time()
            try:
                last_started_at = float(_GEMINI_RATE_LIMIT_FILE.read_text(encoding="utf-8").strip() or "0")
            except Exception:
                last_started_at = 0.0
            if now - last_started_at > _GEMINI_RATE_LIMIT_STALE_SECONDS:
                last_started_at = 0.0
            local_elapsed = time.monotonic() - _LAST_GEMINI_CALL_STARTED_AT
            shared_elapsed = now - last_started_at
            wait_seconds = max(
                0.0,
                _GEMINI_TEST_CALL_INTERVAL_SECONDS - local_elapsed,
                _GEMINI_TEST_CALL_INTERVAL_SECONDS - shared_elapsed,
            )
            if wait_seconds <= 0:
                break
            time.sleep(wait_seconds)
        _LAST_GEMINI_CALL_STARTED_AT = time.monotonic()
        try:
            _GEMINI_RATE_LIMIT_FILE.write_text(str(time.time()), encoding="utf-8")
        except Exception:
            pass


@retry(
    retry=retry_if_exception_type(_RETRYABLE_GEMINI_EXCEPTIONS),
    wait=wait_exponential(multiplier=2, min=15, max=300),
    stop=stop_after_attempt(6),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _generate_content_with_retry(
    client: genai.Client,
    *,
    model: str,
    contents: str,
    config: types.GenerateContentConfig,
) -> Any:
    try:
        return client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
    except genai_errors.ClientError as exc:
        message = str(exc).lower()
        if any(signal in message for signal in ("429", "resource_exhausted", "deadline", "timeout", "500", "503")):
            raise _RetryableGeminiClientError(str(exc)) from exc
        raise


# Performs the generate json helper step.
def generate_json(
    system_prompt: str,
    user_payload: Any,
    *,
    model: str | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("missing_gemini_api_key")
    selected_model = (model or GEMINI_FLASH_MODEL or "gemini-3.5-flash").strip()
    user_text = user_payload if isinstance(user_payload, str) else json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))
    client = _new_gemini_client()
    config_kwargs: dict[str, Any] = {
        "temperature": 0.3,
        "response_mime_type": "application/json",
    }
    if max_output_tokens is not None:
        config_kwargs["max_output_tokens"] = max_output_tokens
    with _GEMINI_RATE_LIMIT_LOCK:
        quota = _reserve_gemini_request(selected_model)
        _wait_for_gemini_test_rate_limit()
    try:
        response = _generate_content_with_retry(
            client,
            model=selected_model,
            contents=(
                f"{system_prompt}\n\n"
                "Return valid JSON only. Do not wrap the JSON in markdown.\n\n"
                f"INPUT:\n{user_text}"
            ),
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except Exception as exc:
        details = _record_gemini_error(quota, exc, selected_model)
        if details.get("quota_error_category") == "provider_quota_exhausted":
            raise GeminiQuotaError("gemini_provider_quota_exhausted", details) from exc
        raise
    text = response.text or ""
    usage_metadata = getattr(response, "usage_metadata", None)
    usage = usage_metadata.model_dump() if hasattr(usage_metadata, "model_dump") else dict(usage_metadata or {})
    candidates = getattr(response, "candidates", None) or []
    finish_reasons = [str(getattr(candidate, "finish_reason", "") or "") for candidate in candidates]
    # Debug logging must never be able to take down the actual model call.
    # This response text is Arabic, so on a console/pipe whose stdout
    # encoding isn't UTF-8 (e.g. the default Windows "charmap" codec), a
    # plain print() raises UnicodeEncodeError here - and since that happened
    # outside the try/except around _generate_content_with_retry above, it
    # propagated up and silently failed the whole selection/rewrite call
    # (surfaced upstream as a generic "gemini_request_failed").
    try:
        print(
            f"[AI Updates] Gemini raw response before JSON parse "
            f"model={selected_model} chars={len(text)} "
            f"finish_reasons={finish_reasons} usage={usage}\n"
            "----- GEMINI RAW RESPONSE BEGIN -----\n"
            f"{text}\n"
            "----- GEMINI RAW RESPONSE END -----",
            flush=True,
        )
    except UnicodeEncodeError:
        stdout_encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(
            f"[AI Updates] Gemini raw response before JSON parse "
            f"model={selected_model} chars={len(text)} finish_reasons={finish_reasons} usage={usage} "
            f"(response text omitted: undisplayable on this console's {stdout_encoding} encoding)",
            flush=True,
        )
    parsed = extract_json_object(text)
    if usage:
        _record_gemini_usage(quota, usage, selected_model)
    if isinstance(parsed, dict):
        parsed["__model_usage"] = {
            "provider": "gemini",
            "model": selected_model,
            "input_tokens": usage.get("prompt_token_count"),
            "output_tokens": usage.get("candidates_token_count"),
            "total_tokens": usage.get("total_token_count"),
            **quota,
            "raw": usage,
        }
    return parsed


@retry(
    retry=retry_if_exception_type(_RETRYABLE_GEMINI_EXCEPTIONS),
    wait=wait_exponential(multiplier=2, min=15, max=300),
    stop=stop_after_attempt(6),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _embed_content_with_retry(client: genai.Client, *, model: str, contents: list[str]) -> Any:
    try:
        return client.models.embed_content(
            model=model,
            contents=contents,
            # gemini-embedding-001 defaults to 3072-dim output, but the
            # Qdrant collection was created for OpenAI's 1536-dim
            # text-embedding-3-small and every semantic-memory upsert/search
            # was failing with "Vector dimension error: expected dim: 1536,
            # got 3072" (hit in production 2026-07-11) until this was set.
            # gemini-embedding-001 supports truncating to 1536 via Matryoshka
            # representation learning without retraining/recreating anything.
            config=types.EmbedContentConfig(output_dimensionality=1536),
        )
    except genai_errors.ClientError as exc:
        message = str(exc).lower()
        if any(signal in message for signal in ("429", "resource_exhausted", "deadline", "timeout", "500", "503")):
            raise _RetryableGeminiClientError(str(exc)) from exc
        raise


# WHAT: Gemini embeddings (greenfield - no Gemini embedding path existed
#       before; embed_texts in openai_client.py was OpenAI-only).
# HOW: ONE request for the WHOLE batch of texts, never one request per text -
#      embeddings must not become a second per-item request-count multiplier
#      after the tool-validation fix (see tools_aware.model_allows_tool_records_batch).
# INPUT: texts list.
# OUTPUT: list[list[float]], same length/order as the input, or [] on any
#         failure (matches openai_client.embed_texts's silent-failure contract
#         so callers in filtering/memory.py don't need provider-specific handling).
def embed_texts(texts: list[str]) -> list[list[float]]:
    cleaned = [str(text or "") for text in texts or []]
    if not GEMINI_API_KEY or not cleaned:
        return []
    client = _new_gemini_client()
    with _GEMINI_RATE_LIMIT_LOCK:
        quota = _reserve_gemini_request(GEMINI_EMBEDDING_MODEL)
        _wait_for_gemini_test_rate_limit()
    try:
        response = _embed_content_with_retry(client, model=GEMINI_EMBEDDING_MODEL, contents=cleaned)
    except Exception as exc:
        _record_gemini_error(quota, exc, GEMINI_EMBEDDING_MODEL)
        return []
    embeddings = getattr(response, "embeddings", None) or []
    vectors = [list(getattr(item, "values", None) or []) for item in embeddings]
    if len(vectors) == len(cleaned):
        _record_gemini_usage(quota, {"embedded_count": len(vectors)}, GEMINI_EMBEDDING_MODEL)
    return vectors
