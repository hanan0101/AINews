# This file is part of the AI newsletter system.
"""Model calls and structured editorial selection.

The selected provider receives only normalized, live candidates from the
fetch/filter stages. It selects the final stories, writes Arabic summaries, and
returns structured data that can be validated against the original source URLs.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter

from backend.config.settings import (
    AI_UPDATES_GPT_COMPACT_LIMIT,
    AI_UPDATES_OUTPUT_LIMIT,
    AI_UPDATES_SINGLE_GPT_COMPACT_LIMIT,
    AI_UPDATES_SINGLE_OUTPUT_LIMIT,
    NEWS_SECTORS,
    AI_UPDATES_RUN_REPORT_FILE,
    MODEL_USAGE_SUMMARY_FILE,
    clean_text,
    env_int,
    result_is_recent_enough,
    safe_write_json,
    source_domain,
    normalized_text,
    parse_result_datetime,
    utc_now,
)
from backend.logging.pipeline_logging import get_mode, get_run_id, log_event, summarize_items
from backend.pipeline.modeling.model_client import (
    MODEL_FLASH_MODEL,
    MODEL_PROVIDER,
    generate_json_for_role,
    model_available,
    model_error_details,
    model_for_role,
    model_quota_remaining,
)
from backend.pipeline.modeling.usage_state import load_usage_state, update_usage_state
from backend.pipeline.fetching.content.news.normalization import (
    candidate_owner_key,
    domain_blocked,
    infer_sector,
    source_candidate_hard_reject_reason,
)
from backend.pipeline.filtering.content.courses.level_balancing import normalize_level
from backend.pipeline.modeling.content.news.prompt import build_news_rewrite_prompt, build_news_selection_prompt

MODEL_USAGE_FILE = MODEL_USAGE_SUMMARY_FILE
COURSE_MAJOR_PLATFORM_KEYS = {"coursera", "udemy", "edx", "linkedin learning"}
NEWS_MODEL_BATCHING_ENABLED = env_int("AI_UPDATES_NEWS_MODEL_BATCHING_ENABLED", "0") == 1
NEWS_MODEL_BATCH_SIZE = max(1, min(5, env_int("AI_UPDATES_NEWS_MODEL_BATCH_SIZE", "5")))
NEWS_MODEL_MAX_BATCHES = max(1, env_int("AI_UPDATES_NEWS_MODEL_MAX_BATCHES", "5"))
NEWS_TOPUP_MIN_PRIMARY_SELECTED = max(0, env_int("AI_UPDATES_NEWS_TOPUP_MIN_PRIMARY_SELECTED", "4"))
MIN_NEWS_SUMMARY_CHARS = max(40, env_int("AI_UPDATES_MIN_NEWS_SUMMARY_CHARS", "120"))
MIN_NEWS_SUMMARY_WORDS = 50
MAX_NEWS_SUMMARY_WORDS = 64
REJECTED_EVENT_TYPES = {"marketing_explainer", "unavailable_research", "old_news_recoverage"}
ABSOLUTE_MARKETING_CLAIMS = (
    "الأفضل في السوق",
    "احترافي بالكامل",
    "يلغي التكاليف",
    "يضمن الأمان",
    "دون تدخل بشري",
    "يحمي المؤسسة بالكامل",
    "يتفوق على المنافسين",
    "جاهز للإنتاج",
    "متوافق بالكامل",
    "يحول الفكرة تلقائيا إلى منتج نهائي",
    "يحوّل الفكرة تلقائيًا إلى منتج نهائي",
)
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
    "وكيل",
    "مساعد",
    "صوت",
    "صور",
    "فيديو",
    "تحليل",
)


# Performs the estimate prompt tokens helper step.
def estimate_prompt_tokens(system_prompt: str, user_payload) -> dict:
    user_text = user_payload if isinstance(user_payload, str) else json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))
    input_chars = len(str(system_prompt or "")) + len(str(user_text or ""))
    return {
        "estimated_input_chars": input_chars,
        "estimated_input_tokens": max(1, round(input_chars / 4)),
    }


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


def arabic_summary_word_count(value: str = "") -> int:
    """Count displayed words using the same whitespace rule given to the model."""
    return len([token for token in clean_text(value).split() if token])


def event_freshness_reject_reason(item: dict, source_item: dict | None = None) -> str:
    """Validate the real product event, independently of the page timestamp."""
    source_item = source_item if isinstance(source_item, dict) else {}
    event_type = clean_text(item.get("event_type") or source_item.get("event_type") or "").lower()
    if event_type in REJECTED_EVENT_TYPES:
        return event_type
    event_date = clean_text(item.get("event_date") or source_item.get("event_date") or "")
    if not event_date:
        return "missing_original_event_date"
    parsed = parse_result_datetime(event_date)
    if parsed is None:
        return "invalid_original_event_date"
    if parsed > utc_now():
        return "future_event_date"
    if not result_is_recent_enough(parsed):
        return "original_event_outside_lookback_window"
    if not clean_text(item.get("event_date_basis") or source_item.get("event_date_basis") or ""):
        return "missing_event_date_evidence"
    return ""


def rewrite_claim_reject_reason(item: dict) -> str:
    """Reject unsafe marketing language and launch verbs that contradict access."""
    text = normalized_text(f"{item.get('title') or ''} {item.get('whats_new') or ''}")
    for phrase in ABSOLUTE_MARKETING_CLAIMS:
        if normalized_text(phrase) in text:
            return "absolute_marketing_claim"
    status = clean_text(item.get("availability_status") or "").lower()
    if status in {"limited_access", "future", "unavailable"}:
        if any(phrase in text for phrase in ("متاح للجميع", "متاحة للجميع", "أطلقت", "أتاحت للجميع")):
            return "availability_claim_mismatch"
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
    word_count = arabic_summary_word_count(whats_new)
    if word_count < MIN_NEWS_SUMMARY_WORDS or word_count > MAX_NEWS_SUMMARY_WORDS:
        return "summary_word_count_out_of_range"
    claim_reject_reason = rewrite_claim_reject_reason(item)
    if claim_reject_reason:
        return claim_reject_reason
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
    # Two outlets covering the same real-world announcement get different
    # story_key hashes (computed upstream per-article), so story_key equality
    # alone missed cases like two separate articles about OpenAI's "Presence"
    # launch both landing in the same newsletter. Fall back to token overlap,
    # gated on a matching company so ordinary shared AI vocabulary between
    # unrelated companies never trips this. Threshold validated against a
    # real run: the true duplicate pair scored 0.28 overlap, every distinct
    # same-company story pair (e.g. three different Claude features) stayed
    # under 0.13.
    left_owner = normalized_update_title(left.get("company_name") or left_source.get("company") or "")
    right_owner = normalized_update_title(right.get("company_name") or right_source.get("company") or "")
    if not left_owner or left_owner != right_owner:
        return False
    left_tokens = selected_story_tokens(left)
    right_tokens = selected_story_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
    return overlap >= 0.2


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
        "updated_date": item.get("updated_date") or item.get("modified_date") or "",
        "event_date": item.get("event_date") or "",
        "event_date_basis": item.get("event_date_basis") or "",
        "availability_date": item.get("availability_date") or "",
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
    a stale page date or product-event date. Does not touch title/whats_new."""
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
        event_reject_reason = event_freshness_reject_reason(item, source_item)
        if event_reject_reason:
            rejected.append({"title": item.get("tool_name"), "reason": event_reject_reason, "domain": domain})
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
            "event_type": item.get("event_type") or "",
            "event_date": item.get("event_date") or "",
            "availability_status": item.get("availability_status") or "",
            "claim_basis": item.get("claim_basis") or "",
            "functional_category": item.get("functional_category") or "",
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


