"""News card assembly, validation, and persistence."""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter

from backend.config.settings import (
    BACKUP_NEWS_COUNT,
    DISPLAY_COUNTS,
    NEWS_FETCH_STATE_FILE,
    NEWS_JSON_FILE,
    NEWS_SECTORS,
    SAVE_NEWS_BACKUP_FROM_SELECTION,
    clean_text,
    env_int,
    load_json,
    memory_url_key,
    normalized_text,
    safe_write_json,
    source_domain,
    utc_now,
)
from backend.services.gemini_limiter import evaluate_run
from backend.pipeline.enrichment.logos import NEWS_SOURCE_LOGO_KEYS, company_logo_candidates, logo_name_key
from backend.pipeline.filtering.news import save_news_memory
from backend.pipeline.filtering.level_balancing import (
    COURSES_PER_LEVEL,
    NEWS_PER_LEVEL,
    build_level_bank,
    build_recommended_view,
    classify_course_item,
    classify_news_item,
)

REJECTION_CARD_PATTERNS = (
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

def stable_update_id(update: dict, source_item: dict | None = None) -> str:
    """Create a stable card id from the selected story identity."""
    source_item = source_item or {}
    raw = "|".join(str(value or "").strip() for value in (update.get("official_url"), update.get("title"), update.get("tool_name"), source_item.get("title")))
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]


# Performs the update company name helper step.

def update_company_name(update: dict, source_item: dict | None = None) -> str:
    source_item = source_item or {}
    for value in (update.get("company_name"), update.get("company"), update.get("tool_name")):
        clean = re.sub(r"\s+", " ", str(value or "")).strip()
        key = logo_name_key(clean)
        if clean and key not in {"ai", "app", "tool", "platform", "assistant"} and key not in NEWS_SOURCE_LOGO_KEYS:
            return clean
    domain = source_domain(source_item.get("url") or update.get("official_url") or "")
    return (domain.split(".")[-2].replace("-", " ").title() if "." in domain else domain.title()) or "AI"


# Performs the sector to track helper step.

def sector_to_track(sector: str = "", bucket: str = "") -> tuple[str, str]:
    """Map English sectors back to the old UI's track/topic fields."""
    text = f"{sector} {bucket}".lower()
    if sector in {"museums", "heritage", "libraries"}:
        return "culture", "culture_research_documents"
    if sector in {"films", "music", "literature", "theater"}:
        return "culture", "culture_language_audio"
    if sector in {"fashion", "visual_arts", "architecture", "cooking"}:
        return "culture", "culture_design_visual"
    if sector in {"mental_health", "physical_health", "ai_education_training_daily_tasks"}:
        return "daily_life", "daily_personal_organization"
    if sector == "work_productivity":
        return "work_life", "work_automation_projects"
    if "daily" in text or "shopping" in text or "travel" in text:
        return "daily_life", "daily_personal_organization"
    if "design" in text or "visual" in text or "fashion" in text:
        return "culture", "culture_design_visual"
    if "workflow" in text or "automation" in text:
        return "work_life", "work_automation_projects"
    return "work_life", "work_documents_reports"


# Performs the news item from update helper step.

def news_item_from_update(update: dict, index: int) -> dict:
    """Convert one GPT-selected update into the compact UI card schema."""
    source_item = update.get("source_item") if isinstance(update.get("source_item"), dict) else {}
    source_url = update.get("official_url") or source_item.get("url") or "#"
    source_domain_name = source_item.get("source_domain") or source_domain(source_url)
    company = update_company_name(update, source_item)
    logo_candidates = company_logo_candidates(company, source_url)
    logo_for_card = logo_candidates[0] if logo_candidates else ""
    title = clean_text(update.get("title") or update.get("tool_name") or source_item.get("title") or "")
    text = clean_text(update.get("whats_new") or source_item.get("content") or "")
    source_title = clean_text(update.get("source_title") or source_item.get("title") or title)
    sector = update.get("sector") if update.get("sector") in NEWS_SECTORS else source_item.get("sector") or "ai_education_training_daily_tasks"
    field_primary, use_case_bucket = sector_to_track(sector, update.get("source_bucket") or source_item.get("bucket") or "")
    item_id = stable_update_id(update, source_item)
    story_key = hashlib.sha1(f"{company}|{update.get('tool_name')}|{source_title}".lower().encode("utf-8", errors="ignore")).hexdigest()[:24]
    return {
        "id": item_id,
        "title": title,
        "text": text,
        "url": source_url,
        "source": source_domain_name or source_item.get("source") or "Live Search",
        "published": update.get("published_date") or source_item.get("published_date") or source_item.get("published_raw") or "",
        "company": company,
        "logo": logo_for_card,
        "logo_size": 30,
        "logo_candidates": list(dict.fromkeys(str(url or "").strip() for url in logo_candidates if str(url or "").strip()))[:3],
        "tool_name": clean_text(update.get("tool_name") or ""),
        # Level-balanced newsletter change: preserve GPT's solution/use-case
        # classification on the card so the bank builder and frontend filters
        # can work without asking GPT again.
        "solution_provided": clean_text(update.get("solution_provided") or ""),
        "main_user_benefit": clean_text(update.get("main_user_benefit") or ""),
        "likely_user": clean_text(update.get("likely_user") or ""),
        "level": clean_text(update.get("level") or ""),
        "topic_group": clean_text(update.get("topic_group") or ""),
        "audience_fit": clean_text(update.get("audience_fit") or ""),
        "should_simplify": bool(update.get("should_simplify")),
        "classification_reason": clean_text(update.get("classification_reason") or ""),
        "field_primary": field_primary,
        "use_case_bucket": use_case_bucket,
        "topic_family": use_case_bucket,
        "sector": sector,
        "is_highlight": bool(update.get("is_highlight")),
        "highlight_reason": clean_text(update.get("highlight_reason") or ""),
        "simple_gpt_selected": True,
        "story_key": story_key,
        "type": "news",
        "status": "display" if index <= DISPLAY_COUNTS["items"] else "backup",
        "position": index,
    }


