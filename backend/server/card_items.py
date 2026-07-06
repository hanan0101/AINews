# This file is part of the AI newsletter system.
"""Card normalization, dedupe, and replacement safety helpers for server routes."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter

from backend.pipeline.enrichment.logos import enrich_card_visual_identity
from backend.pipeline.filtering.courses import supporting_reject_reason
from backend.pipeline.filtering.news import (
    item_story_key as backend_item_story_key,
    story_owner_key as backend_story_owner_key,
)
from backend.utils.text_normalization import cleanup_text_fields, MOJIBAKE_MARKERS_RE

SECTION_TO_CONTENT_TYPE = {
    "items": "news",
    "movies": "movie",
    "courses": "course",
}


# Performs the safe int helper step.
def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


# Performs the trace helper step.
def _trace(message):
    try:
        from backend.utils.debug_logging import trace
        trace(message)
    except Exception:
        pass

# Server role: Read a user-pinned logo URL that enrichment must preserve.
def manual_logo_override_url(item):
    """Return a user-provided logo URL that must not be replaced by auto detection."""
    item = item or {}
    manual = str(
        item.get("logo_override_url")
        or item.get("manual_logo_url")
        or ""
    ).strip()
    if not manual and item.get("logo_manual_override"):
        manual = str(item.get("logo") or item.get("provider_logo") or item.get("source_logo") or "").strip()
    if not manual:
        return ""
    if manual.startswith(("http://", "https://", "data:image", "generated/")):
        return manual
    return ""


# Server role: Apply a manual logo override before automatic enrichment.
def apply_manual_logo_override(item):
    """Keep a pasted web-image URL as the first logo candidate for the card UI."""
    manual = manual_logo_override_url(item)
    if not manual:
        return False
    existing = item.get("logo_candidates") if isinstance(item.get("logo_candidates"), list) else []
    candidates = [manual] + [str(url or "").strip() for url in existing if str(url or "").strip() and str(url or "").strip() != manual]
    item["logo"] = manual
    item["provider_logo"] = manual
    item["source_logo"] = manual
    item["logo_candidates"] = candidates
    item["logo_manual_override"] = True
    item["logo_override_url"] = manual
    item["logo_unresolved"] = False
    item["logo_resolution_reason"] = "manual_override_url"
    item["logo_detection_reason"] = "manual_override_url"
    return True


# Server role: Delegate card logo/company enrichment to the pipeline enrichment stage.
def ensure_visual_identity(item, default_type="news"):
    item = dict(item or {})
    item_type = item.get("type", default_type)
    if apply_manual_logo_override(item):
        return item
    item.update(enrich_card_visual_identity(item, item_type))
    return item


# Server role: Keep UI logo size edits within a safe visible range.
def clamp_logo_size(value, default=30):
    try:
        parsed = int(float(value))
    except Exception:
        parsed = default
    return max(18, min(78, parsed))


# Server role: Keep UI logo position edits within a safe visible range.
def clamp_logo_position(value, default=0):
    try:
        parsed = int(round(float(value)))
    except Exception:
        parsed = default
    return max(-90, min(190, parsed))


# Server role: Normalize the current card schema for UI and JSON storage.
def normalize_item(item, default_type="news"):
    item = cleanup_text_fields(item)
    item = ensure_visual_identity(item, default_type)
    raw_id = item.get("id")
    if not raw_id:
        stable_seed = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
        raw_id = f"{default_type}-{hashlib.sha1(stable_seed.encode('utf-8', errors='ignore')).hexdigest()[:12]}"
    title = str(item.get("title") or "").strip()
    url = str(item.get("url") or "").strip() or "#"
    text = str(item.get("text") or item.get("summary") or "").strip()
    item_type = str(item.get("type") or default_type)
    common = {
        "id": str(raw_id),
        "title": title,
        "text": text,
        "url": url,
        "source": str(item.get("source", "") or ""),
        "published": str(item.get("published", "") or ""),
        "story_key": str(item.get("story_key", "") or ""),
        "type": item_type,
        "status": str(item.get("status", "") or ""),
        "position": int(item.get("position", 0) or 0),
    }
    if item_type == "movie":
        normalized = {
            **common,
            "poster": str(item.get("poster") or item.get("image") or ""),
            "rating": str(item.get("rating", "") or ""),
        }
        return normalized

    logo_fields = {
        "logo": str(item.get("logo", "") or ""),
        "logo_size": clamp_logo_size(item.get("logo_size") or 30),
        "logo_x": clamp_logo_position(item.get("logo_x")) if item.get("logo_x") is not None else "",
        "logo_y": clamp_logo_position(item.get("logo_y")) if item.get("logo_y") is not None else "",
        "logo_candidates": item.get("logo_candidates", []) if isinstance(item.get("logo_candidates", []), list) else [],
        "logo_manual_override": bool(item.get("logo_manual_override", False)),
        "logo_override_url": str(item.get("logo_override_url") or ""),
        "manual_logo_url": str(item.get("manual_logo_url") or ""),
        "logo_updated_at": str(item.get("logo_updated_at") or ""),
    }
    if item_type == "course":
        return {
            **common,
            **logo_fields,
            "provider": str(item.get("provider", "") or ""),
            "platform": str(item.get("platform", "") or ""),
            "level": str(item.get("level", "") or ""),
            "certificate": str(item.get("certificate", "") or ""),
        }

    normalized = {
        **common,
        **logo_fields,
        "company": str(item.get("company", "") or ""),
        "tool_name": str(item.get("tool_name", "") or ""),
        "field_primary": str(item.get("field_primary", "") or ""),
        "use_case_bucket": str(item.get("use_case_bucket", "") or ""),
        "topic_family": str(item.get("topic_family", "") or ""),
        "sector": str(item.get("sector", "") or ""),
        "is_highlight": bool(item.get("is_highlight", False)),
        "highlight_reason": str(item.get("highlight_reason", "") or ""),
        "simple_gpt_selected": bool(item.get("simple_gpt_selected", False)),
    }
    if item_type == "news":
        ensure_server_story_identity(normalized)
    return normalized


# Returns whether is current schema item is true for the current input.
def is_current_schema_item(item, default_type="news"):
    """Accept only cards that already match the current pipeline/UI schema."""
    if not isinstance(item, dict):
        return False
    expected_type = str(default_type or "").strip()
    item_type = str(item.get("type") or "").strip()
    if expected_type and item_type != expected_type:
        return False
    if not str(item.get("id") or "").strip():
        return False
    if not str(item.get("title") or "").strip():
        return False
    url = str(item.get("url") or "").strip()
    if not url or url == "#":
        return False
    if expected_type == "news":
        if not str(item.get("text") or "").strip():
            return False
        if not str(item.get("story_key") or "").strip():
            return False
        if not item.get("simple_gpt_selected"):
            return False
    return True


# Server role: Remove duplicate cards before display or persistence.
def dedupe_store_items(items):
    """
    Keep the first occurrence of each item and remove duplicates by id, URL,
    normalized title, or very similar title/text tokens.
    """
    unique = []
    seen_ids = set()
    seen_urls = set()
    seen_titles = set()
    seen_story_keys = set()

    for item in items or []:
        if isinstance(item, dict) and item.get("type") == "news":
            ensure_server_story_identity(item)
        item_id = item.get("id")
        item_url = normalize_duplicate_text(item.get("url"))
        item_title = normalize_duplicate_text(item.get("title"))
        item_story_key = str(item.get("story_key") or "").strip()

        if item_id and item_id in seen_ids:
            continue
        if item_url and item_url in seen_urls:
            continue
        if item_title and item_title in seen_titles:
            continue
        if item_story_key and item_story_key in seen_story_keys:
            continue
        if looks_duplicate(item, unique):
            continue

        unique.append(item)
        if item_id:
            seen_ids.add(item_id)
        if item_url:
            seen_urls.add(item_url)
        if item_title:
            seen_titles.add(item_title)
        if item_story_key:
            seen_story_keys.add(item_story_key)

    return unique


# Server role: Map a news card to a UI diversity lane.
def server_news_track(item):
    topic = str(item.get("topic_family") or "").strip().lower()
    primary = str(item.get("field_primary") or item.get("domain_bucket") or "").strip().lower()
    if primary == "daily_life" or topic.startswith("daily_"):
        return "daily_life"
    if topic.startswith("culture_"):
        return "culture"
    if topic.startswith("work_"):
        return "work_life"
    if primary in {"culture", "work_life", "daily_life"}:
        return primary
    return "work_life"


# Server role: Compute visible-card diversity targets for the UI.
def balanced_server_news_track_targets(total):
    total = max(0, _safe_int(total, 0))
    if total <= 0:
        return {"culture": 0, "work_life": 0, "daily_life": 0}
    culture = min(total, max(1, round(total * 0.50)))
    work_life = min(total - culture, max(0, round(total * 0.33)))
    daily_life = max(0, total - culture - work_life)
    if total >= 3 and daily_life == 0:
        daily_life = 1
        if work_life > 1:
            work_life -= 1
        elif culture > 1:
            culture -= 1
    return {"culture": culture, "work_life": work_life, "daily_life": daily_life}


# Server role: Build a company key used only for visible-card diversity.
def server_news_company_key(item):
    return normalize_duplicate_text(
        item.get("update_owner")
        or item.get("main_company")
        or item.get("company")
        or item.get("logo_company")
        or item.get("source")
        or ""
    )


# Server role: Build a topic key used only for visible-card diversity.
def server_news_topic_key(item):
    return normalize_duplicate_text(
        item.get("topic_family")
        or item.get("use_case_bucket")
        or item.get("domain_bucket")
        or item.get("field_primary")
        or "general"
    ) or "general"


# Server role: Reorder already accepted news to diversify the visible UI.
def order_news_for_visible_diversity(items, visible_count):
    indexed = list(enumerate(items or []))
    # Server role: Sort accepted news by existing score signals.
    def score_key(pair):
        index, item = pair
        return (
            _safe_int(item.get("score"), 0),
            _safe_int(item.get("quality_score"), 0),
            _safe_int(item.get("popularity_tier"), 0),
            -index,
        )

    ordered = [item for _index, item in sorted(indexed, key=score_key, reverse=True)]
    targets = balanced_server_news_track_targets(visible_count)
    selected = []
    selected_ids = set()
    topic_counts = Counter()
    company_counts = Counter()
    max_topic = max(1, _safe_int(os.getenv("NEWS_VISIBLE_MAX_PER_TOPIC_FAMILY", "1"), 1))
    max_company = max(1, _safe_int(os.getenv("NEWS_VISIBLE_MAX_PER_COMPANY", "2"), 2))

    # Server role: Build a stable identity for visible ordering.
    def identity(item):
        return (
            str(item.get("story_key") or "").strip()
            or normalize_duplicate_text(item.get("url"))
            or normalize_duplicate_text(item.get("title"))
            or str(item.get("id") or "").strip()
        )

    # Server role: Add one card while respecting optional diversity limits.
    def try_add(item, *, enforce_track=True, enforce_company=True, enforce_topic=True):
        if len(selected) >= visible_count:
            return False
        key = identity(item)
        if key and key in selected_ids:
            return False
        track = server_news_track(item)
        if enforce_track and sum(1 for current in selected if server_news_track(current) == track) >= targets.get(track, 0):
            return False
        company = server_news_company_key(item)
        if enforce_company and company and company_counts[company] >= max_company:
            return False
        topic = server_news_topic_key(item)
        if enforce_topic and topic and topic_counts[topic] >= max_topic:
            return False
        selected.append(item)
        if key:
            selected_ids.add(key)
        if company:
            company_counts[company] += 1
        if topic:
            topic_counts[topic] += 1
        return True

    for track in ("culture", "work_life", "daily_life"):
        for item in ordered:
            if server_news_track(item) == track:
                try_add(item, enforce_track=True, enforce_company=True, enforce_topic=True)
            if len(selected) >= visible_count:
                break
    for item in ordered:
        try_add(item, enforce_track=False, enforce_company=True, enforce_topic=True)
        if len(selected) >= visible_count:
            break

    # Server role: Prefer candidates that reduce topic/company repetition.
    def relaxed_sort(item):
        return (
            topic_counts[server_news_topic_key(item)],
            company_counts[server_news_company_key(item)],
            -_safe_int(item.get("score"), 0),
            -_safe_int(item.get("quality_score"), 0),
        )

    for item in sorted(ordered, key=relaxed_sort):
        try_add(item, enforce_track=False, enforce_company=True, enforce_topic=False)
        if len(selected) >= visible_count:
            break
    for item in sorted(ordered, key=relaxed_sort):
        try_add(item, enforce_track=False, enforce_company=False, enforce_topic=False)
        if len(selected) >= visible_count:
            break

    selected_keys = {identity(item) for item in selected if identity(item)}
    remaining = [item for item in ordered if identity(item) not in selected_keys]
    _trace(
        "server news diversity order: "
        f"tracks={dict(Counter(server_news_track(item) for item in selected))} "
        f"topics={dict(Counter(server_news_topic_key(item) for item in selected))} "
        f"companies={dict(Counter(server_news_company_key(item) for item in selected))}"
    )
    return selected + remaining


# Server role: Normalize text for local duplicate checks.
def normalize_duplicate_text(value):
    value = (value or "").lower().strip()
    value = re.sub(r"https?://(www\.)?", "", value)
    value = re.sub(r"[\W_]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


# Server role: Attach pipeline-compatible story identity for UI dedupe.
def ensure_server_story_identity(item: dict) -> dict:
    """Attach the same story identity used by the modular backend filters."""
    if not isinstance(item, dict):
        return {}
    story_key = backend_item_story_key(item)
    owner = backend_story_owner_key(item)
    if story_key:
        item["story_key"] = story_key
        item["story_signature"] = story_key
    if owner and not item.get("story_owner"):
        item["story_owner"] = owner
    return {
        "story_key": story_key,
        "story_owner": owner,
        "story_product": item.get("story_product") or item.get("product_name") or item.get("tool_name") or "",
        "story_signature": story_key,
    }


# Server role: Replace JSON files safely even when Windows locks the target.
def safe_replace_json(temp_file, target_file):
    try:
        os.replace(temp_file, target_file)
    except PermissionError:
        with open(temp_file, "r", encoding="utf-8") as src:
            complete_payload = src.read()
        with open(target_file, "w", encoding="utf-8") as dst:
            dst.write(complete_payload)


# Server role: Run local duplicate checks for visible-card safety.
def looks_duplicate(candidate, existing_items):
    candidate_url = normalize_duplicate_text(candidate.get("url"))
    candidate_title = normalize_duplicate_text(candidate.get("title"))

    for item in existing_items:
        if candidate.get("id") and candidate.get("id") == item.get("id"):
            return True

        item_url = normalize_duplicate_text(item.get("url"))
        if candidate_url and item_url and candidate_url == item_url:
            return True

        item_title = normalize_duplicate_text(item.get("title"))
        if candidate_title and item_title and candidate_title == item_title:
            return True

    return False


# Server role: Reject unreadable text before showing a card in the UI.
def has_broken_display_text(value):
    text = str(value or "").strip()
    if not text:
        return True
    if MOJIBAKE_MARKERS_RE.search(text):
        return True
    if text.count("?") >= 6:
        return True
    control_count = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\t")
    if control_count:
        return True
    arabic = len(re.findall(r"[\u0600-\u06FF]", text))
    cyrillic = len(re.findall(r"[\u0400-\u04FF]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cyrillic >= 6 and arabic == 0:
        return True
    if arabic >= 5 and latin >= 25 and not re.search(r"\([A-Za-z0-9 .+\-]{2,45}\)", text):
        return True
    return False


# Server role: Validate only display safety and duplicate guards for refills.
def validate_replacement_candidate(candidate, section, current_items, allow_seen=False, allow_curated_json=False):
    if not isinstance(candidate, dict):
        return False, "invalid_candidate"
    candidate = normalize_item(candidate, SECTION_TO_CONTENT_TYPE.get(section, "news"))
    title = candidate.get("title", "").strip()
    url = candidate.get("url", "").strip()
    source = candidate.get("source", "").strip()
    text = candidate.get("text", "").strip()
    if not title or not url or url == "#":
        return False, "missing_title_or_url"
    if section == "items" and not text:
        return False, "missing_text"
    if looks_duplicate(candidate, current_items):
        return False, "duplicate_candidate"
    if section == "items" and not source:
        return False, "missing_source"

    if section == "courses":
        reject_reason = supporting_reject_reason(candidate, "course")
        if reject_reason:
            return False, reject_reason

    if section == "movies":
        reject_reason = supporting_reject_reason(candidate, "movie")
        if reject_reason:
            return False, reject_reason

    return True, ""

