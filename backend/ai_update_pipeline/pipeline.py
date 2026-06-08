"""
Main orchestrator for the AI update system.

Pipeline order:
1. Fetch live candidates.
2. Filter, dedupe, and check semantic memory.
3. Ask the model to select and rewrite.
4. Enrich cards and save frontend/news.json.
5. Refresh courses and movies when this is a full Generate run.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .config import (
    AI_UPDATES_GPT_SHORTLIST_LIMIT,
    AI_UPDATES_LOOKBACK_DAYS,
    AI_UPDATES_SCAN_POOL_LIMIT,
    DAEMON_ENABLED,
    DAEMON_INTERVAL_SECONDS,
    DISPLAY_COUNTS,
    NEWS_JSON_FILE,
    NEWS_SECTORS,
    SUPPORTING_COURSE_FETCH_POOL,
    SUPPORTING_MOVIE_FETCH_POOL,
    TOTAL_NEWS_TARGET,
    clean_text,
    env_int,
    env_bool,
    load_json,
    normalized_text,
    recency_cutoff_query_token,
    source_domain,
    utc_now,
)
from .enrichment import (
    apply_supporting_content,
    build_supporting_content,
    news_items_from_updates,
    refresh_supporting_content,
    save_news_report,
    write_news_fetch_state,
)
from .fetchers import fetch_course_candidates, fetch_movie_candidates, fetch_news_candidates, flag_weak_sectors, update_sector_terms
from .filters import filter_news_candidates, filter_supporting_candidates, items_same_story
from .model import save_model_report, select_news_updates, select_supporting_content_cards


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


def _notify(progress_callback, message: str) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(message)
    except Exception:
        pass


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


CULTURE_CREATIVE_SIGNALS = {
    "museums",
    "films",
    "heritage",
    "fashion",
    "libraries",
    "music",
    "visual_arts",
    "literature",
    "cooking",
    "architecture",
    "theater",
    "culture",
    "creative",
    "culture_knowledge",
    "culture_cross_sector",
    "design_visual",
    "audio_voice",
    "video_motion",
    "literature_writing",
    "fashion_style",
    "food_cooking",
    "archives_research",
    "writing_storytelling",
    "image_design",
    "video_creation",
    "music_voice",
}


def culture_creative_signal(item: dict) -> bool:
    """Detect candidates that directly serve the newsletter's culture/creative scope."""
    values = {
        normalized_text(str(item.get(key) or "")).replace(" ", "_")
        for key in ("sector", "sector_hint", "tool_sector_hint", "bucket", "query_mix", "tool_sector_terms")
    }
    text = normalized_text(
        " ".join(str(item.get(key) or "") for key in ("title", "content", "summary", "source_query"))
    )
    return bool(values & CULTURE_CREATIVE_SIGNALS) or any(
        term in text
        for term in (
            "museum",
            "heritage",
            "archive",
            "library",
            "music",
            "film",
            "video",
            "fashion",
            "writing",
            "storytelling",
            "architecture",
            "cooking",
            "design",
        )
    )


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
    score += 10 if culture_creative_signal(item) else 0
    score += 8 if any(term in text for term in ("official", "announcement", "release notes", "changelog", "now available")) else 0
    score += 8 if any(term in text for term in ("new feature", "new capability", "users can now", "launch", "rollout")) else 0
    score += 4 if source_domain(item.get("url") or "") not in {"medium.com", "substack.com"} else 0
    return score


def build_large_scan_pool(candidates: list[dict], diagnostics: dict) -> list[dict]:
    """Keep a broad, in-memory pool for this run only."""
    ranked = sorted(candidates or [], key=scan_candidate_score, reverse=True)
    limit = max(AI_UPDATES_GPT_SHORTLIST_LIMIT, AI_UPDATES_SCAN_POOL_LIMIT)
    pool = ranked[:limit]
    diagnostics["large_scan"] = {
        "enabled": True,
        "filtered_candidates": len(candidates or []),
        "scan_pool_limit": limit,
        "scan_pool_count": len(pool),
        "scan_pool_score_max": scan_candidate_score(pool[0]) if pool else 0,
        "scan_pool_score_min": scan_candidate_score(pool[-1]) if pool else 0,
    }
    return pool


