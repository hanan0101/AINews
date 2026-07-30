# This file is part of the AI newsletter system.
"""
Main orchestrator for the AI update system.

Pipeline order:
1. Fetch live candidates.
2. Filter, dedupe, and check semantic memory.
3. Ask the model to select and rewrite.
4. Enrich cards and save data/news/runtime/news.json.
5. Refresh courses and movies when this is a full Generate run.
"""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from collections import Counter, defaultdict

from backend.config.settings import (
    AI_UPDATES_GPT_SHORTLIST_LIMIT,
    AI_UPDATES_LOOKBACK_DAYS,
    AI_UPDATES_SCAN_POOL_LIMIT,
    DAEMON_ENABLED,
    DAEMON_INTERVAL_SECONDS,
    DISPLAY_COUNTS,
    CANDIDATE_AUDIT_FILE,
    NEWS_JSON_FILE,
    NEWS_SECTORS,
    SUPPORTING_COURSE_FETCH_POOL,
    SUPPORTING_MOVIE_FETCH_POOL,
    TOTAL_NEWS_TARGET,
    QUERY_RESULTS_FILE,
    clean_text,
    env_int,
    env_bool,
    load_json,
    normalized_text,
    recency_cutoff_query_token,
    safe_write_json,
    update_json_file,
    source_domain,
    utc_now,
)
from backend.pipeline.enrichment.content.courses.pipeline import (
    apply_supporting_content,
    build_supporting_content,
    refresh_supporting_content,
)
from backend.pipeline.enrichment.content.news.pipeline import (
    news_items_from_updates,
    save_news_report,
    write_news_fetch_state,
)
from backend.pipeline.fetching.content.courses.discovery import fetch_course_candidates
from backend.pipeline.filtering.content.courses.rules import filter_supporting_candidates, normalize_level
from backend.pipeline.modeling.content.courses.model import select_supporting_content_cards
from backend.pipeline.modeling.model_client import (
    MODEL_FLASH_MODEL,
    MODEL_PROVIDER,
    model_available,
    model_quota_remaining,
)
from backend.pipeline.fetching.content.films.discovery import fetch_movie_candidates
from backend.pipeline.fetching.content.news.fetch import fetch_news_candidates
from backend.pipeline.fetching.content.news.normalization import flag_weak_sectors, update_sector_terms
from backend.pipeline.tool_discovery.tools_aware import apply_tool_activity_signal
from backend.pipeline.filtering.content.news.rules import filter_news_candidates, items_same_story
from backend.pipeline.modeling.content.news.model import save_model_report, select_news_updates
from backend.pipeline.modeling.content.news.selection import balance_for_diversity
from backend.logging.pipeline_logging import (
    file_status,
    log_event,
    new_run_id,
    set_run_context,
    summarize_items,
    timed_stage,
)


NEWS_FETCH_CYCLES = max(1, min(2, env_int("AI_UPDATES_NEWS_FETCH_CYCLES", "2")))
OFFICIAL_FIRST_FALLBACK_PERCENT = max(0, min(100, env_int("AI_UPDATES_OFFICIAL_FIRST_FALLBACK_PERCENT", "30")))
OFFICIAL_FIRST_MIN_PRIMARY = max(1, env_int("AI_UPDATES_OFFICIAL_FIRST_MIN_PRIMARY", "20"))


# Performs the performance helper step.
def _performance(
    run_started: float,
    fetch_seconds: float,
    gpt_seconds: float,
    save_seconds: float,
    diagnostics: dict,
    report: dict,
    *,
    source_fetch_seconds: float | None = None,
    filter_seconds: float | None = None,
) -> dict:
    """Build the performance payload shown in the old UI progress timeline."""
    performance = {
        "total_seconds": round(time.time() - run_started, 2),
        "fetch_seconds": round(fetch_seconds, 2),
        "source_fetch_seconds": round(source_fetch_seconds if source_fetch_seconds is not None else fetch_seconds, 2),
        "filter_seconds": round(filter_seconds or 0.0, 2),
        "gpt_seconds": round(gpt_seconds, 2),
        "save_seconds": round(save_seconds, 2),
        "raw_candidates": diagnostics.get("raw_results", 0),
        "valid_candidates": diagnostics.get("unique_results", 0),
        "selected_count": len(report.get("latest_updates") or []),
        "saved_count": len(report.get("latest_updates") or []),
        "queries": diagnostics.get("queries", 0),
        "exa_queries": diagnostics.get("exa_queries", 0),
        "searxng_queries": diagnostics.get("searxng_queries", 0),
        "exa_raw": diagnostics.get("exa_raw", 0),
        "searxng_raw": diagnostics.get("searxng_raw", 0),
        "exa_seconds": diagnostics.get("exa_seconds", 0),
        "searxng_seconds": diagnostics.get("searxng_seconds", 0),
        "parallel_fetch_seconds": diagnostics.get("parallel_fetch_seconds", 0),
        "source_failures": diagnostics.get("source_failures", {}),
        "source_candidate_counts": diagnostics.get("source_candidate_counts", {}),
        "source_quality_mode": diagnostics.get("source_quality_mode", "best_pool"),
        "cutoff_date": diagnostics.get("cutoff_date") or recency_cutoff_query_token(),
        "lookback_days": AI_UPDATES_LOOKBACK_DAYS,
        "memory_enabled": diagnostics.get("memory_enabled"),
        "semantic_memory_enabled": diagnostics.get("semantic_memory_enabled"),
        "memory_status": diagnostics.get("memory_status"),
        "memory_filter_status": diagnostics.get("memory_filter_status"),
        "memory_exact_available": diagnostics.get("memory_exact_available"),
        "memory_exact_entries": diagnostics.get("memory_exact_entries", 0),
        "memory_exact_skipped": diagnostics.get("memory_exact_skipped", 0),
        "semantic_memory_available": diagnostics.get("semantic_memory_available"),
        "semantic_memory_requested": diagnostics.get("semantic_memory_requested", 0),
        "semantic_memory_checked": diagnostics.get("semantic_memory_checked", 0),
        "semantic_memory_skipped": diagnostics.get("semantic_memory_skipped", 0),
        "memory_save_status": diagnostics.get("memory_save_status"),
        "memory_save_count": diagnostics.get("memory_save_count", 0),
        "memory_save_error": diagnostics.get("memory_save_error"),
    }
    large_scan = diagnostics.get("large_scan") if isinstance(diagnostics.get("large_scan"), dict) else {}
    performance["large_scan"] = large_scan
    performance["scan_pool_count"] = large_scan.get("scan_pool_count", 0)
    performance["gpt_shortlist_count"] = large_scan.get("gpt_shortlist_count", 0)
    performance["stage_durations"] = [
        {"key": "source_fetch", "label": "Source fetch", "seconds": performance["source_fetch_seconds"]},
        {"key": "quality_filter", "label": "Quality filters and memory", "seconds": performance["filter_seconds"]},
        {"key": "ai_model", "label": "AI model selection", "seconds": performance["gpt_seconds"]},
        {"key": "save", "label": "Save output", "seconds": performance["save_seconds"]},
    ]
    return performance


# Performs the notify helper step.
def _notify(progress_callback, message: str) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(message)
    except Exception:
        pass


# Performs the candidate url key helper step.
def _candidate_url_key(value: str = "") -> str:
    return str(value or "").strip().rstrip("/").lower()


