# This file is part of the AI newsletter system.
"""Model calls and structured editorial selection.

The selected provider receives only normalized, live candidates from the
fetch/filter stages. It selects the final stories, writes Arabic summaries, and
returns structured data that can be validated against the original source URLs.
"""

from __future__ import annotations

import json
import hashlib
import re
import time
from collections import Counter

from pydantic import BaseModel, Field

from backend.config.settings import (
    AI_UPDATES_GPT_COMPACT_LIMIT,
    AI_UPDATES_OUTPUT_LIMIT,
    AI_UPDATES_SINGLE_GPT_COMPACT_LIMIT,
    AI_UPDATES_SINGLE_OUTPUT_LIMIT,
    NEWS_SECTORS,
    AI_UPDATES_RUN_REPORT_FILE,
    MODEL_USAGE_SUMMARY_FILE,
    NEWS_FETCH_STATE_FILE,
    clean_text,
    env_int,
    load_json,
    result_is_recent_enough,
    safe_write_json,
    source_domain,
    normalized_text,
    utc_now,
)
from backend.logging.pipeline_logging import get_mode, get_run_id, log_event, summarize_items
from backend.pipeline.modeling.model_client import (
    MODEL_FLASH_MODEL,
    MODEL_PROVIDER,
    generate_json,
    generate_json_for_role,
    model_available,
    model_error_details,
    model_for_role,
    model_quota_remaining,
)
from backend.pipeline.modeling.usage_state import load_usage_state, update_usage_state
from backend.pipeline.fetching.news_discovery import (
    candidate_owner_key,
    domain_blocked,
    infer_sector,
    source_candidate_hard_reject_reason,
)
from backend.pipeline.fetching.course_bank import COURSE_WEEKLY_TARGET_COUNT, select_weekly_courses, upsert_course_bank
from backend.pipeline.filtering.level_balancing import normalize_level
from backend.pipeline.modeling.prompts.news_prompt import build_news_rewrite_prompt, build_news_selection_prompt
from backend.pipeline.modeling.prompts.supporting_prompt import build_supporting_prompt

MODEL_USAGE_FILE = MODEL_USAGE_SUMMARY_FILE
COURSE_MAJOR_PLATFORM_KEYS = {"coursera", "udemy", "edx", "linkedin learning"}
NEWS_MODEL_BATCHING_ENABLED = env_int("AI_UPDATES_NEWS_MODEL_BATCHING_ENABLED", "0") == 1
NEWS_MODEL_BATCH_SIZE = max(1, min(5, env_int("AI_UPDATES_NEWS_MODEL_BATCH_SIZE", "5")))
NEWS_MODEL_MAX_BATCHES = max(1, env_int("AI_UPDATES_NEWS_MODEL_MAX_BATCHES", "5"))
NEWS_TOPUP_MIN_PRIMARY_SELECTED = max(0, env_int("AI_UPDATES_NEWS_TOPUP_MIN_PRIMARY_SELECTED", "4"))
MIN_NEWS_SUMMARY_CHARS = max(40, env_int("AI_UPDATES_MIN_NEWS_SUMMARY_CHARS", "120"))
LOW_VALUE_NEWS_TITLE_TERMS = (
    "new cursor interface",
    "full-screen tabs",
    "compact chats",
    "canvas improvements",
    "more discoverable",
    "smart suggestions",
    "keyboard-first design",
    "context usage report",
)
STRONG_NEWS_VALUE_TERMS = (
    "agent",
    "assistant",
    "voice",
    "image",
    "video",
    "native audio",
    "multimodal",
    "reasoning",
    "automation",
    "analytics",
    "search",
    "transcription",
    "generate",
    "generates",
    "now available",
    "general availability",
    "launch",
    "launched",
    "introducing",
    "ÙˆÙƒÙŠÙ„",
    "Ù…Ø³Ø§Ø¹Ø¯",
    "ØµÙˆØª",
    "ØµÙˆØ±",
    "ÙÙŠØ¯ÙŠÙˆ",
    "ØªØ­Ù„ÙŠÙ„",
)


# Performs the estimate prompt tokens helper step.
def estimate_prompt_tokens(system_prompt: str, user_payload) -> dict:
    user_text = user_payload if isinstance(user_payload, str) else json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))
    input_chars = len(str(system_prompt or "")) + len(str(user_text or ""))
    return {
        "estimated_input_chars": input_chars,
        "estimated_input_tokens": max(1, round(input_chars / 4)),
    }


# Performs the log token usage helper step.
# Loads the current model usage summary file.
def load_model_usage_summary() -> dict:
    return load_usage_state(MODEL_USAGE_FILE)


# Returns the usage bucket for the current run.
def model_usage_run(summary: dict) -> dict:
    run_id = get_run_id() or "manual"
    runs = summary.setdefault("runs", {})
    run = runs.setdefault(run_id, {
        "run_id": run_id,
        "mode": get_mode(),
        "started_at": utc_now().isoformat(),
        "calls": [],
        "failures": [],
        "totals": {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_input_tokens": 0,
            "by_provider": {},
            "by_model": {},
        },
    })
    run["mode"] = run.get("mode") or get_mode()
    return run