def infer_functional_category(item: dict) -> str:
    """Infer a broad editorial function when the model omitted the internal tag."""
    supplied = clean_text(item.get("functional_category") or "").lower()
    allowed = {
        "office_productivity", "daily_use", "education_research", "design_creative",
        "data_analytics", "security_privacy", "digital_services", "audio_video",
        "culture_creative", "other",
    }
    if supplied in allowed:
        return supplied
    source_item = item.get("source_item") if isinstance(item.get("source_item"), dict) else {}
    text = normalized_text(
        " ".join(
            str(value or "")
            for value in (
                item.get("title"), item.get("whats_new"), item.get("topic_group"),
                item.get("solution_provided"), source_item.get("title"), source_item.get("content"),
            )
        )
    )
    groups = (
        ("audio_video", ("video", "audio", "voice", "podcast", "فيديو", "صوت")),
        ("security_privacy", ("security", "privacy", "cyber", "أمان", "خصوصية")),
        ("data_analytics", ("data", "analytics", "spreadsheet", "بيانات", "تحليل")),
        ("education_research", ("education", "research", "learning", "تعليم", "بحث")),
        ("design_creative", ("design", "image", "creative", "تصميم", "صور")),
        ("office_productivity", ("office", "document", "presentation", "meeting", "productivity", "مستند", "عرض", "اجتماع")),
        ("culture_creative", ("culture", "heritage", "museum", "literature", "ثقافة", "تراث")),
        ("digital_services", ("service", "government", "banking", "خدمة", "حكومي")),
        ("daily_use", ("assistant", "search", "shopping", "travel", "مساعد", "بحث", "تسوق")),
    )
    for category, terms in groups:
        if any(term in text for term in terms):
            return category
    return "other"