def shortlist_scan_pool_for_gpt(scan_pool: list[dict], diagnostics: dict) -> list[dict]:
    """Shortlist the temporary scan pool while preserving source/use-case variety."""
    target = max(1, AI_UPDATES_GPT_SHORTLIST_LIMIT)
    selected = []
    selected_ids = set()
    owner_counts = {}
    hint_counts = {}
    mix_counts = {}

    def item_key(item: dict) -> str:
        return "|".join([
            str(item.get("story_key") or ""),
            str(item.get("url") or ""),
            str(item.get("title") or ""),
        ])

    def hint(item: dict) -> str:
        return str(item.get("sector_hint") or item.get("tool_sector_hint") or item.get("sector") or "unknown")

    def owner(item: dict) -> str:
        return str(item.get("owner_key") or item.get("company_name") or item.get("company") or source_domain(item.get("url") or "") or "unknown")

    def can_add(item: dict, *, strict: bool) -> bool:
        if owner_counts.get(owner(item), 0) >= (2 if strict else 3):
            return False
        if hint_counts.get(hint(item), 0) >= (3 if strict else 5):
            return False
        if mix_counts.get(str(item.get("query_mix") or "unknown"), 0) >= (target // 2 if strict else target):
            return False
        return True

    culture_target = max(6, target // 3)
    for item in scan_pool or []:
        if len(selected) >= min(culture_target, target):
            break
        key = item_key(item)
        if key in selected_ids or not culture_creative_signal(item) or not can_add(item, strict=True):
            continue
        selected.append(item)
        selected_ids.add(key)
        owner_counts[owner(item)] = owner_counts.get(owner(item), 0) + 1
        hint_counts[hint(item)] = hint_counts.get(hint(item), 0) + 1
        mix_counts[str(item.get("query_mix") or "unknown")] = mix_counts.get(str(item.get("query_mix") or "unknown"), 0) + 1

    for strict in (True, False):
        for item in scan_pool or []:
            if len(selected) >= target:
                break
            key = item_key(item)
            if key in selected_ids or not can_add(item, strict=strict):
                continue
            selected.append(item)
            selected_ids.add(key)
            owner_counts[owner(item)] = owner_counts.get(owner(item), 0) + 1
            hint_counts[hint(item)] = hint_counts.get(hint(item), 0) + 1
            mix_counts[str(item.get("query_mix") or "unknown")] = mix_counts.get(str(item.get("query_mix") or "unknown"), 0) + 1
        if len(selected) >= target:
            break

    diagnostics["large_scan"] = {
        **dict(diagnostics.get("large_scan") or {}),
        "gpt_shortlist_limit": target,
        "gpt_shortlist_count": len(selected),
        "gpt_shortlist_hint_counts": dict(Counter(hint(item) for item in selected)),
        "gpt_shortlist_query_mix_counts": dict(Counter(str(item.get("query_mix") or "unknown") for item in selected)),
        "gpt_shortlist_source_type_counts": dict(Counter(str(item.get("source_type") or "unknown") for item in selected)),
    }
    return selected


def run_pipeline(write_news_json: bool = False, progress_callback=None, sector: str = "") -> dict:
    """Run the active full Generate path: news first, then courses/movies."""
    print("\n" + "=" * 60, flush=True)
    print("[AI Updates] Modular Exa + SearXNG -> GPT pipeline", flush=True)
    print("=" * 60, flush=True)

    run_started = time.time()
    pre_run_payload = load_json(NEWS_JSON_FILE, {})
    should_write_news = write_news_json or env_bool("AI_UPDATES_WRITE_NEWS_JSON", "0")
    support_executor = None
    support_future = None
    if should_write_news:
        support_executor = ThreadPoolExecutor(max_workers=1)
        support_future = support_executor.submit(build_supporting_content, pre_run_payload)
        _notify(progress_callback, "Background courses and films prefetch running")

    _notify(progress_callback, "Starting news fetch with Exa and SearXNG")
    fetch_started = time.time()
    candidates, diagnostics = fetch_news_candidates(target_hint=sector or "")
    candidates = _apply_sector_filter(candidates, diagnostics, sector)
    source_fetch_seconds = time.time() - fetch_started
    _notify(
        progress_callback,
        f"Source fetch finished in {source_fetch_seconds:.1f}s "
        f"raw={diagnostics.get('raw_results', 0)} unique={diagnostics.get('unique_results', 0)}",
    )
    _notify(progress_callback, "Quality filter started")
    filter_started = time.time()
    filtered = filter_news_candidates(candidates, diagnostics, single=False)
    diagnostics["weak_sector_report"] = flag_weak_sectors(filtered)
    scan_pool = build_large_scan_pool(filtered, diagnostics)
    gpt_candidates = shortlist_scan_pool_for_gpt(scan_pool, diagnostics)
    filter_seconds = time.time() - filter_started
    fetch_seconds = source_fetch_seconds + filter_seconds
    _notify(
        progress_callback,
        f"Quality filter finished in {filter_seconds:.1f}s kept={len(filtered)} "
        f"scan={len(scan_pool)} shortlist={len(gpt_candidates)}",
    )

    _notify(progress_callback, f"Sending {len(gpt_candidates)} shortlisted scan results to GPT")
    gpt_started = time.time()
    report = select_news_updates(gpt_candidates, diagnostics, single=False)
    update_sector_terms(report.get("latest_updates") or [], diagnostics)
    gpt_seconds = time.time() - gpt_started
    _notify(
        progress_callback,
        f"AI model finished in {gpt_seconds:.1f}s selected={len(report.get('latest_updates') or [])}",
    )

    save_started = time.time()
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
        _notify(progress_callback, "Saving frontend/news.json")
        save_news_started = time.time()
        saved_news = save_news_report(report, performance)
        performance["news_json_save_seconds"] = round(time.time() - save_news_started, 2)
        performance["news_json_saved"] = bool(saved_news)
        performance["save_seconds"] = round(save_seconds + performance["news_json_save_seconds"], 2)
        _notify(progress_callback, f"Saved frontend/news.json in {performance['news_json_save_seconds']:.1f}s")

    selected_count = len(report.get("latest_updates") or [])
    if saved_news:
        support_started = time.time()
        if support_future is not None:
            _notify(progress_callback, "Applying prefetched courses and movies")
            support_wait_started = time.time()
            try:
                built_support = support_future.result()
                performance["supporting_content_wait_seconds"] = round(time.time() - support_wait_started, 2)
                support_apply_started = time.time()
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
        _notify(progress_callback, f"Supporting content finished in {performance['supporting_content_seconds']:.1f}s")
    else:
        performance["supporting_content_seconds"] = 0
        report["supporting_content_handled"] = False
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
    if support_executor is not None:
        support_executor.shutdown(wait=False, cancel_futures=True)

    print("=" * 60 + "\n", flush=True)
    return report


def run_single_update_pipeline(
    *,
    exclude_items: list[dict] | None = None,
    target_hint: str = "",
) -> dict:
    """Run the same editorial path as full Generate with smaller pools and a targeted angle."""
    print("\n" + "=" * 60, flush=True)
    print("[AI Updates] Modular single update pipeline", flush=True)
    print("=" * 60, flush=True)

    run_started = time.time()
    fetch_started = time.time()
    candidates, diagnostics = fetch_news_candidates(
        exclude_items=exclude_items,
        target_hint=target_hint,
        single=True,
    )
    diagnostics["mode"] = diagnostics.get("mode") or "single_parallel"
    source_fetch_seconds = time.time() - fetch_started
    filter_started = time.time()
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
    report = select_news_updates(gpt_candidates, diagnostics, single=True)
    gpt_seconds = time.time() - gpt_started

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
    return report


def run_single_supporting_pipeline(
    content_type: str,
    *,
    exclude_items: list[dict] | None = None,
    target_count: int = 1,
) -> dict:
    """Run the supporting-content pipeline for one replacement card.

    This keeps course/movie single replacement on the same fetch, filter, GPT,
    and card-shaping path as full Generate, but with smaller source pools.
    """
    content_type = str(content_type or "").strip().lower()
    if content_type not in {"course", "movie"}:
        return {"success": False, "error": "invalid_supporting_content_type", "cards": []}

    target_count = max(1, int(target_count or 1))
    section = "courses" if content_type == "course" else "movies"
    run_started = time.time()
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
    filter_seconds = time.time() - filter_started

    gpt_started = time.time()
    cards = select_supporting_content_cards(
        filtered,
        content_type,
        target_count,
        visible_count=min(target_count, DISPLAY_COUNTS.get(section, target_count)),
    )
    gpt_seconds = time.time() - gpt_started

    performance = {
        "mode": "single_supporting",
        "content_type": content_type,
        "target_count": target_count,
        "fetch_pool": fetch_pool,
        "raw_candidates": len(raw or []),
        "valid_candidates": len(filtered or []),
        "selected_count": len(cards or []),
        "fetch_seconds": round(fetch_seconds, 2),
        "filter_seconds": round(filter_seconds, 2),
        "gpt_seconds": round(gpt_seconds, 2),
        "total_seconds": round(time.time() - run_started, 2),
    }
    return {
        "success": bool(cards),
        "content_type": content_type,
        "section": section,
        "cards": cards,
        "item": cards[0] if cards else None,
        "performance": performance,
    }


def _background_loop() -> None:
    while True:
        try:
            run_pipeline(write_news_json=True)
        except Exception as exc:
            print(f"[AI Updates] Background round failed: {exc}", flush=True)
        time.sleep(DAEMON_INTERVAL_SECONDS)


def start_background_daemon():
    """Start the optional background updater when explicitly enabled by env."""
    if not DAEMON_ENABLED:
        print("[AI Updates] Background daemon disabled", flush=True)
        return None
    daemon_thread = threading.Thread(target=_background_loop, daemon=True)
    daemon_thread.start()
    print("[AI Updates] Background daemon started", flush=True)
    return daemon_thread