# Adds token counts to nested provider/model totals.
def add_model_usage_totals(bucket: dict, input_tokens: int, output_tokens: int, total_tokens: int, estimated_tokens: int) -> None:
    bucket["calls"] = int(bucket.get("calls") or 0) + 1
    bucket["input_tokens"] = int(bucket.get("input_tokens") or 0) + input_tokens
    bucket["output_tokens"] = int(bucket.get("output_tokens") or 0) + output_tokens
    bucket["total_tokens"] = int(bucket.get("total_tokens") or 0) + total_tokens
    bucket["estimated_input_tokens"] = int(bucket.get("estimated_input_tokens") or 0) + estimated_tokens


# Records a successful model call in model_usage_summary.json.
def record_model_usage(stage: str, model: str, provider: str, usage: dict | None, estimate: dict | None, extra: dict) -> None:
    def update(summary: dict) -> None:
        run = model_usage_run(summary)
        input_tokens = int((usage or {}).get("input_tokens") or 0)
        output_tokens = int((usage or {}).get("output_tokens") or 0)
        total_tokens = int((usage or {}).get("total_tokens") or 0)
        estimated_tokens = int((estimate or {}).get("estimated_input_tokens") or 0)
        run.setdefault("calls", []).append({
            "ts": utc_now().isoformat(),
            "stage": stage,
            "provider": provider,
            "model": model,
            "status": "success",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "estimated_input_tokens": estimated_tokens,
            "payload_candidates": extra.get("payload_candidates"),
            "request_number_today": (usage or {}).get("request_number_today"),
            "remaining_daily_requests": (usage or {}).get("remaining_daily_requests"),
            "daily_request_budget": (usage or {}).get("daily_request_budget"),
            "run_request_number": (usage or {}).get("run_request_number"),
            "run_request_budget": (usage or {}).get("run_request_budget"),
        })
        totals = run.setdefault("totals", {})
        add_model_usage_totals(totals, input_tokens, output_tokens, total_tokens, estimated_tokens)
        provider_totals = totals.setdefault("by_provider", {}).setdefault(provider, {})
        add_model_usage_totals(provider_totals, input_tokens, output_tokens, total_tokens, estimated_tokens)
        model_totals = totals.setdefault("by_model", {}).setdefault(model, {})
        add_model_usage_totals(model_totals, input_tokens, output_tokens, total_tokens, estimated_tokens)
        summary["updated_at"] = utc_now().isoformat()

    update_usage_state(MODEL_USAGE_FILE, update)


# Records a failed model call in model_usage_summary.json.
def record_model_failure(stage: str, model: str, provider: str, details: dict, extra: dict | None = None) -> None:
    def update(summary: dict) -> None:
        run = model_usage_run(summary)
        run.setdefault("failures", []).append({
            "ts": utc_now().isoformat(),
            "stage": stage,
            "provider": provider,
            "model": model,
            "status": "failed",
            "category": details.get("category"),
            "quota_error_category": details.get("quota_error_category"),
            "request_number_today": details.get("request_number_today"),
            "remaining_daily_requests": details.get("remaining_daily_requests"),
            "daily_request_budget": details.get("daily_request_budget"),
            "error": str(details.get("error") or "")[:1200],
            **(extra or {}),
        })
        summary["updated_at"] = utc_now().isoformat()

    update_usage_state(MODEL_USAGE_FILE, update)


def log_token_usage(stage: str, model: str, provider: str, usage: dict | None, estimate: dict | None = None, **extra) -> None:
    usage_payload = dict(usage or {})
    usage_payload.pop("provider", None)
    usage_payload.pop("model", None)
    payload = {
        "stage": stage,
        "model": model,
        "provider": provider,
        **(estimate or {}),
        **usage_payload,
        **extra,
    }
    log_event("model.token_usage", **payload)
    record_model_usage(stage, model, provider, usage, estimate, extra)
    total = payload.get("total_tokens")
    estimated = payload.get("estimated_input_tokens")
    actual_part = f" total={total}" if total is not None else ""
    print(
        f"[AI Updates] token usage stage={stage} provider={provider} model={model} "
        f"estimated_input={estimated}{actual_part}",
        flush=True,
    )


# Performs the model error details helper step.
def model_failure_details(exc: Exception) -> dict:
    return model_error_details(exc)


class AITool(BaseModel):
    """Structured schema GPT must fill for each selected news card."""
    title: str = Field(description="Arabic title, 6 to 8 words, specific to the update")
    tool_name: str = Field(description="Product or tool name")
    company_name: str = Field(description="Canonical product owner")
    official_url: str = Field(description="Source URL from the provided candidate list")
    whats_new: str = Field(description="Arabic 3-4 sentence paragraph")
    sector: str = Field(default="", description="One of the approved 15 sectors")
    # Level-balanced newsletter change: GPT classifies news by the practical
    # solution/use case so the saver can build a balanced level bank.
    solution_provided: str = Field(default="", description="Practical solution or use case provided by the update")
    main_user_benefit: str = Field(default="", description="Main practical user benefit")
    likely_user: str = Field(default="", description="Likely user type for this solution")
    level: str = Field(default="", description="beginner, intermediate, or advanced")
    topic_group: str = Field(default="", description="Topic group used for diversity inside each level")
    audience_fit: str = Field(default="", description="general, semi_technical, or technical")
    should_simplify: bool = Field(default=False, description="True when the card should be simplified for general readers")
    classification_reason: str = Field(default="", description="Short explanation for level classification")
    is_highlight: bool = Field(default=False, description="True only for the strongest update")
    highlight_reason: str = Field(default="", description="Short reason for the highlight")


class TargetAIReport(BaseModel):
    latest_updates: list[AITool] = Field(default=[])
    timestamp: str