# Performs the candidate identity helper step.
def _candidate_identity(item: dict) -> str:
    """Stable key for merging candidates collected across two fetch cycles."""
    url_key = _candidate_url_key(item.get("url") or item.get("official_url") or "")
    if url_key:
        return f"url:{url_key}"
    title = normalized_text(item.get("title") or "")
    domain = source_domain(item.get("url") or "")
    return f"title:{domain}:{title}" if title else ""


# Performs the merge candidate pools helper step.
def _merge_candidate_pools(*pools: list[dict]) -> list[dict]:
    """Merge cycle 1 + cycle 2 candidates without duplicating the same URL/story."""
    merged = []
    seen = set()
    for pool in pools:
        for item in pool or []:
            if not isinstance(item, dict):
                continue
            key = _candidate_identity(item)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(item)
    return merged


# Performs the merge cycle diagnostics helper step.
def _merge_cycle_diagnostics(base: dict, cycle_diagnostics: dict, cycle: int, candidate_total: int) -> dict:
    """Combine diagnostics from up to two fetch cycles for reports/audits."""
    if not base:
        base = deepcopy(cycle_diagnostics or {})
    else:
        cycle_diagnostics = cycle_diagnostics or {}
        for key in ("raw_results", "queries"):
            base[key] = int(base.get(key) or 0) + int(cycle_diagnostics.get(key) or 0)
        base["unique_results"] = candidate_total
        base["parallel_fetch_seconds"] = round(
            float(base.get("parallel_fetch_seconds") or 0) + float(cycle_diagnostics.get("parallel_fetch_seconds") or 0),
            2,
        )
        base_failures = base.get("source_failures") if isinstance(base.get("source_failures"), dict) else {}
        cycle_failures = cycle_diagnostics.get("source_failures") if isinstance(cycle_diagnostics.get("source_failures"), dict) else {}
        base["source_failures"] = {**base_failures, **cycle_failures}
        base_sources = base.get("source_diagnostics") if isinstance(base.get("source_diagnostics"), dict) else {}
        cycle_sources = cycle_diagnostics.get("source_diagnostics") if isinstance(cycle_diagnostics.get("source_diagnostics"), dict) else {}
        for source, source_diag in cycle_sources.items():
            if not isinstance(source_diag, dict):
                continue
            current = base_sources.setdefault(source, {"query_results": [], "errors": []})
            current["queries"] = int(current.get("queries") or 0) + int(source_diag.get("queries") or 0)
            current["raw_results"] = int(current.get("raw_results") or 0) + int(source_diag.get("raw_results") or 0)
            current["unique_results"] = int(current.get("unique_results") or 0) + int(source_diag.get("unique_results") or 0)
            current["seconds"] = round(float(current.get("seconds") or 0) + float(source_diag.get("seconds") or 0), 2)
            current["errors"] = list(current.get("errors") or []) + list(source_diag.get("errors") or [])
            current["query_results"] = list(current.get("query_results") or []) + list(source_diag.get("query_results") or [])
            current["error"] = current.get("error") or source_diag.get("error")
        base["source_diagnostics"] = base_sources
        base["tool_discovery"] = cycle_diagnostics.get("tool_discovery") or base.get("tool_discovery")
        base["query_mix_counts"] = cycle_diagnostics.get("query_mix_counts") or base.get("query_mix_counts")
        base["tool_group_counts"] = cycle_diagnostics.get("tool_group_counts") or base.get("tool_group_counts")
    cycles = list(base.get("fetch_cycles") or [])
    cycles.append({
        "cycle": cycle,
        "raw_results": (cycle_diagnostics or {}).get("raw_results", 0),
        "unique_results": (cycle_diagnostics or {}).get("unique_results", 0),
        "merged_unique_results": candidate_total,
        "queries": (cycle_diagnostics or {}).get("queries", 0),
    })
    base["fetch_cycles"] = cycles
    base["fetch_cycle_count"] = len(cycles)
    base["unique_results"] = candidate_total
    return base


# Performs the candidate audit reason helper step.
def _candidate_audit_reason(item: dict, selected_company_counts: Counter, selected_sector_counts: Counter) -> str:
    text = normalized_text(
        " ".join(str(item.get(key) or "") for key in ("title", "content", "summary", "source_query"))
    )
    owner = str(item.get("owner_key") or item.get("company_name") or item.get("company") or source_domain(item.get("url") or "") or "").lower()
    sector = str(item.get("sector") or item.get("sector_hint") or item.get("tool_sector_hint") or "")
    domain = source_domain(item.get("url") or "")
    if any(term in text for term in ("best ai", "best tools", "top ai", "alternatives", "roundup", "guide", "review", "i tried")):
        return "likely_rejected_listicle_review_or_roundup"
    if selected_company_counts.get(owner, 0) >= 2:
        return "likely_rejected_company_diversity_limit"
    if sector and selected_sector_counts.get(sector, 0) >= 2:
        return "likely_rejected_sector_diversity_or_lower_priority"
    if item.get("query_mix") == "broad":
        return "likely_rejected_broad_result_lower_priority"
    if domain in {"medium.com", "substack.com"} or item.get("source_type") in {"unknown", ""}:
        return "likely_rejected_source_quality_or_unclear_update"
    return "not_selected_by_model"


# Saves save candidate audit to the configured output or state store.
def save_candidate_audit(candidates: list[dict], report: dict, diagnostics: dict) -> None:
    """Persist the GPT shortlist with selected/rejected status for review."""
    selected = list(report.get("latest_updates") or [])
    selected_urls = {_candidate_url_key(item.get("official_url") or "") for item in selected}
    selected_company_counts = Counter(
        str(item.get("owner_key") or item.get("company_name") or item.get("company") or "").lower()
        for item in selected
    )
    selected_sector_counts = Counter(str(item.get("sector") or "") for item in selected)
    rows = []
    for index, item in enumerate(candidates or [], start=1):
        url_key = _candidate_url_key(item.get("url") or "")
        is_selected = url_key in selected_urls
        rows.append({
            "rank": index,
            "status": "selected" if is_selected else "rejected",
            "reason": "selected_by_model" if is_selected else _candidate_audit_reason(item, selected_company_counts, selected_sector_counts),
            "title": item.get("title") or "",
            # Kept alongside title/metadata so this file is a faithful copy of
            # what compact_model_candidate() actually sent the selection model
            # (selection.py:535-557) - lets a saved run be replayed against a
            # different model for a fair side-by-side comparison.
            "content": clean_text(item.get("content") or item.get("summary") or "")[:700],
            "company": item.get("company") or item.get("company_name") or item.get("owner_key") or "",
            "tool": item.get("tool") or item.get("tool_name") or "",
            "source_domain": item.get("source_domain") or source_domain(item.get("url") or ""),
            "fetch_source": item.get("fetch_source") or "",
            "source_lane": candidate_source_lane(item),
            "date_confidence": item.get("date_confidence") or item.get("verified_date_confidence") or "",
            "official_domain": item.get("official_domain") or "",
            "trusted_media_name": item.get("trusted_media_name") or "",
            "trusted_media_domain": item.get("trusted_media_domain") or "",
            "acceptance_reason": item.get("acceptance_reason") or "",
            "query": item.get("source_query") or item.get("query") or "",
            "query_mix": item.get("query_mix") or "",
            "update_priority": item.get("update_priority") or 0,
            "product_update_signal": item.get("product_update_signal") or "",
            "sector": item.get("sector") or item.get("sector_hint") or "",
            "url": item.get("url") or "",
        })
    payload = {
        "timestamp": utc_now().isoformat(),
        "report_timestamp": report.get("timestamp"),
        "total_candidates_sent_to_model": len(candidates or []),
        "selected_count": len(selected),
        "rejected_count": max(0, len(candidates or []) - len(selected_urls)),
        "diagnostics": {
            "gpt_payload_candidates": diagnostics.get("gpt_payload_candidates"),
            "same_story_model_updates_removed": diagnostics.get("same_story_model_updates_removed"),
            "company_counts_after_balance": diagnostics.get("company_counts_after_balance"),
            "sector_counts_after_balance": diagnostics.get("sector_counts_after_balance"),
            "gpt_shortlist_source_lane_counts": (diagnostics.get("large_scan") or {}).get("gpt_shortlist_source_lane_counts"),
        },
        "candidates": rows,
    }
    update_json_file(CANDIDATE_AUDIT_FILE, lambda current: current.update(payload))
    log_event("candidate_audit.saved", path=str(CANDIDATE_AUDIT_FILE), candidates=len(rows), selected=len(selected))