def apply_functional_diversity(items: list[dict], target_limit: int, diagnostics: dict) -> list[dict]:
    """Apply topic/function caps first, relaxing only when no alternatives remain."""
    category_cap = max(2, (max(1, target_limit) + 3) // 4)
    selected: list[dict] = []
    deferred: list[dict] = []
    category_counts = Counter()
    topic_counts = Counter()
    for item in items:
        category = infer_functional_category(item)
        item["functional_category"] = category
        topic = normalized_update_title(item.get("topic_group") or category) or category
        violates = (
            category_counts[category] >= category_cap
            or topic_counts[topic] >= 2
            or (category == "audio_video" and category_counts[category] >= 2)
        )
        if violates:
            deferred.append(item)
            continue
        selected.append(item)
        category_counts[category] += 1
        topic_counts[topic] += 1
        if len(selected) >= target_limit:
            break
    if len(selected) < target_limit:
        selected_keys = {result_url_key(item.get("official_url") or "") for item in selected}
        for item in deferred:
            key = result_url_key(item.get("official_url") or "")
            if key in selected_keys:
                continue
            selected.append(item)
            selected_keys.add(key)
            if len(selected) >= target_limit:
                break
    diagnostics["functional_category_counts_after_cap"] = dict(
        Counter(item.get("functional_category") or "other" for item in selected)
    )
    diagnostics["functional_diversity_deferred"] = len(deferred)
    return selected


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

    preselected = apply_functional_diversity(preselected, target_limit, diagnostics)

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
        for item in selected:
            item.setdefault("highlight_reason", "")
        # Each ask_model() call (primary/topup/batch) only ever sees its own
        # slice of candidates, so more than one call can independently flag
        # is_highlight=true. Comparing candidates only ever happened within a
        # single call's payload, never across the final combined bank - the
        # old code just kept whichever nominee happened to land first in list
        # order (itself an accident of level-bucketing), which could crown a
        # minor update over a much stronger one that a later call nominated.
        # Break the tie with update_priority, the same launch/rollout-vs-side-
        # story heuristic already computed per source item in orchestrator.py.
        nominees = [item for item in selected if item.get("is_highlight")]
        pool = nominees or selected
        for item in selected:
            item["is_highlight"] = False
        best = max(
            pool,
            key=lambda entry: (
                int((entry.get("source_item") or {}).get("update_priority") or entry.get("update_priority") or 0),
                len(str(entry.get("highlight_reason") or "")),
            ),
        )
        best["is_highlight"] = True
        if not best.get("highlight_reason"):
            best["highlight_reason"] = "اختيار المودل الأعلى أولوية"

    diagnostics["sector_counts_after_balance"] = dict(Counter(item.get("sector") or "unknown" for item in selected))
    diagnostics["visible_sector_counts"] = dict(Counter(item.get("sector") or "unknown" for item in selected[:6]))
    diagnostics["company_counts_after_balance"] = dict(Counter(item.get("owner_key") or "unknown" for item in selected))
    diagnostics["visible_company_counts"] = dict(Counter(item.get("owner_key") or "unknown" for item in selected[:6]))
    diagnostics["highlight_title"] = next((item.get("title") for item in selected if item.get("is_highlight")), selected[0].get("title") if selected else "")
    return selected



# Performs the select news updates helper step.
def select_news_updates(candidates: list[dict], diagnostics: dict, *, single: bool = False) -> dict:
    """Ask GPT to select final updates from the shortlist."""
    # A single-card refill only needs one finished card.  The previous code
    # used AI_UPDATES_SINGLE_OUTPUT_LIMIT (currently 5) as the completion
    # target, so it kept running top-ups even after the endpoint only needed
    # one result.  Keep the configurable limit for full generation and make
    # the single-card contract explicit here.
    target_limit = 1 if single else max(1, AI_UPDATES_OUTPUT_LIMIT)
    configured_limit = max(1, AI_UPDATES_SINGLE_GPT_COMPACT_LIMIT if single else AI_UPDATES_GPT_COMPACT_LIMIT)
    compact_limit = min(max(configured_limit, target_limit * 5), 24 if single else 72)
    if not candidates:
        return failure_report(diagnostics.get("error") or "no_live_results", diagnostics)
    if not model_available():
        return failure_report(f"missing_{MODEL_PROVIDER}_api_key", diagnostics)

    # URLs selected by the editorial model but omitted by rewriting or final
    # validation must not be offered again during a single-card top-up.  The
    # old retry fallback re-sent the whole shortlist, causing the same rejected
    # Google result to be selected and rewritten four times.
    rejected_candidate_urls: set[str] = set()

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
        if single and not raw_selected:
            # For a single-card request, an empty editorial selection means
            # every candidate in this small retry payload was considered
            # unsuitable. Do not spend the next two calls asking about the
            # identical payload; let the orchestrator expand to the full-fetch
            # source pool instead.
            rejected_candidate_urls.update(
                result_url_key(item.get("url") or "").lower()
                for item in compact_source
                if result_url_key(item.get("url") or "")
            )
            diagnostics[f"gpt_{stage}_model_rejected_payload"] = len(compact_source)
            diagnostics["gpt_rejected_candidate_count"] = len(rejected_candidate_urls)
        # Two-call flow: selection just ran above; attach_source_items does
        # the structural checks that don't need Arabic text, then
        # rewrite_selected_items makes ONE rewrite request for the whole
        # matched batch, then finalize_selected_items runs the quality checks
        # that need the rewritten title/whats_new. See the docstring comment
        # on build_news_selection_prompt for why this is split in two calls.
        matched = attach_source_items(raw_selected, source_by_url, diagnostics)
        rewritten = rewrite_selected_items(matched, diagnostics, stage)
        selected = finalize_selected_items(rewritten, diagnostics)
        selected_urls = {
            result_url_key((item.get("official_url") or item.get("url") or "")).lower()
            for item in selected
            if item.get("official_url") or item.get("url")
        }
        rejected_in_stage = {
            result_url_key(
                (
                    item.get("official_url")
                    or (item.get("source_item") or {}).get("url")
                    or item.get("url")
                    or ""
                )
            ).lower()
            for item in matched
            if (
                item.get("official_url")
                or (item.get("source_item") or {}).get("url")
                or item.get("url")
            )
        } - selected_urls
        rejected_candidate_urls.update(key for key in rejected_in_stage if key)
        if rejected_in_stage:
            diagnostics[f"gpt_{stage}_rejected_candidate_urls"] = sorted(rejected_in_stage)
            diagnostics["gpt_rejected_candidate_count"] = len(rejected_candidate_urls)
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
                    and url_key not in rejected_candidate_urls
                    and url_key not in attempted_source_urls
                ]
                if not remaining_source:
                    remaining_source = [
                        item for item in candidates
                        if (url_key := result_url_key(item.get("url") or "").lower())
                        and url_key not in used_urls
                        and url_key not in rejected_candidate_urls
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