def failure_report(reason: str, diagnostics: dict | None = None) -> dict:
    return {
        "latest_updates": [],
        "timestamp": utc_now().isoformat(),
        "success": False,
        "error": reason,
        "diagnostics": diagnostics or {},
    }


# Performs the result url key helper step.
def result_url_key(url: str) -> str:
    return (url or "").strip().rstrip("/")


# Prepares normalized update title so downstream stages receive consistent data.
def normalized_update_title(value: str = "") -> str:
    return " ".join(clean_text(value).lower().split())


SOURCE_FILLER_PHRASES = (
    "كما ذكر المصدر",
    "كما ورد في المصدر",
    "بحسب المصدر",
    "وفقًا للمصدر",
    "وفقا للمصدر",
    "نُشر في المدونة",
    "نشر في المدونة",
    "نشرت المدونة",
    "ضمن تحديثات",
    "كتحديثات",
    "في مدونة",
)

MODEL_REJECTION_PATTERNS = (
    r"\bمرفوض\b",
    r"\bمرفوضة\b",
    r"\bرفض\b",
    r"\bغير صالح\b",
    r"\bغير صالحة\b",
    r"\bلا يصلح\b",
    r"\bلا تصلح\b",
    r"\bليس تحديث\b",
    r"\bليست تحديث\b",
    r"\bليس(?:ت)? (?:إعلان|اعلان|ميزة)\b",
    r"\bلا توجد إشارة\b",
    r"\bلا يوضح تحديث\b",
    r"\bلا توضّح تحديث\b",
    r"\bخارج نافذة\b",
    r"\bخارج النطاق\b",
    r"\breject(?:ed|ion)?\b",
    r"\bnot a valid\b",
    r"\bnot an update\b",
    r"\bnot eligible\b",
    r"\boutside the window\b",
    r"\bdoes not describe\b",
)


# Performs the strip source filler sentences helper step.
def strip_source_filler_sentences(value: str = "") -> str:
    """Remove editorial filler that only references the source/date."""
    text = clean_text(value or "")
    if not text:
        return ""
    for phrase in SOURCE_FILLER_PHRASES:
        text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
    sentences = re.split(r"(?<=[.!؟])\s+", text)
    kept = []
    for sentence in sentences:
        lowered = sentence.lower()
        source_only = any(
            marker in lowered
            for marker in (
                "المدونة الرسمية",
                "تحديثات مايو",
                "تحديثات يونيو",
                "مدونة",
                "نشرت",
                "مايو",
                "يونيو",
                "الرسمية",
                "بحسب",
                "وفق",
                "المصدر",
                "official blog",
                "according to",
            )
        )
        feature_signal = any(
            marker in lowered
            for marker in (
                "ميزة",
                "تتيح",
                "يتيح",
                "تضيف",
                "يضيف",
                "يدعم",
                "يمكن",
                "إطلاق",
                "new feature",
                "users can",
                "now available",
            )
        )
        if source_only and not feature_signal:
            continue
        clean_sentence = sentence.strip(" ،,")
        if clean_sentence:
            kept.append(clean_sentence)
    cleaned = " ".join(kept).strip()
    return re.sub(r"\s{2,}", " ", cleaned).strip()


# Performs the flatten nested parentheses helper step.
def flatten_nested_parentheses(value: str = "") -> str:
    """Collapse nested display parentheses, e.g. (Nano (Banana) 2)."""
    text = clean_text(value or "")
    pattern = re.compile(r"\(([^()]*)\(([^()]+)\)([^()]*)\)")
    previous = None
    while previous != text:
        previous = text
        text = pattern.sub(lambda match: f"({match.group(1)}{match.group(2)}{match.group(3)})", text)
    return re.sub(r"\s{2,}", " ", text).strip()


# Performs the wrap english terms helper step.
def wrap_english_terms(value: str = "") -> str:
    """Ensure English product/model/technical terms appear inside one pair of parentheses."""
    text = flatten_nested_parentheses(value)
    if not text:
        return ""
    parts = re.split(r"(\([^()]*\))", text)
    english_run = re.compile(r"\b[A-Za-z][A-Za-z0-9&+.\-]*(?:\s+[A-Za-z0-9&+.\-]+){0,4}\b")

    # Performs the wrap helper step.
    def wrap(match: re.Match) -> str:
        phrase = match.group(0).strip()
        if not phrase:
            return phrase
        return f"({phrase})"

    output = []
    for part in parts:
        if not part:
            continue
        if part.startswith("(") and part.endswith(")"):
            output.append(flatten_nested_parentheses(part))
        else:
            output.append(english_run.sub(wrap, part))
    return flatten_nested_parentheses("".join(output))


# Prepares normalize editorial text so downstream stages receive consistent data.
def normalize_editorial_text(value: str = "") -> str:
    return wrap_english_terms(strip_source_filler_sentences(value))


# Performs the model rejection text reason helper step.
def model_rejection_text_reason(item: dict) -> str:
    """Catch cases where GPT returns its rejection note as if it were a story."""
    text = clean_text(
        " ".join(
            str(item.get(key) or "")
            for key in ("title", "tool_name", "company_name", "whats_new", "highlight_reason")
        )
    )
    if not text:
        return ""
    lowered = text.lower()
    for pattern in MODEL_REJECTION_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return pattern
    return ""