# Saves save query results audit to the configured output or state store.
def save_query_results_audit(diagnostics: dict) -> None:
    """Persist per-query source results for debugging search behavior."""
    source_diagnostics = diagnostics.get("source_diagnostics") if isinstance(diagnostics.get("source_diagnostics"), dict) else {}
    sources = {}
    all_queries = []
    for source, source_diag in source_diagnostics.items():
        if not isinstance(source_diag, dict):
            continue
        query_results = list(source_diag.get("query_results") or [])
        sources[source] = {
            "queries": source_diag.get("queries", len(query_results)),
            "raw_results": source_diag.get("raw_results", 0),
            "unique_results": source_diag.get("unique_results", 0),
            "official_accepted_count": sum(int(item.get("official_accepted_count") or 0) for item in query_results if isinstance(item, dict)),
            "trusted_media_accepted_count": sum(int(item.get("trusted_media_accepted_count") or 0) for item in query_results if isinstance(item, dict)),
            "fallback_accepted_count": sum(int(item.get("fallback_accepted_count") or 0) for item in query_results if isinstance(item, dict)),
            "source_lane_counts": dict(Counter(str(result.get("source_lane") or "unknown") for result in query_results if isinstance(result, dict))),
            "seconds": source_diag.get("seconds", 0),
            "error": source_diag.get("error"),
            "errors": list(source_diag.get("errors") or [])[:50],
            "query_results": query_results,
        }
        all_queries.extend(query_results)
    payload = {
        "timestamp": utc_now().isoformat(),
        "cutoff_date": diagnostics.get("cutoff_date"),
        "lookback_days": diagnostics.get("lookback_days"),
        "total_queries": diagnostics.get("queries", len(all_queries)),
        "raw_results": diagnostics.get("raw_results", 0),
        "unique_results": diagnostics.get("unique_results", 0),
        "source_failures": diagnostics.get("source_failures", {}),
        "sources": sources,
        "queries": all_queries,
    }
    safe_write_json(QUERY_RESULTS_FILE, payload)
    log_event("query_results_audit.saved", path=str(QUERY_RESULTS_FILE), queries=len(all_queries))


# Performs the sector aliases helper step.
def _sector_aliases(value: str = "") -> set[str]:
    """Map CLI sector names to the stable sector/query hints used internally."""
    key = normalized_text(value).replace(" ", "_")
    aliases = {
        "culture": {
            "museums", "films", "heritage", "fashion", "libraries", "music",
            "visual_arts", "literature", "cooking", "architecture", "theater",
            "design_tools", "image_generation", "video_creation", "audio_voice",
            "fashion_try_on", "writing_storytelling", "archives_research",
            "translation",
        },
        "creative": {
            "visual_arts", "films", "music", "fashion", "literature",
            "design_tools", "image_generation", "video_creation", "audio_voice",
            "fashion_try_on", "writing_storytelling",
        },
        "daily": {
            "mental_health", "physical_health", "ai_education_training_daily_tasks",
            "daily_assistant", "learning", "general_market",
        },
        "life": {
            "mental_health", "physical_health", "ai_education_training_daily_tasks",
            "daily_assistant", "learning", "general_market",
        },
        "work": {"work_productivity", "general_market"},
        "productivity": {"work_productivity", "general_market"},
        "general": {"ai_education_training_daily_tasks", "general_market"},
    }
    if key in aliases:
        return aliases[key]
    return {key}


# Performs the candidate matches sector helper step.
def _candidate_matches_sector(item: dict, requested_sector: str = "") -> bool:
    targets = _sector_aliases(requested_sector)
    values = {
        normalized_text(str(item.get("sector") or "")).replace(" ", "_"),
        normalized_text(str(item.get("sector_hint") or "")).replace(" ", "_"),
        normalized_text(str(item.get("tool_sector_hint") or "")).replace(" ", "_"),
        normalized_text(str(item.get("bucket") or "")).replace(" ", "_"),
        normalized_text(str(item.get("query_mix") or "")).replace(" ", "_"),
    }
    return bool(targets & values)


# Performs the apply sector filter helper step.
def _apply_sector_filter(candidates: list[dict], diagnostics: dict, sector: str = "") -> list[dict]:
    """Apply the optional CLI sector filter when it leaves a usable candidate pool."""
    sector = str(sector or "").strip()
    if not sector:
        return candidates
    matched = [item for item in candidates or [] if _candidate_matches_sector(item, sector)]
    minimum = min(6, max(1, TOTAL_NEWS_TARGET // 2))
    applied = len(matched) >= minimum
    diagnostics["cli_sector_filter"] = {
        "requested": sector,
        "matched": len(matched),
        "total": len(candidates or []),
        "minimum_to_apply": minimum,
        "applied": applied,
        "known_sectors": NEWS_SECTORS,
    }
    return matched if applied else candidates


def candidate_source_lane(item: dict) -> str:
    lane = str(item.get("source_lane") or "").strip()
    if lane:
        return lane
    query_mix = str(item.get("query_mix") or "")
    if query_mix == "verified_exa_recent_tool_update":
        return "official_exa"
    if query_mix == "tool_name_update":
        return "tool_searxng"
    if query_mix == "trusted_media_tool_update":
        return "trusted_media_exa"
    if query_mix == "exa_product_update_broad":
        return "fallback_broad"
    if query_mix == "tracker_pipeline":
        return "tracker"
    return "unknown"


def candidate_is_primary_lane(item: dict) -> bool:
    return candidate_source_lane(item) in {"official_exa", "tool_searxng", "trusted_media_exa"}


def candidate_is_fallback_lane(item: dict) -> bool:
    return candidate_source_lane(item) in {"fallback_broad", "tracker"}


def source_lane_priority(item: dict) -> int:
    return {
        "official_exa": 40,
        "tool_searxng": 30,
        "trusted_media_exa": 22,
        "tracker": 12,
        "fallback_broad": 4,
    }.get(candidate_source_lane(item), 8)


# Performs the scan candidate score helper step.
def scan_candidate_score(item: dict) -> int:
    """Rank filtered news for the temporary large-scan pool without deciding final selection."""
    text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "content", "summary", "source_update_signal", "source_type", "query_mix")
    ).lower()
    score = 0
    score += min(35, max(0, int(item.get("tool_score") or item.get("popularity_score") or 0)) // 3)
    score += min(25, max(0, int(item.get("source_quality_score") or 0)) * 3)
    score += 12 if item.get("source_type") == "trending_tool" else 0
    score += 8 if item.get("is_trending") else 0
    score += 8 if item.get("query_mix") == "specialized" else 0
    score += 6 if item.get("query_mix") == "tool_driven" else 0
    score += 8 if any(term in text for term in ("official", "announcement", "release notes", "changelog", "now available")) else 0
    score += 8 if any(term in text for term in ("new feature", "new capability", "users can now", "launch", "rollout")) else 0
    score += 4 if source_domain(item.get("url") or "") not in {"medium.com", "substack.com"} else 0
    score += source_lane_priority(item)
    if candidate_source_lane(item) == "fallback_broad":
        score -= 8
    return score


# Performs the product update priority helper step.
def product_update_priority(item: dict) -> int:
    """Prefer concrete launches and model/product releases over side articles."""
    text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "content", "summary", "source_update_signal", "query")
    ).lower()
    url = str(item.get("url") or "").lower()
    score = 0
    if any(term in text for term in ("launches", "launched", "introduces", "released", "rolls out", "rolling out", "now available")):
        score += 35
    if any(term in text for term in ("new model", "new version", "first public", "generally available", "public can access", "available today")):
        score += 30
    if any(term in text for term in ("release notes", "changelog")) or "release-notes" in url or "/release-notes/" in url:
        score += 18
    if any(term in text for term in ("new feature", "product update", "users can now", "adds")):
        score += 16
    if any(term in text for term in ("research", "policy", "lawsuit", "ipo", "funding", "cyber threat", "security", "appoint", "appointed")):
        score -= 30
    if any(term in text for term in ("what we learned", "first look", "takeaways", "guide", "how to", "opinion")):
        score -= 16
    return score


