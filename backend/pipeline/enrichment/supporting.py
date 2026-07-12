"""Course and film supporting-card enrichment."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.config.settings import (
    DISPLAY_COUNTS,
    NEWS_JSON_FILE,
    SUPPORTING_COURSE_FETCH_POOL,
    SUPPORTING_MOVIE_FETCH_POOL,
    load_json,
    memory_url_key,
    safe_write_json,
)
from backend.pipeline.fetching.courses import fetch_course_candidates
from backend.pipeline.fetching.films import fetch_movie_candidates
from backend.pipeline.fetching.courses import record_discovered_course_platforms
from backend.pipeline.filtering.courses import filter_supporting_candidates, save_supporting_memory
from backend.pipeline.filtering.level_balancing import (
    COURSES_PER_LEVEL,
    build_level_bank,
    build_recommended_view,
    classify_course_item,
    course_platform_topic_diversity_key,
)
from backend.pipeline.modeling.courses import select_supporting_content_cards
from backend.logging.pipeline_logging import log_event, set_run_context, summarize_items

def build_supporting_content(pre_run_payload: dict | None = None, run_id: str = "", mode: str = "") -> dict:
    """Fetch, filter, and rewrite course/movie cards without saving news.json."""
    """Build course/movie cards without writing frontend/news.json.

    This lets the main pipeline prepare supporting content in parallel with
    news fetching/GPT selection, then apply the cards only after the current
    news run has been safely saved.
    """
    if run_id:
        set_run_context(run_id, mode or "supporting_content")
    started = time.time()
    result = {
        "enabled": True,
        "courses": 0,
        "movies": 0,
        "seconds": 0.0,
        "kept_existing": [],
        "_cards": {"courses": [], "movies": []},
    }

    course_limit = max(DISPLAY_COUNTS["courses"] + 8, SUPPORTING_COURSE_FETCH_POOL, 10)
    movie_limit = max(DISPLAY_COUNTS["movies"], 1) + 3

    def supporting_url_key(item: dict) -> str:
        if not isinstance(item, dict):
            return ""
        return memory_url_key(item.get("url") or item.get("source_url") or "")

    def dedupe_supporting_items(items: list[dict]) -> list[dict]:
        deduped = []
        seen = set()
        for item in items or []:
            key = supporting_url_key(item)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            deduped.append(item)
        return deduped

    def merge_supporting_selection(primary: list[dict], extra: list[dict], limit: int) -> list[dict]:
        merged = []
        seen = set()
        for item in list(primary or []) + list(extra or []):
            key = supporting_url_key(item)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                break
        return merged

    # Builds build one for the next pipeline or API step.
    def build_one(section: str) -> dict:
        section_started = time.time()
        fetch_seconds = 0.0
        filter_seconds = 0.0
        gpt_seconds = 0.0
        log_event("supporting_content.section_started", section=section)
        if section == "courses":
            content_type = "course"
            display_count = DISPLAY_COUNTS["courses"]
            target_limit = course_limit
            fetch_started = time.time()
            candidates = fetch_course_candidates(
                max_results=max(SUPPORTING_COURSE_FETCH_POOL, target_limit + 3)
            )
            fetch_seconds = time.time() - fetch_started
        else:
            content_type = "movie"
            display_count = DISPLAY_COUNTS["movies"]
            target_limit = movie_limit
            fetch_started = time.time()
            candidates = fetch_movie_candidates(
                target_count=max(SUPPORTING_MOVIE_FETCH_POOL, target_limit + 8)
            )
            fetch_seconds = time.time() - fetch_started
        visible_items = []
        if isinstance(pre_run_payload, dict) and isinstance(pre_run_payload.get(section), list):
            visible_items = pre_run_payload.get(section) or []
        filter_started = time.time()
        filtered_cards = filter_supporting_candidates(
            candidates,
            content_type,
            target_limit,
            visible_items=visible_items,
        )
        filter_seconds = time.time() - filter_started
        gpt_started = time.time()
        gpt_cards = select_supporting_content_cards(
            filtered_cards,
            content_type,
            min(target_limit, len(filtered_cards) or target_limit),
            visible_count=display_count,
        )
        gpt_seconds = time.time() - gpt_started
        quick_fetch_report = {}
        if section == "courses" and len(gpt_cards or []) < display_count:
            missing = display_count - len(gpt_cards or [])
            quick_fetch_started = time.time()
            log_event(
                "supporting_content.quick_fetch_started",
                section=section,
                content_type=content_type,
                selected=len(gpt_cards or []),
                missing=missing,
            )
            retry_fetch_started = time.time()
            retry_candidates = fetch_course_candidates(
                max_results=max(SUPPORTING_COURSE_FETCH_POOL, target_limit + display_count + 8)
            )
            retry_fetch_seconds = time.time() - retry_fetch_started
            combined_candidates = dedupe_supporting_items(list(candidates or []) + list(retry_candidates or []))
            selected_keys = {supporting_url_key(item) for item in gpt_cards or [] if supporting_url_key(item)}
            retry_filter_started = time.time()
            retry_filtered_cards = filter_supporting_candidates(
                combined_candidates,
                content_type,
                target_limit + display_count,
                visible_items=list(visible_items or []) + list(gpt_cards or []),
            )
            retry_filtered_cards = [
                item for item in retry_filtered_cards or []
                if supporting_url_key(item) not in selected_keys
            ]
            retry_filter_seconds = time.time() - retry_filter_started
            retry_gpt_started = time.time()
            retry_cards = select_supporting_content_cards(
                retry_filtered_cards,
                content_type,
                min(target_limit, len(retry_filtered_cards) or target_limit),
                visible_count=display_count,
                use_course_bank=False,
            )
            retry_gpt_seconds = time.time() - retry_gpt_started
            gpt_cards = merge_supporting_selection(gpt_cards, retry_cards, target_limit)
            candidates = combined_candidates
            fetch_seconds += retry_fetch_seconds
            filter_seconds += retry_filter_seconds
            gpt_seconds += retry_gpt_seconds
            quick_fetch_report = {
                "missing_before_quick_fetch": missing,
                "raw_candidates": len(retry_candidates or []),
                "combined_candidates": len(combined_candidates or []),
                "filtered_candidates": len(retry_filtered_cards or []),
                "selected": len(retry_cards or []),
                "final_selected": len(gpt_cards or []),
                "seconds": round(time.time() - quick_fetch_started, 2),
            }
            log_event(
                "supporting_content.quick_fetch_finished",
                section=section,
                content_type=content_type,
                **quick_fetch_report,
                selected_sample=summarize_items(gpt_cards or [], limit=6),
            )
        selector = "supporting_prompt_gpt"
        timings = {
            "fetch_seconds": round(fetch_seconds, 2),
            "filter_seconds": round(filter_seconds, 2),
            "gpt_seconds": round(gpt_seconds, 2),
            "total_seconds": round(time.time() - section_started, 2),
        }
        log_event(
            "supporting_content.section_finished",
            section=section,
            content_type=content_type,
            raw_candidates=len(candidates or []),
            filtered_candidates=len(filtered_cards or []),
            selected=len(gpt_cards or []),
            quick_fetch=quick_fetch_report,
            timings=timings,
            selected_sample=summarize_items(gpt_cards or [], limit=6),
        )
        if len(gpt_cards) >= display_count:
            return {
                "section": section,
                "cards": gpt_cards,
                "selector": selector,
                "prompt_selected": len(gpt_cards),
                "filtered_candidates": len(filtered_cards),
                "raw_candidates": len(candidates or []),
                "quick_fetch": quick_fetch_report,
                "timings": timings,
            }
        return {
            "section": section,
            "cards": [],
            "selector": "supporting_prompt_no_selection",
            "prompt_selected": len(gpt_cards or []),
            "filtered_candidates": len(filtered_cards),
            "raw_candidates": len(candidates or []),
            "quick_fetch": quick_fetch_report,
            "timings": timings,
            "kept_existing": {
                "section": section,
                "reason": f"not_enough_cards:{len(gpt_cards or [])}/{display_count}",
            },
        }

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(build_one, "courses"), executor.submit(build_one, "movies")]
        for future in as_completed(futures):
            try:
                section_result = future.result()
            except Exception as exc:
                result["kept_existing"].append({"section": "supporting", "reason": f"build_failed:{exc}"})
                continue
            section = section_result.get("section")
            cards = section_result.get("cards") or []
            result["_cards"][section] = cards
            result[section] = len(cards)
            result[f"{section[:-1]}_selector"] = section_result.get("selector")
            result[f"{section[:-1]}_prompt_selected"] = section_result.get("prompt_selected", 0)
            result[f"{section[:-1]}_raw_candidates"] = section_result.get("raw_candidates", 0)
            result[f"{section[:-1]}_filtered_candidates"] = section_result.get("filtered_candidates", 0)
            result[f"{section}_quick_fetch"] = section_result.get("quick_fetch", {})
            timings = section_result.get("timings") if isinstance(section_result.get("timings"), dict) else {}
            result[f"{section}_fetch_seconds"] = timings.get("fetch_seconds", 0.0)
            result[f"{section}_filter_seconds"] = timings.get("filter_seconds", 0.0)
            result[f"{section}_gpt_seconds"] = timings.get("gpt_seconds", 0.0)
            result[f"{section}_total_seconds"] = timings.get("total_seconds", 0.0)
            if section_result.get("kept_existing"):
                result["kept_existing"].append(section_result["kept_existing"])

    result["seconds"] = round(time.time() - started, 2)
    return result


# Builds apply supporting content for the next pipeline or API step.

def apply_supporting_content(built: dict, pre_run_payload: dict | None = None) -> dict:
    """Merge refreshed courses/movies into the current newsletter payload."""
    """Apply prebuilt supporting cards to the current JSON without touching news."""
    started = time.time()
    result = dict(built or {})
    result.setdefault("enabled", True)
    result.setdefault("courses", 0)
    result.setdefault("movies", 0)
    result.setdefault("kept_existing", [])
    cards_by_section = result.get("_cards") if isinstance(result.get("_cards"), dict) else {}

    payload = load_json(NEWS_JSON_FILE, {})
    changed = False
    course_cards = cards_by_section.get("courses") if isinstance(cards_by_section.get("courses"), list) else []
    movie_cards = cards_by_section.get("movies") if isinstance(cards_by_section.get("movies"), list) else []

    if len(course_cards) >= DISPLAY_COUNTS["courses"]:
        # Level-balanced newsletter change: save all selected courses as a
        # level bank, but keep the legacy `courses` field as the default
        # recommended 2-card view.
        courses_bank, bank_courses, course_bank_notes = build_level_bank(
            course_cards,
            COURSES_PER_LEVEL,
            classify_course_item,
            diversity_key_fn=course_platform_topic_diversity_key,
            # Prefer free courses at ties; does not override a stronger paid
            # candidate since ordering only affects which item breaks a tie
            # within the diversity selection, not the level/topic filtering.
            sort_key_fn=lambda item: 0 if item.get("is_free") else 1,
        )
        news_bank = payload.get("news_bank") if isinstance(payload.get("news_bank"), dict) else {}
        recommended_view = build_recommended_view(
            news_bank,
            courses_bank,
            payload.get("movies", []) if isinstance(payload.get("movies"), list) else [],
        )
        payload["courses_bank"] = courses_bank
        payload["courses"] = bank_courses[:DISPLAY_COUNTS["courses"]]
        payload["recommended_view"] = {
            **(payload.get("recommended_view") if isinstance(payload.get("recommended_view"), dict) else {}),
            "news": (payload.get("recommended_view") or {}).get("news") or payload.get("items", []),
            "courses": payload["courses"],
        }
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        metadata.update({
            "level_balancing_enabled": True,
            "courses_target_per_level": COURSES_PER_LEVEL,
            "default_courses_view_count": DISPLAY_COUNTS["courses"],
            "courses_total_count": len(bank_courses),
            "course_bank_notes": course_bank_notes,
        })
        payload["metadata"] = metadata
        result["courses"] = len(course_cards)
        visible_course_cards = payload["courses"][:DISPLAY_COUNTS["courses"]]
        save_supporting_memory(visible_course_cards, "course")
        result["course_memory_saved_visible_only"] = len(visible_course_cards)
        result["course_source"] = "ai_update_pipeline_exa_tavily"
        record_discovered_course_platforms(bank_courses)
        changed = True
    else:
        if not any(item.get("section") == "courses" for item in result["kept_existing"] if isinstance(item, dict)):
            result["kept_existing"].append({"section": "courses", "reason": f"not_enough_cards:{len(course_cards)}/{DISPLAY_COUNTS['courses']}"})

    if len(movie_cards) >= DISPLAY_COUNTS["movies"]:
        payload["movies"] = movie_cards
        if isinstance(payload.get("recommended_view"), dict):
            payload["recommended_view"]["movie"] = movie_cards[0] if movie_cards else {}
        result["movies"] = len(movie_cards)
        visible_movie_cards = movie_cards[:DISPLAY_COUNTS["movies"]]
        save_supporting_memory(visible_movie_cards, "movie")
        result["movie_memory_saved_visible_only"] = len(visible_movie_cards)
        result["movie_source"] = "ai_update_pipeline_tmdb"
        changed = True
    else:
        if not any(item.get("section") == "movies" for item in result["kept_existing"] if isinstance(item, dict)):
            result["kept_existing"].append({"section": "movies", "reason": f"not_enough_cards:{len(movie_cards)}/{DISPLAY_COUNTS['movies']}"})

    if changed:
        safe_write_json(NEWS_JSON_FILE, payload)
    result["apply_seconds"] = round(time.time() - started, 2)
    result.pop("_cards", None)
    return result


# Performs the refresh supporting content helper step.

def refresh_supporting_content(pre_run_payload: dict | None = None) -> dict:
    """Refresh courses and movies through the modular AI update pipeline."""
    built = build_supporting_content(pre_run_payload)
    return apply_supporting_content(built, pre_run_payload)

__all__ = [
    "apply_supporting_content",
    "build_supporting_content",
    "refresh_supporting_content",
]