def selected_item_quality_reject_reason(item: dict, source_item: dict) -> str:
    """Reject model selections that are too weak to become newsletter cards."""
    title = normalized_update_title(
        " ".join(
            str(value or "")
            for value in (
                item.get("title"),
                item.get("tool_name"),
                item.get("company_name"),
                source_item.get("title"),
            )
        )
    )
    whats_new = clean_text(item.get("whats_new") or "")
    if len(whats_new) < MIN_NEWS_SUMMARY_CHARS:
        return "empty_or_too_short_summary"
    if normalize_level(item.get("level") or item.get("news_level")) not in {"beginner", "intermediate", "advanced"}:
        return "missing_or_invalid_news_level"
    if any(term in title for term in LOW_VALUE_NEWS_TITLE_TERMS) and not any(term in title or term in whats_new.lower() for term in STRONG_NEWS_VALUE_TERMS):
        return "low_value_ui_or_navigation_change"
    return ""


# Performs the selected story tokens helper step.
def selected_story_tokens(item: dict) -> set[str]:
    source_item = item.get("source_item") if isinstance(item.get("source_item"), dict) else {}
    text = normalized_update_title(
        " ".join(
            str(item.get(key) or "")
            for key in ("title", "tool_name", "company_name", "source_title", "whats_new")
        )
        + " "
        + " ".join(
            str(source_item.get(key) or "")
            for key in ("title", "content", "summary", "query", "tool", "company")
        )
    )
    stop = {
        "ai", "the", "and", "for", "with", "now", "new", "feature", "users", "can",
        "available", "launch", "launches", "adds", "inside", "directly",
        "artificial", "intelligence", "official", "announcement", "update", "updates",
        "product", "tool", "tools", "app", "release", "released", "rollout",
    }
    return {word for word in re.split(r"\s+", text) if len(word) >= 4 and word not in stop}


# Performs the selected same story helper step.
def selected_same_story(left: dict, right: dict) -> bool:
    left_source = left.get("source_item") if isinstance(left.get("source_item"), dict) else {}
    right_source = right.get("source_item") if isinstance(right.get("source_item"), dict) else {}
    left_story = str(left_source.get("story_key") or "").strip()
    right_story = str(right_source.get("story_key") or "").strip()
    if left_story and right_story and left_story == right_story:
        return True
    return False


# Prepares dedupe selected updates so downstream stages receive consistent data.
def dedupe_selected_updates(items: list[dict], diagnostics: dict) -> list[dict]:
    seen_urls = set()
    seen_titles = set()
    unique = []
    removed = 0
    same_story_removed = 0
    for item in items or []:
        source_item = item.get("source_item") if isinstance(item.get("source_item"), dict) else {}
        url_key = result_url_key(item.get("official_url") or source_item.get("url") or "").lower()
        title_key = normalized_update_title(item.get("title") or item.get("source_title") or source_item.get("title") or "")
        if (url_key and url_key in seen_urls) or (title_key and title_key in seen_titles):
            removed += 1
            continue
        if any(selected_same_story(item, existing) for existing in unique):
            same_story_removed += 1
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        unique.append(item)
    if removed:
        diagnostics["duplicate_model_updates_removed"] = removed
    if same_story_removed:
        diagnostics["same_story_model_updates_removed"] = same_story_removed
    return unique


# Performs the compact model candidate helper step.
def compact_model_candidate(item: dict) -> dict:
    """Keep model context small while preserving selection evidence."""
    return {
        "title": clean_text(item.get("title") or "")[:220],
        "content": clean_text(item.get("content") or item.get("summary") or "")[:700],
        "url": item.get("url") or "",
        "source_domain": item.get("source_domain") or source_domain(item.get("url") or ""),
        "published_date": item.get("published_date") or item.get("published_raw") or "",
        "source_type": item.get("source_type") or "",
        "tool": item.get("tool") or "",
        "company": item.get("company") or "",
        "query_mix": item.get("query_mix") or "",
        "source_lane": item.get("source_lane") or "",
        "date_confidence": item.get("date_confidence") or "",
        "official_domain": item.get("official_domain") or "",
        "trusted_media_name": item.get("trusted_media_name") or "",
        "trusted_media_domain": item.get("trusted_media_domain") or "",
        "acceptance_reason": item.get("acceptance_reason") or "",
        "fetch_method": item.get("fetch_method") or "",
        "candidate_flags": list(item.get("candidate_flags") or [])[:12],
        "update_priority": item.get("update_priority") or 0,
        "product_update_signal": item.get("product_update_signal") or "",
    }

# Selection and rewriting are now two separate model calls (see
# build_news_selection_prompt's docstring comment), so the old single
# filter_model_items() is split into three stages that ask_model() runs in
# order: attach_source_items() (structural checks that don't need
# title/whats_new, since those don't exist until after the rewrite call),
# rewrite_selected_items() (the rewrite call itself), and
# finalize_selected_items() (the quality/rejection-text checks that DO need
# the rewritten text).