# Performs the product update signal helper step.
def product_update_signal(item: dict) -> str:
    """Human-readable reason for product-update priority in model payload/audits."""
    text = " ".join(str(item.get(key) or "") for key in ("title", "content", "summary", "query")).lower()
    url = str(item.get("url") or "").lower()
    if any(term in text for term in ("launches", "launched", "introduces", "released", "rolls out", "rolling out")):
        return "launch_or_rollout"
    if any(term in text for term in ("new model", "new version", "first public", "generally available", "public can access", "available today")):
        return "new_model_or_public_availability"
    if any(term in text for term in ("release notes", "changelog")) or "release-notes" in url:
        return "release_notes_or_changelog"
    if any(term in text for term in ("new feature", "product update", "users can now", "adds")):
        return "feature_update"
    if any(term in text for term in ("research", "policy", "lawsuit", "ipo", "funding", "cyber threat", "security")):
        return "side_story_or_company_news"
    return ""


# Builds build large scan pool for the next pipeline or API step.
def build_large_scan_pool(candidates: list[dict], diagnostics: dict) -> list[dict]:
    """Keep a broad, in-memory pool for this run only."""
    for item in candidates or []:
        item["update_priority"] = product_update_priority(item)
        item["product_update_signal"] = product_update_signal(item)
        item["source_lane"] = candidate_source_lane(item)
    ranked = sorted(
        candidates or [],
        key=lambda item: (source_lane_priority(item), int(item.get("update_priority") or 0), scan_candidate_score(item)),
        reverse=True,
    )
    limit = max(AI_UPDATES_GPT_SHORTLIST_LIMIT, AI_UPDATES_SCAN_POOL_LIMIT)
    pool = ranked[:limit]
    diagnostics["large_scan"] = {
        "enabled": True,
        "filtered_candidates": len(candidates or []),
        "scan_pool_limit": limit,
        "scan_pool_count": len(pool),
        "scan_pool_score_max": scan_candidate_score(pool[0]) if pool else 0,
        "scan_pool_score_min": scan_candidate_score(pool[-1]) if pool else 0,
        "scan_pool_product_priority_max": product_update_priority(pool[0]) if pool else 0,
        "scan_pool_product_priority_min": product_update_priority(pool[-1]) if pool else 0,
        "scan_pool_source_lane_counts": dict(Counter(candidate_source_lane(item) for item in pool)),
    }
    return pool