# Performs the news items from updates helper step.

def news_items_from_updates(updates: list[dict]) -> list[dict]:
    """Convert all selected updates and keep only valid UI cards."""
    return [news_item_from_update(update, index) for index, update in enumerate(updates or [], start=1)]


# Performs the rejection card reason helper step.

def rejection_card_reason(item: dict) -> str:
    """Detect model rejection notes that should never become newsletter cards."""
    text = clean_text(
        " ".join(
            str(item.get(key) or "")
            for key in ("title", "text", "tool_name", "company", "highlight_reason")
        )
    )
    if not text:
        return ""
    for pattern in REJECTION_CARD_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return pattern
    return ""


# Prepares filter rejection news items so downstream stages receive consistent data.

def filter_rejection_news_items(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Remove invalid cards before writing news.json."""
    kept = []
    removed = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if not clean_text(item.get("text") or ""):
            removed.append({
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "reason": "empty_news_text",
            })
            continue
        reason = rejection_card_reason(item)
        if reason:
            removed.append({
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "reason": "rejection_text_in_card",
                "match": reason,
            })
            continue
        kept.append(item)
    return kept, removed


# Prepares dedupe news items so downstream stages receive consistent data.

def dedupe_news_items(items: list[dict]) -> tuple[list[dict], int]:
    """Remove literal duplicate cards before writing runtime/news.json."""
    seen_urls = set()
    seen_titles = set()
    seen_stories = set()
    unique = []
    removed = 0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url_key = memory_url_key(item.get("url") or item.get("original_url") or item.get("source_url") or "")
        title_key = normalized_text(item.get("title") or item.get("original_title") or "")
        story_key = str(item.get("story_key") or item.get("story_signature") or "").strip().lower()
        if (url_key and url_key in seen_urls) or (title_key and title_key in seen_titles) or (story_key and story_key in seen_stories):
            removed += 1
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        if story_key:
            seen_stories.add(story_key)
        unique.append(item)

    for index, item in enumerate(unique, start=1):
        item["position"] = index
        item["status"] = "display" if index <= DISPLAY_COUNTS["items"] else "backup"
    return unique, removed


# Saves write news fetch state to the configured output or state store.

def write_news_fetch_state(performance: dict, items: list[dict]) -> None:
    """Save lightweight fetch diagnostics for the next UI/status read."""
    """Persist timing and diversity diagnostics for the UI progress panel."""
    state = load_json(NEWS_FETCH_STATE_FILE, {})
    visible = items[:DISPLAY_COUNTS["items"]]
    state["last_run_performance"] = {
        "generated_at": utc_now().isoformat(),
        "source": "ai_update_pipeline",
        "performance": performance,
        "diversity": {
            "domain_counts": dict(Counter(item.get("field_primary") or "unknown" for item in visible)),
            "sector_counts": dict(Counter(item.get("sector") or item.get("news_sector") or "unknown" for item in visible)),
            "highlight": next(({
                "title": item.get("title"),
                "sector": item.get("sector") or item.get("news_sector"),
                "reason": item.get("highlight_reason"),
            } for item in visible if item.get("is_highlight")), {}),
            "target_counts": {
                "visible": DISPLAY_COUNTS["items"],
                "backup": len(items[DISPLAY_COUNTS["items"]:]),
                "total": len(items),
            },
        },
    }
    safe_write_json(NEWS_FETCH_STATE_FILE, state)


# Saves save news report to the configured output or state store.

def save_news_report(report: dict, performance: dict) -> bool:
    """Save the run report that explains what happened during Generate."""
    """Save selected news plus backups to runtime/news.json and Qdrant memory."""
    backup_target = BACKUP_NEWS_COUNT if SAVE_NEWS_BACKUP_FROM_SELECTION else 0
    required_total = DISPLAY_COUNTS["items"] + backup_target
    # Flexible save gate: target the configured full bank, but allow a smaller
    # visible draft when the model returns useful items and a background top-up
    # can continue the work.
    minimum_save_total = max(1, min(required_total, env_int("AI_UPDATES_MIN_NEWS_SAVE_COUNT", "1")))
    allow_under_min_partial = os.getenv("AI_UPDATES_ALLOW_UNDER_MIN_PARTIAL_SAVE", "1").strip().lower() in {
        "1", "true", "yes", "on"
    }
    under_min_partial_min = max(1, env_int("AI_UPDATES_UNDER_MIN_PARTIAL_MIN", "1"))
    updates = list(report.get("latest_updates") or [])[:required_total]
    items = news_items_from_updates(updates)
    items, removed_rejection_cards = filter_rejection_news_items(items)
    if removed_rejection_cards:
        performance["news_rejection_cards_removed_before_save"] = removed_rejection_cards
        print(f"[AI Updates] removed rejection-text news cards before save: {len(removed_rejection_cards)}", flush=True)
    items, removed_duplicates = dedupe_news_items(items)
    if removed_duplicates:
        performance["news_duplicates_removed_before_save"] = removed_duplicates
        print(f"[AI Updates] removed duplicate selected news before save: {removed_duplicates}", flush=True)
    existing = load_json(NEWS_JSON_FILE, {})
    processing_result = {"successful": [{"result": item} for item in items], "failed": []}
    run_evaluation = evaluate_run(processing_result, min_required=minimum_save_total)
    if (
        len(items) < minimum_save_total
        and run_evaluation.get("status") == "insufficient"
        and (not allow_under_min_partial or len(items) < under_min_partial_min)
    ):
        performance["incomplete_news_bank"] = True
        performance["partial_news_selected"] = len(items)
        performance["partial_news_required"] = required_total
        if isinstance(report, dict):
            report["success"] = False
            report["error"] = "incomplete_news_bank"
            diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), dict) else {}
            diagnostics["incomplete_news_bank"] = {
                "selected": len(items),
                "minimum_required": minimum_save_total,
                "target": required_total,
                "reason": "selected_news_below_flexible_save_minimum",
            }
            report["diagnostics"] = diagnostics
        print(f"[AI Updates] news.json skipped: selected={len(items)} minimum={minimum_save_total} target={required_total}", flush=True)
        return False
    if len(items) < minimum_save_total:
        performance["partial_news_save"] = True
        performance["under_min_partial_news_save"] = True
        performance["background_topup_requested"] = True
        performance["partial_news_selected"] = len(items)
        performance["partial_news_required"] = required_total
        performance["partial_news_minimum"] = minimum_save_total
        performance["partial_news_warning"] = run_evaluation.get("warning") or ""
        if isinstance(report, dict):
            report["success"] = True
            report["partial"] = True
            report["needs_background_topup"] = True
            report["warning"] = "under_min_partial_news_bank"
            diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), dict) else {}
            diagnostics["partial_news_bank"] = {
                "selected": len(items),
                "minimum_required": minimum_save_total,
                "target": required_total,
                "status": run_evaluation.get("status"),
                "warning": run_evaluation.get("warning") or "",
                "background_topup_requested": True,
            }
            report["diagnostics"] = diagnostics
        print(
            f"[AI Updates] news.json partial save accepted: selected={len(items)} "
            f"minimum={minimum_save_total} target={required_total}",
            flush=True,
        )
    if len(items) < required_total:
        performance["partial_news_save"] = True
        performance["partial_news_selected"] = len(items)
        performance["partial_news_required"] = required_total
        performance["partial_news_minimum"] = minimum_save_total
        print(
            f"[AI Updates] news.json partial save: selected={len(items)} "
            f"visible={DISPLAY_COUNTS['items']} backup={max(0, len(items) - DISPLAY_COUNTS['items'])} "
            f"target={required_total}",
            flush=True,
        )
    # Level-balanced newsletter change: build the full news bank first,
    # then save the recommended 4-card mixed view into the legacy `items` field
    # so older server/frontend code keeps working.
    news_per_level = max(NEWS_PER_LEVEL, math.ceil(required_total / 3))
    news_bank, bank_items, news_bank_notes = build_level_bank(items, news_per_level, classify_news_item)
    performance["news_saved_count"] = len(bank_items)

    # Regression guard (2026-07-12, hit in production: a background top-up
    # run whose Exa calls failed with "exa_no_credits" still unconditionally
    # overwrote a healthy 8-item saved news.json with a worse 3-item one,
    # since this function never looked at what was already saved before
    # writing). Never let a run save fewer news items than what's already
    # live - keep the existing news content and only refresh non-news fields
    # (movies/courses/etc. are saved through their own paths, not this one).
    existing_metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
    existing_news_total = int(existing_metadata.get("news_total_count") or 0)
    if existing_news_total and len(bank_items) < existing_news_total:
        performance["news_save_skipped_worse_than_existing"] = True
        performance["news_save_skipped_existing_count"] = existing_news_total
        performance["news_save_skipped_new_count"] = len(bank_items)
        print(
            f"[AI Updates] news.json save skipped: new run has {len(bank_items)} items, "
            f"existing saved news.json already has {existing_news_total} - keeping existing.",
            flush=True,
        )
        performance["semantic_memory_saved"] = save_news_memory(bank_items, performance)
        write_news_fetch_state(performance, bank_items)
        return True
    recommended_view = build_recommended_view(
        news_bank,
        existing.get("courses_bank") if isinstance(existing.get("courses_bank"), dict) else {},
        existing.get("movies", []) if isinstance(existing.get("movies"), list) else [],
    )
    visible_news = recommended_view.get("news") or bank_items[:DISPLAY_COUNTS["items"]]
    hidden = [item for item in bank_items if item.get("id") not in {entry.get("id") for entry in visible_news}]
    metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
    metadata.update({
        "source": "ai_update_pipeline",
        "generated_at": utc_now().isoformat(),
        "display_count": DISPLAY_COUNTS["items"],
        "backup_count": len(hidden),
        "backup_from_large_scan_enabled": bool(SAVE_NEWS_BACKUP_FROM_SELECTION),
        "news_total_count": len(bank_items),
        "level_balancing_enabled": True,
        "news_target_per_level": news_per_level,
        "news_actual_per_level": news_per_level,
        "courses_target_per_level": COURSES_PER_LEVEL,
        "default_news_view_count": 4,
        "default_courses_view_count": 2,
        "news_bank_notes": news_bank_notes,
        "ai_updates_performance": performance,
    })
    payload = {
        "items": visible_news[:DISPLAY_COUNTS["items"]],
        "backup_news": hidden,
        "news_bank": news_bank,
        "recommended_view": {
            **(existing.get("recommended_view") if isinstance(existing.get("recommended_view"), dict) else {}),
            "news": visible_news[:DISPLAY_COUNTS["items"]],
        },
        "movies": existing.get("movies", []) if isinstance(existing.get("movies", []), list) else [],
        "courses": existing.get("courses", []) if isinstance(existing.get("courses", []), list) else [],
        "courses_bank": existing.get("courses_bank") if isinstance(existing.get("courses_bank"), dict) else {},
        "feature_mode": existing.get("feature_mode") or "course",
        "template": existing.get("template") or {},
        "metadata": {
            "source": metadata.get("source"),
            "generated_at": metadata.get("generated_at"),
            "display_count": metadata.get("display_count"),
            "backup_count": metadata.get("backup_count"),
            "backup_from_large_scan_enabled": metadata.get("backup_from_large_scan_enabled"),
            "news_total_count": metadata.get("news_total_count"),
            "level_balancing_enabled": metadata.get("level_balancing_enabled"),
            "news_target_per_level": metadata.get("news_target_per_level"),
            "news_actual_per_level": metadata.get("news_actual_per_level"),
            "courses_target_per_level": metadata.get("courses_target_per_level"),
            "default_news_view_count": metadata.get("default_news_view_count"),
            "default_courses_view_count": metadata.get("default_courses_view_count"),
            "news_bank_notes": metadata.get("news_bank_notes"),
        },
    }
    safe_write_json(NEWS_JSON_FILE, payload)
    performance["semantic_memory_saved"] = save_news_memory(bank_items, performance)
    write_news_fetch_state(performance, bank_items)
    print(f"[AI Updates] Saved news.json visible={DISPLAY_COUNTS['items']} backup={len(hidden)} total={len(bank_items)}", flush=True)
    return True


# Builds build supporting content for the next pipeline or API step.

__all__ = [
    "dedupe_news_items",
    "filter_rejection_news_items",
    "news_item_from_update",
    "news_items_from_updates",
    "rejection_card_reason",
    "save_news_report",
    "sector_to_track",
    "stable_update_id",
    "update_company_name",
    "write_news_fetch_state",
]