# Prepares filter model items so downstream stages receive consistent data.
def attach_source_items(items: list[dict], source_by_url: dict[str, dict], diagnostics: dict) -> list[dict]:
    """Match selection-stage output back to its raw candidate; drop items
    with a bad domain, no matching source, a hard source-level rejection, or
    a stale published date. Does not touch title/whats_new."""
    matched = []
    rejected = []
    for index, item in enumerate(items or []):
        url = item.get("official_url") or ""
        domain = source_domain(url)
        if domain_blocked(domain):
            rejected.append({"title": item.get("tool_name"), "reason": "disallowed_source_domain", "domain": domain})
            continue
        source_item = source_by_url.get(result_url_key(url))
        if not source_item:
            rejected.append({"title": item.get("tool_name"), "reason": "source_url_not_in_live_results", "domain": domain})
            continue
        title = source_item.get("title") or ""
        content = source_item.get("content") or ""
        published_date = source_item.get("published_date") or source_item.get("published_raw") or ""
        # Editorial policy: re-check the full source after selection because
        # narrow availability can be hidden inside the article body.
        source_reject_reason = source_candidate_hard_reject_reason(source_item)
        if source_reject_reason:
            rejected.append({"title": item.get("tool_name"), "reason": source_reject_reason, "domain": domain})
            continue
        # News freshness change: keep rejection diagnostics tied to the
        # configured lookback window instead of the old fixed 14-day label.
        if not result_is_recent_enough(published_date):
            rejected.append({"title": item.get("tool_name"), "reason": "outside_lookback_window", "domain": domain})
            continue
        item["rewrite_id"] = str(index)
        item["tool_name"] = flatten_nested_parentheses(clean_text(item.get("tool_name") or ""))
        item["company_name"] = flatten_nested_parentheses(clean_text(item.get("company_name") or ""))
        item["source_item"] = source_item
        item["source_title"] = title
        item["source_domain"] = source_item.get("source_domain") or domain
        item["published_date"] = published_date
        item["source_query"] = source_item.get("query") or ""
        item["source_bucket"] = source_item.get("bucket") or ""
        if item.get("sector") not in NEWS_SECTORS:
            item["sector"] = infer_sector(title, content, "")
        matched.append(item)
    if rejected:
        diagnostics.setdefault("gpt_output_rejected", []).extend(rejected)
    return matched


# Sends every matched item to the rewrite model in ONE request (never one
# request per item) and merges the Arabic title/whats_new back by
# rewrite_id. An item missing from the rewrite response is dropped, matching
# the old fused-prompt behavior of rejecting candidates too weak to write a
# grounded card for.
def rewrite_selected_items(matched: list[dict], diagnostics: dict, stage: str) -> list[dict]:
    if not matched:
        return []
    payload = [
        {
            "id": item["rewrite_id"],
            "source_title": item.get("source_title") or "",
            "source_text": clean_text((item.get("source_item") or {}).get("content") or "")[:900],
        }
        for item in matched
    ]
    rewrite_model = model_for_role("rewrite")
    log_event(
        "prompt.news_rewrite.started",
        stage=stage,
        model=rewrite_model,
        provider=MODEL_PROVIDER,
        items=len(payload),
    )
    started = time.time()
    try:
        parsed = generate_json_for_role("rewrite", build_news_rewrite_prompt(), {"items": payload})
    except Exception as exc:
        details = model_failure_details(exc)
        diagnostics[f"{MODEL_PROVIDER}_{stage}_rewrite_failure"] = details
        record_model_failure(f"{stage}_rewrite", rewrite_model, MODEL_PROVIDER, details, {"items": len(payload)})
        log_event(
            "prompt.news_rewrite.model_failed",
            stage=stage,
            model=rewrite_model,
            provider=MODEL_PROVIDER,
            **{key: value for key, value in details.items() if key not in {"provider", "model"}},
        )
        print(f"[AI Updates] {MODEL_PROVIDER} rewrite failed stage={stage} category={details.get('category', 'unknown')} error={details.get('error', str(exc))}", flush=True)
        return []
    if not isinstance(parsed, dict):
        return []
    usage = parsed.pop("__model_usage", None)
    if usage:
        log_token_usage(f"{stage}_rewrite", rewrite_model, MODEL_PROVIDER, usage, payload_candidates=len(payload))
    by_id = {}
    for row in parsed.get("rewritten") or []:
        rid = str(row.get("id") or "")
        if rid:
            by_id[rid] = row
    log_event(
        "prompt.news_rewrite.finished",
        stage=stage,
        seconds=round(time.time() - started, 2),
        requested=len(payload),
        rewritten=len(by_id),
    )
    result = []
    for item in matched:
        row = by_id.get(item["rewrite_id"])
        if not row:
            continue
        item["title"] = normalize_editorial_text(row.get("title") or "")
        item["whats_new"] = normalize_editorial_text(row.get("whats_new") or "")
        result.append(item)
    return result


# Quality/rejection-text checks that need the rewritten title/whats_new -
# the part of the old filter_model_items() that had to move after the
# rewrite call.
def finalize_selected_items(items: list[dict], diagnostics: dict) -> list[dict]:
    kept = []
    rejected = []
    for item in items or []:
        source_item = item.get("source_item") if isinstance(item.get("source_item"), dict) else {}
        quality_reject_reason = selected_item_quality_reject_reason(item, source_item)
        if quality_reject_reason:
            rejected.append({"title": item.get("title") or item.get("tool_name"), "reason": quality_reject_reason})
            continue
        rejection_reason = model_rejection_text_reason(item)
        if rejection_reason:
            rejected.append({
                "title": item.get("title") or item.get("tool_name"),
                "reason": "model_returned_rejection_explanation",
                "match": rejection_reason,
            })
            continue
        item["owner_key"] = candidate_owner_key(
            {
                **source_item,
                "company_name": item.get("company_name") or source_item.get("company_name"),
                "tool_name": item.get("tool_name") or source_item.get("tool_name"),
            },
            url=item.get("official_url") or "",
            title=f"{item.get('title') or ''} {item.get('source_title') or ''}",
            content=f"{item.get('whats_new') or ''} {source_item.get('content') or ''}",
        )
        kept.append(item)
    if rejected:
        diagnostics.setdefault("gpt_output_rejected", []).extend(rejected)
    return kept