# Performs the shortlist scan pool for gpt helper step.
def shortlist_scan_pool_for_gpt(scan_pool: list[dict], diagnostics: dict) -> list[dict]:
    """Shortlist the temporary scan pool without using inferred sector hints."""
    target = max(1, AI_UPDATES_GPT_SHORTLIST_LIMIT)
    selected = []
    selected_ids = set()
    owner_counts = {}
    mix_counts = {}
    lane_counts = {}
    primary_pool = [item for item in scan_pool or [] if candidate_is_primary_lane(item)]
    fallback_cap = max(1, (target * OFFICIAL_FIRST_FALLBACK_PERCENT) // 100)
    fallback_cap_initially_enforced = len(primary_pool) >= min(OFFICIAL_FIRST_MIN_PRIMARY, max(1, target - fallback_cap))
    enforce_fallback_cap = fallback_cap_initially_enforced

    # Performs the item key helper step.
    def item_key(item: dict) -> str:
        return "|".join([
            str(item.get("story_key") or ""),
            str(item.get("url") or ""),
            str(item.get("title") or ""),
        ])

    # Performs the owner helper step.
    def owner(item: dict) -> str:
        return str(item.get("owner_key") or item.get("company_name") or item.get("company") or source_domain(item.get("url") or "") or "unknown")

    # Performs the tool key helper step.
    def tool_key(item: dict) -> str:
        key = normalized_text(str(item.get("tool") or item.get("company") or item.get("owner_key") or ""))
        return key or owner(item)

    # Performs the add item helper step.
    def add_item(item: dict, *, strict: bool) -> bool:
        key = item_key(item)
        if key in selected_ids or not can_add(item, strict=strict):
            return False
        selected.append(item)
        selected_ids.add(key)
        owner_counts[owner(item)] = owner_counts.get(owner(item), 0) + 1
        mix_counts[str(item.get("query_mix") or "unknown")] = mix_counts.get(str(item.get("query_mix") or "unknown"), 0) + 1
        lane = candidate_source_lane(item)
        lane_counts[lane] = lane_counts.get(lane, 0) + 1
        return True

    # Returns whether can add is true for the current input.
    def can_add(item: dict, *, strict: bool) -> bool:
        if owner_counts.get(owner(item), 0) >= (2 if strict else 3):
            return False
        if mix_counts.get(str(item.get("query_mix") or "unknown"), 0) >= (target // 2 if strict else target):
            return False
        if enforce_fallback_cap and candidate_is_fallback_lane(item):
            current_fallback = sum(lane_counts.get(lane, 0) for lane in ("fallback_broad", "tracker"))
            if current_fallback >= fallback_cap:
                return False
        return True

    tool_groups = defaultdict(list)
    for item in scan_pool or []:
        if candidate_is_primary_lane(item):
            tool_groups[tool_key(item)].append(item)
    tool_seed_limit = min(target, max(12, target - fallback_cap))
    for _, group in sorted(
        tool_groups.items(),
        key=lambda pair: max((source_lane_priority(item), product_update_priority(item), scan_candidate_score(item)) for item in pair[1]),
        reverse=True,
    ):
        if len(selected) >= tool_seed_limit:
            break
        for item in sorted(group, key=lambda value: (source_lane_priority(value), product_update_priority(value), scan_candidate_score(value)), reverse=True)[:2]:
            if add_item(item, strict=False):
                break

    for strict in (True, False):
        for item in scan_pool or []:
            if len(selected) >= target:
                break
            add_item(item, strict=strict)
        if len(selected) >= target:
            break

    if len(selected) < target and enforce_fallback_cap:
        enforce_fallback_cap = False
        for item in scan_pool or []:
            if len(selected) >= target:
                break
            add_item(item, strict=False)

    diagnostics["large_scan"] = {
        **dict(diagnostics.get("large_scan") or {}),
        "gpt_shortlist_limit": target,
        "gpt_shortlist_count": len(selected),
        "gpt_shortlist_inferred_sector_counts": dict(Counter(str(item.get("sector") or "unknown") for item in selected)),
        "gpt_shortlist_query_mix_counts": dict(Counter(str(item.get("query_mix") or "unknown") for item in selected)),
        "gpt_shortlist_source_lane_counts": dict(Counter(candidate_source_lane(item) for item in selected)),
        "gpt_shortlist_source_type_counts": dict(Counter(str(item.get("source_type") or "unknown") for item in selected)),
        "official_first_enabled": True,
        "official_first_primary_candidates": len(primary_pool),
        "official_first_fallback_cap": fallback_cap,
        "official_first_fallback_cap_enforced": fallback_cap_initially_enforced,
        "tool_driven_seeded_tools": len(tool_groups),
        "tool_driven_seed_limit": tool_seed_limit,
        "sector_hints_used_for_shortlist": False,
    }
    return selected


# Runs run pipeline as an executable pipeline or service step.
def run_pipeline(write_news_json: bool = False, progress_callback=None, sector: str = "") -> dict:
    """Run the active full Generate path: news first, then courses/movies."""
    run_id = new_run_id("full")
    set_run_context(run_id, "full")
    print("\n" + "=" * 60, flush=True)
    print("[AI Updates] Modular Exa + SearXNG -> GPT pipeline", flush=True)
    print("=" * 60, flush=True)

    run_started = time.time()
    pre_run_payload = load_json(NEWS_JSON_FILE, {})
    should_write_news = write_news_json or env_bool("AI_UPDATES_WRITE_NEWS_JSON", "0")
    log_event(
        "pipeline.started",
        write_news_json=bool(write_news_json),
        should_write_news=bool(should_write_news),
        sector=sector or "",
        news_json=file_status(NEWS_JSON_FILE),
    )
    if not model_available():
        diagnostics = {
            "error": f"missing_{MODEL_PROVIDER}_api_key",
            "model_preflight_failed": True,
            "model_provider": MODEL_PROVIDER,
            "model": MODEL_FLASH_MODEL,
        }
        report = {
            "latest_updates": [],
            "timestamp": utc_now().isoformat(),
            "success": False,
            "error": diagnostics["error"],
            "diagnostics": diagnostics,
            "performance": _performance(run_started, 0, 0, 0, diagnostics, {}, source_fetch_seconds=0, filter_seconds=0),
        }
        _notify(progress_callback, f"Model preflight failed: {diagnostics['error']}")
        save_model_report(report)
        log_event("pipeline.model_preflight_failed", **diagnostics)
        return report
    remaining_quota = model_quota_remaining()
    if remaining_quota <= 0:
        diagnostics = {
            "error": f"{MODEL_PROVIDER}_quota_exhausted",
            "model_preflight_failed": True,
            "model_provider": MODEL_PROVIDER,
            "model": MODEL_FLASH_MODEL,
            "remaining_model_requests": remaining_quota,
        }
        report = {
            "latest_updates": [],
            "timestamp": utc_now().isoformat(),
            "success": False,
            "error": diagnostics["error"],
            "diagnostics": diagnostics,
            "performance": _performance(run_started, 0, 0, 0, diagnostics, {}, source_fetch_seconds=0, filter_seconds=0),
        }
        _notify(progress_callback, f"Model preflight failed: {diagnostics['error']}")
        save_model_report(report)
        log_event("pipeline.model_preflight_failed", **diagnostics)
        return report
    support_executor = None
    support_future = None

    # Two-cycle news fetch: cycle 1 uses the current query rotation. If the
    # model cannot fill the complete 12-card bank, cycle 2 fetches the next
    # rotated query batch, merges candidates, and asks GPT again before failing.
    candidates = []
    diagnostics = {}
    gpt_candidates = []
    report = {}
    source_fetch_seconds = 0.0
    filter_seconds = 0.0
    gpt_seconds = 0.0
    tool_activity_queried: set[str] = set()
    tool_activity_seen: set[str] = set()
    all_preselected_pool: list[dict] = []
    for cycle in range(1, NEWS_FETCH_CYCLES + 1):
        _notify(progress_callback, f"Starting news fetch cycle {cycle}/{NEWS_FETCH_CYCLES} with Exa and SearXNG")
        fetch_started = time.time()
        try:
            with timed_stage("source_fetch", target_hint=sector or "", cycle=cycle):
                cycle_candidates, cycle_diagnostics = fetch_news_candidates(target_hint=sector or "", cycle=cycle)
        except Exception as fetch_exc:
            cycle_candidates = []
            cycle_diagnostics = {
                "error": "source_fetch_exception",
                "exception": str(fetch_exc),
                "raw_results": 0,
                "unique_results": 0,
                "queries": 0,
                "source_failures": {"source_fetch": "source_fetch_exception"},
                "source_failures_detail": {"source_fetch": str(fetch_exc)},
            }
        exa_cycle_diag = (cycle_diagnostics.get("source_diagnostics") or {}).get("exa") or {}
        tool_activity_queried.update(exa_cycle_diag.get("tool_activity_queried") or [])
        tool_activity_seen.update(exa_cycle_diag.get("tool_activity_seen") or [])
        cycle_candidates = _apply_sector_filter(cycle_candidates, cycle_diagnostics, sector)
        candidates = _merge_candidate_pools(candidates, cycle_candidates)
        diagnostics = _merge_cycle_diagnostics(diagnostics, cycle_diagnostics, cycle, len(candidates or []))
        cycle_fetch_seconds = time.time() - fetch_started
        source_fetch_seconds += cycle_fetch_seconds
        log_event(
            "source_fetch.summary",
            cycle=cycle,
            raw_results=cycle_diagnostics.get("raw_results", 0),
            unique_results=len(cycle_candidates or []),
            merged_unique_results=len(candidates or []),
            queries=cycle_diagnostics.get("queries", 0),
            source_failures=cycle_diagnostics.get("source_failures", {}),
            sample=summarize_items(cycle_candidates, limit=8),
        )
        _notify(
            progress_callback,
            f"Source fetch cycle {cycle} finished in {cycle_fetch_seconds:.1f}s "
            f"raw={cycle_diagnostics.get('raw_results', 0)} merged_unique={len(candidates or [])}",
        )

        _notify(progress_callback, f"Quality filter cycle {cycle} started")
        cycle_filter_started = time.time()
        with timed_stage("quality_filter", input_candidates=len(candidates or []), cycle=cycle):
            filtered = filter_news_candidates(candidates, diagnostics, single=False)
            diagnostics["weak_sector_report"] = flag_weak_sectors(filtered)
            scan_pool = build_large_scan_pool(filtered, diagnostics)
            gpt_candidates = shortlist_scan_pool_for_gpt(scan_pool, diagnostics)
        cycle_filter_seconds = time.time() - cycle_filter_started
        filter_seconds += cycle_filter_seconds
        log_event(
            "quality_filter.summary",
            cycle=cycle,
            kept=len(filtered or []),
            scan_pool=len(scan_pool or []),
            gpt_shortlist=len(gpt_candidates or []),
            weak_sector_report=diagnostics.get("weak_sector_report", {}),
            shortlist_sample=summarize_items(gpt_candidates, limit=10),
        )
        _notify(
            progress_callback,
            f"Quality filter cycle {cycle} finished in {cycle_filter_seconds:.1f}s kept={len(filtered)} "
            f"scan={len(scan_pool)} shortlist={len(gpt_candidates)}",
        )

        _notify(progress_callback, f"Sending cycle {cycle} shortlist ({len(gpt_candidates)}) to GPT")
        cycle_gpt_started = time.time()
        with timed_stage("gpt_news_selection", candidates=len(gpt_candidates or []), cycle=cycle):
            cycle_report = select_news_updates(gpt_candidates, diagnostics, single=False)
        cycle_gpt_seconds = time.time() - cycle_gpt_started
        gpt_seconds += cycle_gpt_seconds
        if cycle_report.get("preselected_pool"):
            all_preselected_pool.extend(cycle_report["preselected_pool"])
        # CHANGE: `report` used to be unconditionally overwritten by whatever
        # this cycle returned, so a cycle 2 failure (e.g. a real Gemini
        # provider-side quota_or_billing error mid-run, hit in production
        # 2026-07-11) discarded a perfectly good cycle 1 report (6 selected
        # items) and left the whole run with 0 saved. Keep the best
        # successful report seen so far instead of the most recent one.
        cycle_selected_count = len(cycle_report.get("latest_updates") or [])
        previous_selected_count = len(report.get("latest_updates") or [])
        if cycle_report.get("success") and (not report.get("success") or cycle_selected_count >= previous_selected_count):
            report = cycle_report
        elif not report:
            report = cycle_report
        selected_now = len(report.get("latest_updates") or [])
        diagnostics.setdefault("gpt_cycle_results", []).append({
            "cycle": cycle,
            "selected": cycle_selected_count,
            "banked": selected_now,
            "required": TOTAL_NEWS_TARGET,
            "seconds": round(cycle_gpt_seconds, 2),
        })
        log_event(
            "gpt_news_selection.summary",
            cycle=cycle,
            selected=cycle_selected_count,
            banked=selected_now,
            selected_sample=summarize_items(cycle_report.get("latest_updates") or [], limit=12),
            success=bool(cycle_report.get("success")),
            error=cycle_report.get("error"),
        )
        _notify(progress_callback, f"AI model cycle {cycle} selected={cycle_selected_count} banked={selected_now}/{TOTAL_NEWS_TARGET}")
        if selected_now >= TOTAL_NEWS_TARGET or cycle >= NEWS_FETCH_CYCLES:
            break
        # CHANGE: previously kept fetching (~90-150s of Exa/SearXNG queries)
        # for every remaining cycle even after the model itself reported the
        # provider quota was exhausted (hit in production 2026-07-11/12: a
        # daily Gemini quota ran out mid-run and cycle 2's entire fetch stage
        # ran anyway, guaranteed to hit the same quota error again). If the
        # model has no quota left, no later cycle can succeed either -
        # stop fetching and go straight to save/finalize with what exists.
        if model_quota_remaining() <= 0:
            diagnostics["cycle_loop_stopped_early"] = "model_quota_exhausted"
            _notify(progress_callback, f"Stopping after cycle {cycle}: {MODEL_PROVIDER} quota exhausted for today")
            break
        _notify(progress_callback, f"Only {selected_now}/{TOTAL_NEWS_TARGET} news selected; starting fetch cycle {cycle + 1}")

    # Last-resort backfill (2026-07-12, explicit user request: "guarantee 12,
    # widen diversity instead of the date window"): after every normal cycle
    # and topup is exhausted, some model-selected, already-rewritten,
    # already-structurally-valid items get dropped only for exceeding the
    # >2-per-company cap (balance_for_diversity). If the run is still short
    # of target, re-run that same cap logic once more with a relaxed cap over
    # the union of everything selected across all cycles - zero new Exa/
    # SearXNG/Gemini calls, since nothing here is re-fetched or re-asked.
    # Only swapped in if it strictly improves the count; items from this pass
    # are tagged so it stays auditable which cards came from the relaxed tier.
    if len(report.get("latest_updates") or []) < TOTAL_NEWS_TARGET and all_preselected_pool:
        relaxed_diagnostics: dict = {}
        relaxed_selection = balance_for_diversity(
            all_preselected_pool, TOTAL_NEWS_TARGET, relaxed_diagnostics, company_cap=4,
        )
        if len(relaxed_selection) > len(report.get("latest_updates") or []):
            previous_count = len(report.get("latest_updates") or [])
            # Tag the 3rd+ card from any one company - those are the ones
            # that only exist here because the cap was relaxed from 2 to 4.
            owner_seen: Counter = Counter()
            for item in relaxed_selection:
                owner = item.get("owner_key") or ""
                owner_seen[owner] += 1
                item["diversity_relaxed_fallback"] = bool(owner) and owner_seen[owner] > 2
            report = dict(report)
            report["latest_updates"] = relaxed_selection
            report["success"] = True
            report["diversity_relaxed_fallback_used"] = True
            diagnostics["diversity_relaxed_fallback"] = {
                "before": previous_count,
                "after": len(relaxed_selection),
                "company_cap": 4,
            }
            log_event(
                "gpt_news_selection.diversity_relaxed_fallback",
                before=previous_count,
                after=len(relaxed_selection),
                company_cap=4,
            )
            _notify(progress_callback, f"Relaxed company diversity cap to reach {len(relaxed_selection)}/{TOTAL_NEWS_TARGET} news")

    if tool_activity_queried:
        try:
            diagnostics["tool_activity_signal"] = apply_tool_activity_signal(
                sorted(tool_activity_queried), sorted(tool_activity_seen)
            )
        except Exception as activity_exc:
            diagnostics["tool_activity_signal_error"] = str(activity_exc)

    fetch_seconds = source_fetch_seconds + filter_seconds
    save_query_results_audit(diagnostics)
    update_sector_terms(report.get("latest_updates") or [], diagnostics)
    save_candidate_audit(gpt_candidates, report, diagnostics)
    _notify(
        progress_callback,
        f"AI model finished in {gpt_seconds:.1f}s selected={len(report.get('latest_updates') or [])}",
    )

    save_started = time.time()
    with timed_stage("save_model_report"):
        save_model_report(report)
    save_seconds = time.time() - save_started

    performance = _performance(
        run_started,
        fetch_seconds,
        gpt_seconds,
        save_seconds,
        diagnostics,
        report,
        source_fetch_seconds=source_fetch_seconds,
        filter_seconds=filter_seconds,
    )
    report["performance"] = performance
    if isinstance(report.get("diagnostics"), dict):
        report["diagnostics"]["performance"] = performance

    saved_news = False
    if should_write_news:
        _notify(progress_callback, "Saving runtime/news.json")
        save_news_started = time.time()
        with timed_stage("save_news_json", target=str(NEWS_JSON_FILE)):
            saved_news = save_news_report(report, performance)
        performance["news_json_save_seconds"] = round(time.time() - save_news_started, 2)
        performance["news_json_saved"] = bool(saved_news)
        performance["save_seconds"] = round(save_seconds + performance["news_json_save_seconds"], 2)
        _notify(progress_callback, f"Saved runtime/news.json in {performance['news_json_save_seconds']:.1f}s")

    selected_count = len(report.get("latest_updates") or [])
    if saved_news:
        support_started = time.time()
        if support_future is not None:
            _notify(progress_callback, "Applying prefetched courses and movies")
            support_wait_started = time.time()
            try:
                with timed_stage("supporting_content.wait_for_prefetch"):
                    built_support = support_future.result()
                performance["supporting_content_wait_seconds"] = round(time.time() - support_wait_started, 2)
                support_apply_started = time.time()
                with timed_stage("supporting_content.apply"):
                    support = apply_supporting_content(built_support, pre_run_payload)
                performance["supporting_content_apply_seconds"] = round(time.time() - support_apply_started, 2)
                performance["supporting_content_prefetched"] = True
                performance["supporting_content_seconds"] = round(float(support.get("seconds") or 0.0), 2)
                performance["supporting_content_blocking_seconds"] = round(time.time() - support_started, 2)
            except Exception as support_exc:
                performance["supporting_content_prefetch_error"] = str(support_exc)
                support = {
                    "enabled": True,
                    "courses": 0,
                    "movies": 0,
                    "seconds": 0.0,
                    "kept_existing": [{"section": "supporting", "reason": f"prefetch_failed:{support_exc}"}],
                }
                performance["supporting_content_seconds"] = 0.0
                performance["supporting_content_blocking_seconds"] = round(time.time() - support_started, 2)
                performance["supporting_content_prefetched"] = False
        else:
            _notify(progress_callback, "Supporting content started")
            with timed_stage("supporting_content.refresh"):
                support = refresh_supporting_content(pre_run_payload)
            performance["supporting_content_seconds"] = round(time.time() - support_started, 2)
            performance["supporting_content_blocking_seconds"] = performance["supporting_content_seconds"]
            performance["supporting_content_prefetched"] = False
        for key in (
            "courses_fetch_seconds",
            "courses_filter_seconds",
            "courses_gpt_seconds",
            "courses_total_seconds",
            "movies_fetch_seconds",
            "movies_filter_seconds",
            "movies_gpt_seconds",
            "movies_total_seconds",
        ):
            if key in support:
                performance[key] = support.get(key)
        performance["courses_seconds"] = round(float(support.get("courses_total_seconds") or 0.0), 2) if support.get("courses") else 0
        performance["movies_seconds"] = round(float(support.get("movies_total_seconds") or 0.0), 2) if support.get("movies") else 0
        report["supporting_content"] = support
        report["supporting_content_handled"] = True
        log_event("supporting_content.summary", **{key: value for key, value in support.items() if key != "_cards"})
        _notify(progress_callback, f"Supporting content finished in {performance['supporting_content_seconds']:.1f}s")
    else:
        performance["supporting_content_seconds"] = 0
        report["supporting_content_handled"] = False
        report["supporting_content_skipped_reason"] = "news_not_saved"
    performance["total_seconds"] = round(time.time() - run_started, 2)
    performance["stage_durations"] = [
        {"key": "source_fetch", "label": "Source fetch", "seconds": performance.get("source_fetch_seconds", 0)},
        {"key": "quality_filter", "label": "Quality filters and memory", "seconds": performance.get("filter_seconds", 0)},
        {"key": "ai_model", "label": "AI model selection", "seconds": performance.get("gpt_seconds", 0)},
        {"key": "save", "label": "Save output", "seconds": performance.get("save_seconds", 0)},
        {"key": "supporting", "label": "Courses and movies", "seconds": performance.get("supporting_content_blocking_seconds", performance.get("supporting_content_seconds", 0))},
    ]
    if saved_news:
        write_news_fetch_state(performance, news_items_from_updates(list(report.get("latest_updates") or [])))
    # Persist the final report after supporting content and timing fields are
    # attached; the first save happens before courses/movies are refreshed.
    save_model_report(report)
    log_event(
        "pipeline.finished",
        success=bool(report.get("success")),
        selected_count=selected_count,
        saved_news=bool(saved_news),
        total_seconds=round(time.time() - run_started, 2),
        performance=performance,
        news_json=file_status(NEWS_JSON_FILE),
    )
    if support_executor is not None:
        support_executor.shutdown(wait=False, cancel_futures=True)

    print("=" * 60 + "\n", flush=True)
    return report


# Runs run single update pipeline as an executable pipeline or service step.
def run_single_update_pipeline(
    *,
    exclude_items: list[dict] | None = None,
    target_hint: str = "",
) -> dict:
    """Run the same editorial path as full Generate with smaller pools and a targeted angle."""
    run_id = new_run_id("single-news")
    set_run_context(run_id, "single_news")
    print("\n" + "=" * 60, flush=True)
    print("[AI Updates] Modular single update pipeline", flush=True)
    print("=" * 60, flush=True)

    run_started = time.time()
    fetch_started = time.time()
    log_event("single_news_pipeline.started", target_hint=target_hint, exclude_count=len(exclude_items or []))
    with timed_stage("source_fetch", target_hint=target_hint):
        candidates, diagnostics = fetch_news_candidates(
            exclude_items=exclude_items,
            target_hint=target_hint,
            single=True,
        )
    diagnostics["mode"] = diagnostics.get("mode") or "single_parallel"
    source_fetch_seconds = time.time() - fetch_started
    filter_started = time.time()
    with timed_stage("quality_filter", input_candidates=len(candidates or [])):
        filtered = filter_news_candidates(candidates, diagnostics, single=True)
    if exclude_items:
        before_exclude = len(filtered)
        filtered = [
            item for item in filtered
            if not any(items_same_story(item, existing) for existing in exclude_items or [])
        ]
        diagnostics["single_excluded_same_story_after_filter"] = before_exclude - len(filtered)
    scan_pool = build_large_scan_pool(filtered, diagnostics)
    gpt_candidates = shortlist_scan_pool_for_gpt(scan_pool, diagnostics)
    filter_seconds = time.time() - filter_started
    fetch_seconds = source_fetch_seconds + filter_seconds

    gpt_started = time.time()
    with timed_stage("gpt_news_selection", candidates=len(gpt_candidates or [])):
        report = select_news_updates(gpt_candidates, diagnostics, single=True)
    gpt_seconds = time.time() - gpt_started

    # A targeted single fetch can occasionally leave only a handful of valid
    # candidates after recency and memory checks. If that small pool cannot
    # produce a card, use the second, broader fetch cycle from full generation
    # and ask for just one result. This preserves the single-card response
    # contract while giving it the same recovery path as Full Fetch.
    if (
        not report.get("success")
        and NEWS_FETCH_CYCLES > 1
        and model_quota_remaining() > 0
    ):
        initial_candidate_keys = {
            _candidate_identity(item)
            for item in gpt_candidates or []
            if _candidate_identity(item)
        }
        log_event(
            "single_news_expansion.started",
            initial_candidates=len(gpt_candidates or []),
            reason=report.get("error") or "no_selected_update",
        )
        expansion_fetch_started = time.time()
        with timed_stage("source_fetch", target_hint=target_hint, cycle=2, expansion=True):
            expansion_candidates, expansion_diagnostics = fetch_news_candidates(
                exclude_items=exclude_items,
                target_hint=target_hint,
                single=False,
                cycle=2,
            )
        source_fetch_seconds += time.time() - expansion_fetch_started
        candidates = _merge_candidate_pools(candidates, expansion_candidates)
        diagnostics = _merge_cycle_diagnostics(
            diagnostics,
            expansion_diagnostics,
            2,
            len(candidates),
        )

        expansion_filter_started = time.time()
        with timed_stage("quality_filter", input_candidates=len(candidates), cycle=2, expansion=True):
            expanded_filtered = filter_news_candidates(candidates, diagnostics, single=False)
        if exclude_items:
            expanded_filtered = [
                item for item in expanded_filtered
                if not any(items_same_story(item, existing) for existing in exclude_items or [])
            ]
        expanded_scan_pool = build_large_scan_pool(expanded_filtered, diagnostics)
        expanded_gpt_candidates = [
            item
            for item in shortlist_scan_pool_for_gpt(expanded_scan_pool, diagnostics)
            if _candidate_identity(item) not in initial_candidate_keys
        ]
        filter_seconds += time.time() - expansion_filter_started

        expansion_gpt_started = time.time()
        with timed_stage(
            "gpt_news_selection",
            candidates=len(expanded_gpt_candidates),
            cycle=2,
            expansion=True,
        ):
            expanded_report = select_news_updates(
                expanded_gpt_candidates,
                diagnostics,
                single=True,
            )
        gpt_seconds += time.time() - expansion_gpt_started
        if expanded_report.get("success"):
            report = expanded_report
        else:
            report["diagnostics"] = diagnostics
            report["expansion_error"] = expanded_report.get("error") or "no_selected_update"
        diagnostics["single_expansion"] = {
            "attempted": True,
            "fetched_candidates": len(expansion_candidates or []),
            "new_shortlist_candidates": len(expanded_gpt_candidates),
            "success": bool(expanded_report.get("success")),
        }
        report["diagnostics"] = diagnostics
        log_event("single_news_expansion.finished", **diagnostics["single_expansion"])

    performance = _performance(
        run_started,
        fetch_seconds,
        gpt_seconds,
        0.0,
        diagnostics,
        report,
        source_fetch_seconds=source_fetch_seconds,
        filter_seconds=filter_seconds,
    )
    performance["mode"] = "single_parallel"
    report["performance"] = performance
    if isinstance(report.get("diagnostics"), dict):
        report["diagnostics"]["performance"] = performance

    generated_items = news_items_from_updates(list(report.get("latest_updates") or []))
    performance["semantic_memory_saved"] = 0
    performance["semantic_memory_save_deferred"] = True
    report["news_items"] = generated_items
    report["item"] = generated_items[0] if generated_items else None
    print(
        f"[AI Updates] Single selected={len(generated_items)} "
        f"raw={performance['raw_candidates']} valid={performance['valid_candidates']} "
        f"total={performance['total_seconds']}s",
        flush=True,
    )
    print("=" * 60 + "\n", flush=True)
    log_event(
        "single_news_pipeline.finished",
        success=bool(report.get("success")),
        selected_count=len(generated_items),
        total_seconds=performance["total_seconds"],
        performance=performance,
    )
    return report


# Runs run single supporting pipeline as an executable pipeline or service step.
def run_single_supporting_pipeline(
    content_type: str,
    *,
    exclude_items: list[dict] | None = None,
    target_count: int = 1,
    requested_level: str = "",
) -> dict:
    """Run the supporting-content pipeline for one replacement card.

    This keeps course/movie single replacement on the same fetch, filter, GPT,
    and card-shaping path as full Generate, but with smaller source pools.
    """
    content_type = str(content_type or "").strip().lower()
    if content_type not in {"course", "movie"}:
        return {"success": False, "error": "invalid_supporting_content_type", "cards": []}

    target_count = max(1, int(target_count or 1))
    # Course difficulty is level-aware; films are global and must never be
    # filtered, tagged, or persisted against the toolbar's level selection.
    requested_level = normalize_level(requested_level) if content_type == "course" else ""
    run_id = new_run_id(f"single-{content_type or 'support'}")
    set_run_context(run_id, "single_supporting")
    section = "courses" if content_type == "course" else "movies"
    run_started = time.time()
    log_event("single_supporting_pipeline.started", content_type=content_type, target_count=target_count)
    fetch_started = time.time()
    if content_type == "course":
        fetch_pool = max(
            target_count + 4,
            min(SUPPORTING_COURSE_FETCH_POOL, env_int("AI_UPDATES_SINGLE_COURSE_FETCH_POOL", "14")),
        )
        raw = fetch_course_candidates(max_results=fetch_pool)
    else:
        fetch_pool = max(
            target_count + 8,
            min(SUPPORTING_MOVIE_FETCH_POOL, env_int("AI_UPDATES_SINGLE_MOVIE_FETCH_POOL", "28")),
        )
        raw = fetch_movie_candidates(target_count=fetch_pool)
    fetch_seconds = time.time() - fetch_started

    filter_started = time.time()
    filtered = filter_supporting_candidates(
        raw or [],
        content_type,
        max(target_count + 3, target_count),
        visible_items=exclude_items or [],
    )
    if content_type == "course" and requested_level:
        same_level = [
            item for item in filtered
            if normalize_level(item.get("level") or item.get("course_level") or "") == requested_level
        ]
        filtered = same_level
    filter_seconds = time.time() - filter_started

    gpt_started = time.time()
    cards = select_supporting_content_cards(
        filtered,
        content_type,
        target_count,
        visible_count=min(target_count, DISPLAY_COUNTS.get(section, target_count)),
    )
    if content_type == "movie":
        for card in cards or []:
            for field in ("level", "course_level", "difficulty", "level_source"):
                card.pop(field, None)
    elif requested_level:
        for card in cards or []:
            card["level"] = requested_level
    gpt_seconds = time.time() - gpt_started

    performance = {
        "mode": "single_supporting",
        "content_type": content_type,
        "target_count": target_count,
        "requested_level": requested_level,
        "fetch_pool": fetch_pool,
        "raw_candidates": len(raw or []),
        "valid_candidates": len(filtered or []),
        "selected_count": len(cards or []),
        "fetch_seconds": round(fetch_seconds, 2),
        "filter_seconds": round(filter_seconds, 2),
        "gpt_seconds": round(gpt_seconds, 2),
        "total_seconds": round(time.time() - run_started, 2),
    }
    log_event(
        "single_supporting_pipeline.finished",
        content_type=content_type,
        success=bool(cards),
        selected_count=len(cards or []),
        performance=performance,
    )
    return {
        "success": bool(cards),
        "content_type": content_type,
        "section": section,
        "cards": cards,
        "item": cards[0] if cards else None,
        "performance": performance,
    }


# Performs the background loop helper step.
def _background_loop() -> None:
    while True:
        try:
            run_pipeline(write_news_json=True)
        except Exception as exc:
            print(f"[AI Updates] Background round failed: {exc}", flush=True)
        time.sleep(DAEMON_INTERVAL_SECONDS)


# Runs start background daemon as an executable pipeline or service step.
def start_background_daemon():
    """Start the optional background updater when explicitly enabled by env."""
    if not DAEMON_ENABLED:
        print("[AI Updates] Background daemon disabled", flush=True)
        return None
    daemon_thread = threading.Thread(target=_background_loop, daemon=True)
    daemon_thread.start()
    print("[AI Updates] Background daemon started", flush=True)
    return daemon_thread