# Prepares balance for diversity so downstream stages receive consistent data.
def balance_for_diversity(items: list[dict], target_limit: int, diagnostics: dict, *, company_cap: int = 2) -> list[dict]:
    """Preserve quality while enforcing duplicates, owner caps, and level balance."""
    items = dedupe_selected_updates(items, diagnostics)
    if not items:
        return []

    preselected = []
    company_counts = Counter()
    for item in items:
        source_item = item.get("source_item") if isinstance(item.get("source_item"), dict) else {}
        if item.get("sector") not in NEWS_SECTORS:
            item["sector"] = infer_sector(
                item.get("title") or "",
                item.get("whats_new") or source_item.get("content") or "",
                "",
            )
        owner = item.get("owner_key") or candidate_owner_key(item, url=item.get("official_url") or "")
        item["owner_key"] = owner
        if owner and company_counts[owner] >= company_cap:
            continue
        preselected.append(item)
        if owner:
            company_counts[owner] += 1

    # Level-balanced newsletter change: keep a balanced unique bank whenever
    # the model returned enough classified
    # candidates. Do not duplicate items to fake a complete level.
    if target_limit >= 12:
        per_level_target = max(1, target_limit // 3)
        selected = []
        selected_keys = set()
        level_shortages = {}
        for level in ("beginner", "intermediate", "advanced"):
            level_items = [item for item in preselected if normalize_level(item.get("level") or item.get("news_level")) == level]
            for item in level_items:
                key = result_url_key(item.get("official_url") or "") or normalized_update_title(item.get("title") or "")
                if key in selected_keys:
                    continue
                selected.append(item)
                selected_keys.add(key)
                if len([entry for entry in selected if normalize_level(entry.get("level") or entry.get("news_level")) == level]) >= per_level_target:
                    break
            level_count = len([entry for entry in selected if normalize_level(entry.get("level") or entry.get("news_level")) == level])
            if level_count < per_level_target:
                level_shortages[level] = per_level_target - level_count
        for item in preselected:
            if len(selected) >= target_limit:
                break
            key = result_url_key(item.get("official_url") or "") or normalized_update_title(item.get("title") or "")
            if key in selected_keys:
                continue
            selected.append(item)
            selected_keys.add(key)
        diagnostics["level_counts_after_balance"] = dict(Counter(normalize_level(item.get("level") or item.get("news_level")) or "unknown" for item in selected))
        if level_shortages:
            diagnostics["level_balance_shortages"] = level_shortages
    else:
        selected = preselected[:target_limit]

    if selected:
        highlight_seen = False
        for item in selected:
            if item.get("is_highlight") and not highlight_seen:
                highlight_seen = True
            else:
                item["is_highlight"] = False
            item.setdefault("highlight_reason", "")
        if not highlight_seen:
            selected[0]["is_highlight"] = True
            selected[0]["highlight_reason"] = selected[0].get("highlight_reason") or "اختيار المودل الأعلى أولوية"

    diagnostics["sector_counts_after_balance"] = dict(Counter(item.get("sector") or "unknown" for item in selected))
    diagnostics["visible_sector_counts"] = dict(Counter(item.get("sector") or "unknown" for item in selected[:6]))
    diagnostics["company_counts_after_balance"] = dict(Counter(item.get("owner_key") or "unknown" for item in selected))
    diagnostics["visible_company_counts"] = dict(Counter(item.get("owner_key") or "unknown" for item in selected[:6]))
    diagnostics["highlight_title"] = next((item.get("title") for item in selected if item.get("is_highlight")), selected[0].get("title") if selected else "")
    return selected



# Performs the select news updates helper step.
def select_news_updates(candidates: list[dict], diagnostics: dict, *, single: bool = False) -> dict:
    """Ask GPT to select final updates from the shortlist."""
    target_limit = max(1, AI_UPDATES_SINGLE_OUTPUT_LIMIT if single else AI_UPDATES_OUTPUT_LIMIT)
    configured_limit = max(1, AI_UPDATES_SINGLE_GPT_COMPACT_LIMIT if single else AI_UPDATES_GPT_COMPACT_LIMIT)
    compact_limit = min(max(configured_limit, target_limit * 5), 24 if single else 72)
    if not candidates:
        return failure_report(diagnostics.get("error") or "no_live_results", diagnostics)
    if not model_available():
        return failure_report(f"missing_{MODEL_PROVIDER}_api_key", diagnostics)

    # Performs the ask model helper step.
    def ask_model(compact_source: list[dict], ask_limit: int, stage: str) -> list[dict]:
        compact = [compact_model_candidate(item) for item in compact_source]
        source_by_url = {result_url_key(item.get("url") or ""): item for item in compact_source if item.get("url")}
        diagnostics[f"gpt_{stage}_payload_candidates"] = len(compact)
        if stage == "primary":
            diagnostics["gpt_compact_limit_used"] = len(compact_source)
            diagnostics["gpt_payload_candidates"] = len(compact)
        print(f"[AI Updates] Sending {len(compact)} live results to GPT ({stage})", flush=True)
        prompt_started = time.time()
        initial_model = model_for_role("selection")
        initial_provider = MODEL_PROVIDER
        log_event(
            "prompt.news_selection.started",
            stage=stage,
            model=initial_model,
            provider=initial_provider,
            prompt_name="model_prompt",
            ask_limit=ask_limit,
            payload_candidates=len(compact),
            candidate_sample=summarize_items(compact_source, limit=8),
        )
        selected_model = initial_model
        selected_provider = initial_provider
        prompt_text = build_news_selection_prompt(ask_limit, single=single, batch_mode=bool(NEWS_MODEL_BATCHING_ENABLED and stage.endswith(tuple(str(i) for i in range(1, NEWS_MODEL_MAX_BATCHES + 1)))))
        estimate = estimate_prompt_tokens(prompt_text, compact)
        log_event(
            "model.token_estimate",
            stage=stage,
            model=selected_model,
            provider=selected_provider,
            payload_candidates=len(compact),
            **estimate,
        )
        try:
            parsed_data = generate_json_for_role("selection", prompt_text, compact)
        except Exception as model_exc:
            details = model_failure_details(model_exc)
            diagnostics[f"{MODEL_PROVIDER}_{stage}_failure"] = details
            record_model_failure(
                stage,
                selected_model,
                MODEL_PROVIDER,
                details,
                {"payload_candidates": len(compact)},
            )
            log_event(
                "prompt.news_selection.model_failed",
                stage=stage,
                model=selected_model,
                provider=MODEL_PROVIDER,
                **{key: value for key, value in details.items() if key not in {"provider", "model"}},
            )
            print(
                f"[AI Updates] {MODEL_PROVIDER} failed stage={stage} "
                f"category={details.get('category', 'unknown')} error={details.get('error', str(model_exc))}",
                flush=True,
            )
            raise
        if isinstance(parsed_data, list):
            parsed_data = {"latest_updates": parsed_data}
        if not isinstance(parsed_data, dict):
            raise RuntimeError(f"model_prompt_format_incompatible:{type(parsed_data).__name__}")
        usage = parsed_data.pop("__model_usage", None) if isinstance(parsed_data, dict) else None
        log_token_usage(stage, selected_model, selected_provider, usage, estimate, payload_candidates=len(compact))
        raw_selected = list(parsed_data.get("latest_updates") or [])[:ask_limit]
        # Two-call flow: selection just ran above; attach_source_items does
        # the structural checks that don't need Arabic text, then
        # rewrite_selected_items makes ONE rewrite request for the whole
        # matched batch, then finalize_selected_items runs the quality checks
        # that need the rewritten title/whats_new. See the docstring comment
        # on build_news_selection_prompt for why this is split in two calls.
        matched = attach_source_items(raw_selected, source_by_url, diagnostics)
        rewritten = rewrite_selected_items(matched, diagnostics, stage)
        selected = finalize_selected_items(rewritten, diagnostics)
        log_event(
            "prompt.news_selection.finished",
            stage=stage,
            model=selected_model,
            provider=selected_provider,
            seconds=round(time.time() - prompt_started, 2),
            raw_selected=len(raw_selected),
            selected=len(selected),
            selected_sample=summarize_items(selected, limit=8),
        )
        return selected

    def ask_model_batches(compact_source: list[dict], ask_limit: int, stage: str) -> list[dict]:
        if not NEWS_MODEL_BATCHING_ENABLED or single or len(compact_source) <= NEWS_MODEL_BATCH_SIZE:
            return ask_model(compact_source, ask_limit, stage)
        selected: list[dict] = []
        failed: list[dict] = []
        batches = [
            compact_source[index:index + NEWS_MODEL_BATCH_SIZE]
            for index in range(0, len(compact_source), NEWS_MODEL_BATCH_SIZE)
        ][:NEWS_MODEL_MAX_BATCHES]
        diagnostics[f"gpt_{stage}_batch_size"] = NEWS_MODEL_BATCH_SIZE
        diagnostics[f"gpt_{stage}_max_batches"] = NEWS_MODEL_MAX_BATCHES
        diagnostics[f"gpt_{stage}_batches"] = len(batches)
        for batch_index, batch in enumerate(batches, start=1):
            batch_stage = f"{stage}_batch_{batch_index}"
            print(
                f"[AI Updates] {MODEL_PROVIDER} batch {batch_index}/{len(batches)} "
                f"stage={stage} candidates={len(batch)}",
                flush=True,
            )
            try:
                batch_limit = min(len(batch), max(1, min(ask_limit, NEWS_MODEL_BATCH_SIZE)))
                batch_selected = ask_model(batch, batch_limit, batch_stage)
                selected.extend(batch_selected)
                diagnostics[f"gpt_{batch_stage}_selected"] = len(batch_selected)
            except Exception as exc:
                failed.append({"batch": batch_index, "error": str(exc)})
                diagnostics[f"gpt_{batch_stage}_error"] = str(exc)
                print(f"[AI Updates] {MODEL_PROVIDER} batch failed stage={batch_stage}: {exc}", flush=True)
                continue
            if len(selected) >= ask_limit:
                break
        diagnostics[f"gpt_{stage}_batch_failures"] = failed
        return selected

    compact_source = candidates[:compact_limit]
    try:
        data = {"latest_updates": [], "timestamp": utc_now().isoformat()}
        primary_ask_limit = target_limit if single else min(target_limit + 4, max(target_limit, len(compact_source)))
        selected = ask_model_batches(compact_source, primary_ask_limit, "primary")
        data["latest_updates"] = balance_for_diversity(selected, target_limit, diagnostics)
        if len(data["latest_updates"]) < target_limit:
            if not single and len(data["latest_updates"]) < NEWS_TOPUP_MIN_PRIMARY_SELECTED:
                diagnostics["gpt_topup_primary_below_minimum"] = True
                diagnostics["gpt_topup_min_primary_selected"] = NEWS_TOPUP_MIN_PRIMARY_SELECTED
            attempted_source_urls = {
                result_url_key(item.get("url") or "").lower()
                for item in compact_source
                if result_url_key(item.get("url") or "")
            }
            for attempt in range(1, 4):
                missing = target_limit - len(data["latest_updates"])
                if missing <= 0:
                    break
                if model_quota_remaining() <= 0:
                    diagnostics[f"gpt_topup_{attempt}_skipped"] = f"{MODEL_PROVIDER}_quota_exhausted"
                    break
                used_urls = {
                    result_url_key((item.get("official_url") or item.get("url") or "")).lower()
                    for item in data["latest_updates"]
                    if item.get("official_url") or item.get("url")
                }
                remaining_source = [
                    item for item in candidates
                    if (url_key := result_url_key(item.get("url") or "").lower())
                    and url_key not in used_urls
                    and url_key not in attempted_source_urls
                ]
                if not remaining_source:
                    remaining_source = [
                        item for item in candidates
                        if (url_key := result_url_key(item.get("url") or "").lower())
                        and url_key not in used_urls
                    ]
                retry_cap = 24 if single else 40
                retry_floor = 10 if single else 16
                retry_source = remaining_source[:min(max(retry_floor, missing * 6), retry_cap)]
                if not retry_source:
                    diagnostics[f"gpt_topup_{attempt}_skipped"] = "no_remaining_candidates"
                    break
                attempted_source_urls.update(
                    result_url_key(item.get("url") or "").lower()
                    for item in retry_source
                    if result_url_key(item.get("url") or "")
                )
                diagnostics["gpt_topup_attempted"] = True
                diagnostics[f"gpt_topup_{attempt}_missing_before"] = missing
                diagnostics[f"gpt_topup_{attempt}_payload_candidates"] = len(retry_source)
                try:
                    topup_ask_limit = min(len(retry_source), max(missing + 4, missing * 3))
                    topup_selected = ask_model_batches(retry_source, topup_ask_limit, f"topup_{attempt}")
                    diagnostics[f"gpt_topup_{attempt}_raw_selected"] = len(topup_selected)
                    selected = selected + topup_selected
                    data["latest_updates"] = balance_for_diversity(
                        selected,
                        target_limit,
                        diagnostics,
                    )
                except Exception as topup_exc:
                    diagnostics[f"gpt_topup_{attempt}_error"] = str(topup_exc)
                    break
        # Exposed so orchestrator.py can do a zero-extra-API-call last-resort
        # rebalance (relaxed company_cap) across cycles if the run still ends
        # up short of the target after normal selection - these items already
        # passed structural checks and got rewritten, they were only dropped
        # here for exceeding the diversity cap, not for quality reasons.
        data["preselected_pool"] = list(selected)
        data["timestamp"] = utc_now().isoformat()
        required_selected = 1 if single else target_limit
        data["success"] = bool(data["latest_updates"])
        data["diagnostics"] = diagnostics
        if not data["latest_updates"]:
            data["error"] = "gpt_selected_no_updates"
        elif len(data["latest_updates"]) < required_selected:
            data["partial"] = True
            data["warning"] = "partial_news_bank"
            diagnostics["partial_news_bank"] = {
                "selected": len(data["latest_updates"]),
                "target": required_selected,
                "reason": "model_selected_fewer_than_target",
            }
        print(f"[AI Updates] GPT selected {len(data['latest_updates'])} update(s)", flush=True)
        return data
    except Exception as exc:
        details = model_failure_details(exc)
        record_model_failure("news_selection", MODEL_FLASH_MODEL, MODEL_PROVIDER, details)
        print(f"[AI Updates] {MODEL_PROVIDER} failed: {details.get('category', 'unknown')} - {details.get('error', str(exc))}", flush=True)
        return failure_report(f"{MODEL_PROVIDER}_failed", {**diagnostics, f"{MODEL_PROVIDER}_failure": details})


# Performs the compact supporting candidate helper step.

# Compatibility exports for older imports. Supporting-card model selection now
# lives in backend.pipeline.modeling.supporting.
_SUPPORTING_MODEL_EXPORTS = {
    "SupportingCard",
    "SupportingReport",
    "compact_supporting_candidate",
    "merge_supporting_cards",
    "course_topic_key",
    "course_platform_key",
    "is_major_course_platform",
    "course_item_key",
    "course_platform_label",
    "course_level_label",
    "course_platform_level_pair",
    "save_last_course_platforms",
    "enforce_course_platform_level_pairs",
    "enforce_course_alternative_platforms",
    "prepare_course_prompt_pool",
    "balance_course_levels",
    "select_supporting_content_cards",
}

def __getattr__(name: str):
    if name in _SUPPORTING_MODEL_EXPORTS:
        from backend.pipeline.modeling import supporting as supporting_modeling
        return getattr(supporting_modeling, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Saves save model report to the configured output or state store.
def save_model_report(report: dict) -> bool:
    try:
        report["timestamp"] = utc_now().isoformat()
        safe_write_json(AI_UPDATES_RUN_REPORT_FILE, report)
        print(f"[AI Updates] Saved run report: {AI_UPDATES_RUN_REPORT_FILE}", flush=True)
        return True
    except Exception as exc:
        print(f"[AI Updates] Save failed: {exc}", flush=True)
        return False
