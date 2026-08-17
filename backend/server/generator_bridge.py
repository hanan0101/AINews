# This file is part of the AI newsletter system.
"""Bridges the HTTP Generate action to backend.pipeline.orchestrator.

This module owns generator run state (`GENERATOR_STATE`, `GENERATOR_LOCK`)
and everything that starts, tracks, or reports on a Generate run. HTTP route
handlers only read this module's state/functions; they don't run the
pipeline directly.
"""

from __future__ import annotations

import os
import threading
import time

from backend.utils.debug_logging import (
    append_generator_timeline as debug_append_generator_timeline,
    generator_public_state as debug_generator_public_state,
    trace,
)
from backend.storage.newsletter_store import (
    DISPLAY_COUNTS,
    NEWS_BACKUP_COUNT,
    NEWS_JSON_FILE,
    REQUIRED_COUNTS,
    increment_newsletter_issue,
    load_news_fetch_state_server,
    load_newsletter_settings,
    load_store,
    newsletter_template_from_settings,
    safe_int,
    save_previous_generation_snapshot,
    save_store,
    section_feedback,
    visible_items,
)
from backend.pipeline.orchestrator import run_pipeline as run_ai_updates_pipeline
from backend.pipeline.modeling.model_client import MODEL_FLASH_MODEL, MODEL_PROVIDER

AUTO_FETCH_COOLDOWN = int(os.getenv("AUTO_FETCH_COOLDOWN", "300") or "300")
USE_AI_UPDATES_PIPELINE_FOR_GENERATE = os.getenv("USE_AI_UPDATES_PIPELINE_FOR_GENERATE", "1").strip().lower() in {"1", "true", "yes", "on"}
AI_UPDATES_BACKGROUND_TOPUP_ENABLED = os.getenv(
    "AI_UPDATES_BACKGROUND_TOPUP_ENABLED", "1"
).strip().lower() in {"1", "true", "yes", "on"}
AI_UPDATES_BACKGROUND_TOPUP_DELAY_SECONDS = max(
    1,
    int(os.getenv("AI_UPDATES_BACKGROUND_TOPUP_DELAY_SECONDS", "5") or "5"),
)
NEWS_JSON_ONLY_MODE = os.getenv("NEWS_JSON_ONLY_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}

# COST BLOCK: Cap full generation/refresh runs regardless of who or what
# triggers them (each run makes many paid Gemini calls). Single-card
# refill/replace does not go through start_generator_background at all, so
# it is unaffected by this cap. A background top-up is a system-scheduled
# continuation of a run that already counted, not a new independently
# triggered run, so it is exempt (see start_generator_background).
AI_UPDATES_MAX_GENERATE_RUNS_PER_DAY = int(os.getenv("AI_UPDATES_MAX_GENERATE_RUNS_PER_DAY", "8") or "8")
_GENERATE_RUN_BUDGET_WINDOW_SECONDS = 24 * 60 * 60
_GENERATE_RUN_BUDGET_LOCK = threading.Lock()
_recent_generate_run_times: list[float] = []


def _generate_run_budget_allows_start() -> bool:
    """Record this attempt and return whether it's within the rolling 24h cap."""
    now = time.time()
    cutoff = now - _GENERATE_RUN_BUDGET_WINDOW_SECONDS
    with _GENERATE_RUN_BUDGET_LOCK:
        while _recent_generate_run_times and _recent_generate_run_times[0] < cutoff:
            _recent_generate_run_times.pop(0)
        if len(_recent_generate_run_times) >= AI_UPDATES_MAX_GENERATE_RUNS_PER_DAY:
            return False
        _recent_generate_run_times.append(now)
        return True


GENERATOR_LOCK = threading.Lock()
GENERATOR_CANCEL_EVENT = threading.Event()
GENERATOR_STATE = {
    "running": False,
    "last_result": None,
    "last_log_tail": "",
    "timeline": [],
    "started_at": None,
    "finished_at": None,
    "last_auto_start": None,
    "reason": "",
    "background_topup_pending": False,
    "sections": [],
    "active_stage_key": "",
    "stage_started_at": {},
    "stage_completed_at": {},
    "cancel_requested": False,
}

# Generator progress stages define the steps shown on the frontend's Generate
# progress UI, in order.
GENERATOR_PROGRESS_STAGES = [
    {
        "key": "source_fetch",
        "label_ar": "جلب المصادر",
        "label_en": "Fetch Sources",
    },
    {
        "key": "quality_filter",
        "label_ar": "فلترة الجودة والذاكرة",
        "label_en": "Filter and Deduplicate",
    },
    {
        "key": "ai_model",
        "label_ar": "اختيار وصياغة الأخبار",
        "label_en": "AI Selection and Writing",
    },
    {
        "key": "save",
        "label_ar": "حفظ الأخبار",
        "label_en": "Save News",
    },
    {
        "key": "supporting",
        "label_ar": "تحديث الكورسات والأفلام",
        "label_en": "Courses and Films",
    },
    {
        "key": "ready",
        "label_ar": "النشرة جاهزة للمراجعة",
        "label_en": "Newsletter Ready for Review",
    },
]
STAGE_KEY_TO_INDEX = {stage["key"]: index for index, stage in enumerate(GENERATOR_PROGRESS_STAGES)}

TIMELINE_LIMIT = 120
MESSAGE_LIMIT = 700

# Generator state accessors for the frontend and generator code to update progress and timeline in a consistent way.
append_generator_timeline = lambda line: debug_append_generator_timeline(  # noqa: E731
    line,
    GENERATOR_STATE,
    STAGE_KEY_TO_INDEX,
    TIMELINE_LIMIT,
)
def generator_public_state():
    state = debug_generator_public_state(
        GENERATOR_STATE,
        GENERATOR_PROGRESS_STAGES,
        STAGE_KEY_TO_INDEX,
        load_news_fetch_state_server,
        MESSAGE_LIMIT,
    )
    state["cancel_requested"] = bool(GENERATOR_STATE.get("cancel_requested"))
    return state


def generator_cancelled():
    return GENERATOR_CANCEL_EVENT.is_set()


def cancel_generator():
    """Request cooperative cancellation and preserve the pre-run newsletter."""
    running = bool(GENERATOR_STATE.get("running"))
    GENERATOR_CANCEL_EVENT.set()
    GENERATOR_STATE["cancel_requested"] = running
    GENERATOR_STATE["background_topup_pending"] = False
    if running:
        append_generator_timeline("Generation cancellation requested")
    return {"success": True, "running": running, "cancel_requested": running}


def should_use_ai_updates_generator(section=None, preserve_visible_sections=None):
    """Return True when the old Generate button should use the new modular path."""
    return bool(USE_AI_UPDATES_PIPELINE_FOR_GENERATE and run_ai_updates_pipeline is not None)


# Server role: Refresh courses/movies through modular supporting pipelines.
def refresh_supporting_content_into_store(base_store, pre_run_store_snapshot):
    """
    The new AI updates path owns news discovery, but the old UI still needs
    vetted course and movie cards from the modular supporting fetchers.
    """
    if os.getenv("AI_UPDATES_REFRESH_SUPPORTING_CONTENT", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        return dict(base_store or {}), {"courses": 0, "movies": 0}

    counts = {"courses": 0, "movies": 0}
    try:
        from backend.config.settings import SUPPORTING_COURSE_FETCH_POOL, SUPPORTING_MOVIE_FETCH_POOL, memory_url_key
        from backend.pipeline.fetching.content.courses.discovery import fetch_course_candidates
        from backend.pipeline.filtering.content.courses.rules import filter_supporting_candidates, save_supporting_memory
        from backend.pipeline.modeling.content.courses.model import select_supporting_content_cards
        from backend.pipeline.fetching.content.films.discovery import fetch_movie_candidates
    except Exception as exc:
        trace(f"AI updates supporting content skipped; modular sources unavailable: {exc}")
        return dict(base_store or {}), counts

    store = dict(base_store or load_store())
    fetch_plan = (
        ("course", "courses", lambda: fetch_course_candidates(max_results=max(SUPPORTING_COURSE_FETCH_POOL, DISPLAY_COUNTS.get("courses", 2) + 8))),
        ("movie", "movies", lambda: fetch_movie_candidates(target_count=max(SUPPORTING_MOVIE_FETCH_POOL, DISPLAY_COUNTS.get("movies", 1) + 12))),
    )
    for content_type, section, fetcher in fetch_plan:
        if generator_cancelled():
            trace("Supporting content refresh cancelled")
            break
        try:
            append_generator_timeline(f"Refreshing {section} with modular sources")
            raw = fetcher() or []
            if generator_cancelled():
                break
            required = DISPLAY_COUNTS.get(section, REQUIRED_COUNTS.get(section, 1))
            limit = max(required + 6, required)
            visible_items_list = []
            if isinstance(pre_run_store_snapshot, dict) and isinstance(pre_run_store_snapshot.get(section), list):
                visible_items_list = pre_run_store_snapshot.get(section) or []
            elif isinstance(store.get(section), list):
                visible_items_list = store.get(section) or []
            result = filter_supporting_candidates(raw, content_type, limit, visible_items=visible_items_list)
            gpt_result = select_supporting_content_cards(
                result,
                content_type,
                min(limit, len(result) or limit),
            )
            if generator_cancelled():
                break
            if content_type == "course" and len(gpt_result or []) < required:
                trace(
                    f"AI updates supporting {section} prompt returned "
                    f"{len(gpt_result or [])}/{required}; running quick fetch"
                )
                retry_raw = fetch_course_candidates(max_results=max(SUPPORTING_COURSE_FETCH_POOL, limit + required + 8)) or []
                seen_raw = set()
                combined_raw = []
                for item in list(raw or []) + list(retry_raw or []):
                    key = memory_url_key(item.get("url") or item.get("source_url") or "") if isinstance(item, dict) else ""
                    if key and key in seen_raw:
                        continue
                    if key:
                        seen_raw.add(key)
                    combined_raw.append(item)
                selected_keys = {
                    memory_url_key(item.get("url") or item.get("source_url") or "")
                    for item in gpt_result or []
                    if isinstance(item, dict)
                }
                retry_filtered = filter_supporting_candidates(
                    combined_raw,
                    content_type,
                    limit + required,
                    visible_items=list(visible_items_list or []) + list(gpt_result or []),
                )
                retry_filtered = [
                    item for item in retry_filtered or []
                    if memory_url_key(item.get("url") or item.get("source_url") or "") not in selected_keys
                ]
                retry_result = select_supporting_content_cards(
                    retry_filtered,
                    content_type,
                    min(limit, len(retry_filtered) or limit),
                    use_course_bank=False,
                )
                merged_result = []
                seen_selected = set()
                for item in list(gpt_result or []) + list(retry_result or []):
                    key = memory_url_key(item.get("url") or item.get("source_url") or "") if isinstance(item, dict) else ""
                    if key and key in seen_selected:
                        continue
                    if key:
                        seen_selected.add(key)
                    merged_result.append(item)
                gpt_result = merged_result
            if len(gpt_result or []) >= required:
                result = gpt_result
                trace(f"AI updates supporting {section} selected with modular supporting prompt")
            else:
                trace(
                    f"AI updates supporting {section} prompt returned "
                    f"{len(gpt_result or [])}/{required}; keeping existing content"
                )
                result = []
            if len(result or []) < required:
                trace(
                    f"AI updates supporting {section} refresh kept existing content: "
                    f"new={len(result or [])}/{required}"
                )
                continue
            store[section] = result
            counts[section] = len(result or [])
            try:
                visible_count = DISPLAY_COUNTS.get(section, REQUIRED_COUNTS.get(section, len(result or [])))
                save_supporting_memory((result or [])[:visible_count], content_type)
            except Exception as memory_exc:
                trace(f"AI updates supporting {section} memory save skipped: {memory_exc}")
            trace(f"AI updates supporting {section} refreshed: {counts[section]}")
        except Exception as exc:
            trace(f"AI updates supporting {section} refresh failed: {exc}")

    return store, counts


# Server role: Refresh and persist supporting content after news generation.
def refresh_supporting_content_for_ai_updates(pre_run_store_snapshot):
    store, counts = refresh_supporting_content_into_store(load_store(), pre_run_store_snapshot)
    if counts["courses"] or counts["movies"]:
        save_store(store, rebalance_news=True)
    return counts


def ai_updates_failure_message(report: dict, selected_count: int, minimum_news_to_save: int) -> str:
    """Return a clear generator failure reason without hiding model errors."""
    if not isinstance(report, dict):
        return "AI updates pipeline did not return a valid report."
    diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), dict) else {}
    failure = {}
    for key, value in diagnostics.items():
        if str(key).endswith("_failure") and isinstance(value, dict):
            failure = value
            break
    error = str(report.get("error") or diagnostics.get("error") or "").strip()
    category = str(failure.get("category") or "").strip()
    quota_category = str(failure.get("quota_error_category") or diagnostics.get("quota_error_category") or "").strip()
    if error.startswith("missing_") and error.endswith("_api_key"):
        return f"{MODEL_PROVIDER} API key is missing. The previous newsletter version was preserved."
    if "quota" in error.lower() or category == "quota_or_billing" or quota_category:
        return f"{MODEL_PROVIDER} quota or billing limit blocked the model step. The previous newsletter version was preserved."
    if category == "model_not_found":
        return f"{MODEL_PROVIDER} model '{MODEL_FLASH_MODEL}' was not found. Check the configured model name."
    if category in {"invalid_or_unauthorized_key", "missing_gemini_api_key", "missing_openai_api_key"}:
        return f"{MODEL_PROVIDER} credentials are invalid or unavailable. The previous newsletter version was preserved."
    if error:
        return f"AI updates pipeline failed at {error}. The previous newsletter version was preserved."
    return f"SearXNG generated {selected_count}/{minimum_news_to_save} minimum news items. The previous newsletter version was preserved."


def schedule_background_topup(reason="under_min_partial_news_bank"):
    """Queue one delayed pipeline run to fill a partial newsletter."""
    if not AI_UPDATES_BACKGROUND_TOPUP_ENABLED or NEWS_JSON_ONLY_MODE:
        return False
    if GENERATOR_STATE.get("background_topup_pending"):
        return False
    GENERATOR_STATE["background_topup_pending"] = True

    def run_later():
        if not GENERATOR_STATE.get("background_topup_pending"):
            trace("Background top-up cancelled before start")
            return
        if GENERATOR_STATE.get("running"):
            timer = threading.Timer(AI_UPDATES_BACKGROUND_TOPUP_DELAY_SECONDS, run_later)
            timer.daemon = True
            timer.start()
            trace("Background top-up waiting for current run to finish")
            return
        try:
            GENERATOR_STATE["background_topup_pending"] = False
            start_generator_background(None, reason="background_topup")
            trace(f"Background top-up started reason={reason}")
        except Exception as exc:
            GENERATOR_STATE["background_topup_pending"] = False
            trace(f"Background top-up failed to start: {exc}")

    timer = threading.Timer(AI_UPDATES_BACKGROUND_TOPUP_DELAY_SECONDS, run_later)
    timer.daemon = True
    timer.start()
    trace(
        f"Background top-up scheduled in {AI_UPDATES_BACKGROUND_TOPUP_DELAY_SECONDS}s "
        f"reason={reason}"
    )
    return True


# Server role: Bridge the frontend Generate action to the pipeline orchestrator.
def run_ai_updates_generator(section=None, force_refresh=False, preserve_visible_sections=None):
    """Bridge the UI Generate endpoint to backend.pipeline.orchestrator."""
    if run_ai_updates_pipeline is None:
        return {"success": False, "message": "AI updates pipeline is not available"}
    if not GENERATOR_LOCK.acquire(blocking=False):
        return {"success": True, "running": True, "message": "Pipeline is already running"}
    started = time.time()
    try:
        GENERATOR_STATE["running"] = True
        GENERATOR_STATE["sections"] = ["items"]
        GENERATOR_STATE["started_at"] = started
        GENERATOR_STATE["finished_at"] = None
        GENERATOR_STATE["last_log_tail"] = ""
        GENERATOR_STATE["timeline"] = []
        GENERATOR_STATE["last_result"] = None
        GENERATOR_STATE["reason"] = GENERATOR_STATE.get("reason") or "manual"
        GENERATOR_STATE["active_stage_key"] = ""
        GENERATOR_STATE["stage_started_at"] = {}
        GENERATOR_STATE["stage_completed_at"] = {}
        append_generator_timeline("Starting news fetch with SearXNG")
        pre_run_store_snapshot = load_store()
        if section in {"courses", "movies"}:
            GENERATOR_STATE["sections"] = [section]
            append_generator_timeline(f"Refreshing {section} with modular pipeline")
            store, counts = refresh_supporting_content_into_store(pre_run_store_snapshot, pre_run_store_snapshot)
            if generator_cancelled():
                payload = {"success": False, "cancelled": True, "message": "Generation cancelled by user."}
                GENERATOR_STATE["last_result"] = payload
                return payload
            save_store(store, rebalance_news=True)
            selected = counts.get(section, 0)
            success = selected >= DISPLAY_COUNTS.get(section, REQUIRED_COUNTS.get(section, 1))
            message = f"AI updates refreshed {section}: {selected} item(s)."
            GENERATOR_STATE["last_log_tail"] = message
            GENERATOR_STATE["last_result"] = {"success": success, "message": message, "counts": counts}
            trace(f"AI updates supporting-only refresh section={section} success={success} counts={counts}")
            return GENERATOR_STATE["last_result"]
        if section is None:
            GENERATOR_STATE["sections"] = ["items", "courses", "movies"]
        trace("Starting SearXNG AI updates pipeline for old UI Generate")
        try:
            report = run_ai_updates_pipeline(
                write_news_json=True,
                progress_callback=append_generator_timeline,
                cancel_check=generator_cancelled,
            )
        except Exception as exc:
            report = {"success": False, "error": "ai_updates_pipeline_exception", "exception": str(exc)}
        performance = report.get("performance") if isinstance(report, dict) else {}
        if generator_cancelled() or (isinstance(report, dict) and report.get("cancelled")):
            save_store(pre_run_store_snapshot)
            payload = {"success": False, "cancelled": True, "message": "Generation cancelled by user.", "performance": performance}
            GENERATOR_STATE["last_log_tail"] = payload["message"]
            GENERATOR_STATE["last_result"] = payload
            append_generator_timeline("Generation cancelled; previous newsletter preserved")
            return payload
        selected_count = len(report.get("latest_updates") or []) if isinstance(report, dict) else 0
        required_total = DISPLAY_COUNTS.get("items", REQUIRED_COUNTS["items"]) + NEWS_BACKUP_COUNT
        # Flexible save gate: target the configured full bank, but accept only
        # when the configured minimum news count is saved.
        minimum_news_to_save = max(
            1,
            min(required_total, safe_int(os.getenv("AI_UPDATES_MIN_NEWS_SAVE_COUNT"), 1)),
        )
        append_generator_timeline(
            f"SearXNG news selected {selected_count}/{required_total} target "
            f"(minimum {minimum_news_to_save}) "
            f"in {safe_int(round(float(performance.get('total_seconds', 0) or 0)))}s"
        )
        saved_news_count = safe_int(performance.get("news_saved_count"), selected_count)
        display_success = bool(
            isinstance(report, dict)
            and report.get("success")
            and performance.get("news_json_saved")
            and NEWS_JSON_FILE.exists()
        )
        complete_success = bool(display_success and saved_news_count >= minimum_news_to_save)
        partial_success = bool(display_success and not complete_success)
        background_topup_scheduled = False
        current_reason = str(GENERATOR_STATE.get("reason") or "manual")
        if partial_success and current_reason != "background_topup":
            background_topup_scheduled = schedule_background_topup("under_min_partial_news_bank")
            if background_topup_scheduled:
                append_generator_timeline("Partial newsletter saved; background top-up scheduled")
        if display_success:
            support_counts = {"courses": 0, "movies": 0}
            if section is None and isinstance(report, dict) and report.get("supporting_content_handled"):
                support_info = report.get("supporting_content") if isinstance(report.get("supporting_content"), dict) else {}
                support_counts = {
                    "courses": safe_int(support_info.get("courses", 0)),
                    "movies": safe_int(support_info.get("movies", 0)),
                }
                trace(
                    "SearXNG pipeline handled supporting content: "
                    f"courses={support_counts.get('courses', 0)} movies={support_counts.get('movies', 0)}"
                )
            elif section is None:
                support_counts = refresh_supporting_content_for_ai_updates(pre_run_store_snapshot)
            try:
                reconciled_input = load_store()
                reconciled_input["template"] = newsletter_template_from_settings(
                    load_newsletter_settings()
                )
                reconciled_store = save_store(reconciled_input, rebalance_news=True)
                trace(
                    "SearXNG pipeline reconciled runtime/news.json: "
                    f"items={len(reconciled_store.get('items', []))} "
                    f"visible_items={len(visible_items(reconciled_store, 'items'))}"
                )
            except Exception as reconcile_exc:
                trace(f"SearXNG pipeline reconcile failed: {reconcile_exc}")
            if section is None and complete_success:
                increment_newsletter_issue()
            append_generator_timeline("Saved runtime/news.json")
            append_generator_timeline(
                "Newsletter ready for review" if complete_success else "Partial newsletter ready for review"
            )
        else:
            try:
                restored_store = dict(pre_run_store_snapshot or {})
                support_counts = {"courses": 0, "movies": 0}
                save_store(restored_store)
                trace(
                    "SearXNG pipeline did not produce enough live news to save; "
                    "restored pre-run news and skipped supporting refresh"
                )
            except Exception as restore_exc:
                trace(f"SearXNG pipeline restore skipped: {restore_exc}")
        total_seconds = time.time() - started
        append_generator_timeline(
            "Fetch finished successfully" if complete_success else (
                "Partial newsletter saved" if partial_success else "Fetch finished without enough news"
            )
        )
        if complete_success:
            message = f"SearXNG generated {saved_news_count} news items in {total_seconds:.1f}s."
        elif partial_success:
            message = (
                f"SearXNG generated {saved_news_count}/{minimum_news_to_save} minimum news items "
                f"in {total_seconds:.1f}s. Showing the partial newsletter now."
            )
            if background_topup_scheduled:
                message += " Background top-up started."
        else:
            message = ai_updates_failure_message(report, selected_count, minimum_news_to_save)
        if display_success and section is None:
            message += f" courses={support_counts.get('courses', 0)} movies={support_counts.get('movies', 0)}."
        if performance:
            message += (
                f" fetch={float(performance.get('fetch_seconds', 0) or 0):.1f}s"
                f" gpt={float(performance.get('gpt_seconds', 0) or 0):.1f}s"
            )
        payload = {
            "success": display_success,
            "complete": complete_success,
            "partial": partial_success,
            "needs_background_topup": partial_success,
            "background_topup_scheduled": background_topup_scheduled,
            "message": message,
            "performance": performance,
        }
        GENERATOR_STATE["last_log_tail"] = message
        GENERATOR_STATE["last_result"] = payload
        trace(
            f"SearXNG AI updates pipeline finished in {total_seconds:.1f}s "
            f"display_success={display_success} complete={complete_success}"
        )
        return payload
    except Exception as exc:
        payload = {"success": False, "message": str(exc)}
        GENERATOR_STATE["last_log_tail"] = str(exc)
        GENERATOR_STATE["last_result"] = payload
        return payload
    finally:
        GENERATOR_STATE["running"] = False
        GENERATOR_STATE["finished_at"] = time.time()
        GENERATOR_STATE["sections"] = []
        GENERATOR_STATE["cancel_requested"] = False
        GENERATOR_LOCK.release()


# Server role: Block the disabled legacy generator path.
def run_generator(section=None, force_refresh=False, preserve_visible_sections=None):
    """Legacy generator runtime is intentionally disabled.

    All generate/refill work is routed through backend.pipeline.orchestrator.
    This guard keeps old UI entry points on the modular pipeline.
    """
    return {
        "success": False,
        "message": "Legacy generator is disabled. The server uses the stage-based pipeline only.",
    }


# Server role: Start a background generation/refill thread for the UI.
def start_generator_background(section=None, reason="manual", force_refresh=False, preserve_visible_sections=None):
    if NEWS_JSON_ONLY_MODE:
        trace(
            f"Pipeline blocked by NEWS_JSON_ONLY_MODE section={section or 'all'} "
            f"reason={reason} preserve_visible_sections={preserve_visible_sections or []}"
        )
        return {
            "success": True,
            "running": False,
            "message": "JSON-only mode active. Using current newsletter content without fetching.",
        }
    if GENERATOR_STATE["running"]:
        trace(f"Pipeline already running; request joined section={section or 'all'}")
        message = section_feedback(section) if section else "Fetching more content..."
        return {"success": True, "running": True, "message": message}
    # COST BLOCK: reason == "background_topup" is a system-scheduled
    # continuation of a run that already counted against the cap, not a new
    # independently triggered one - see _generate_run_budget_allows_start.
    if reason != "background_topup" and not _generate_run_budget_allows_start():
        trace(
            f"Generate run blocked by daily cap ({AI_UPDATES_MAX_GENERATE_RUNS_PER_DAY}/24h) "
            f"section={section or 'all'} reason={reason}"
        )
        return {
            "success": False,
            "running": False,
            "daily_limit_reached": True,
            "message": (
                f"Daily generation limit reached ({AI_UPDATES_MAX_GENERATE_RUNS_PER_DAY} runs/24h). "
                "Try again later."
            ),
        }
    GENERATOR_CANCEL_EVENT.clear()
    GENERATOR_STATE["cancel_requested"] = False

    now = time.time()
    if reason == "auto":
        last_auto_start = GENERATOR_STATE.get("last_auto_start")
        if last_auto_start and now - last_auto_start < AUTO_FETCH_COOLDOWN:
            remaining = int(AUTO_FETCH_COOLDOWN - (now - last_auto_start))
            trace(
                f"Auto-fetch skipped section={section or 'all'}; "
                f"cooldown active for {remaining}s"
            )
            return {
                "success": True,
                "running": False,
                "message": f"Waiting before another automatic fetch ({remaining}s).",
            }
        GENERATOR_STATE["last_auto_start"] = now

    if section is None and reason != "auto" and not preserve_visible_sections:
        save_previous_generation_snapshot()

    GENERATOR_STATE["running"] = True
    GENERATOR_STATE["sections"] = [section] if section else list(REQUIRED_COUNTS)
    GENERATOR_STATE["started_at"] = time.time()
    GENERATOR_STATE["finished_at"] = None
    GENERATOR_STATE["last_log_tail"] = ""
    GENERATOR_STATE["last_result"] = None
    GENERATOR_STATE["timeline"] = []
    GENERATOR_STATE["reason"] = reason
    GENERATOR_STATE["active_stage_key"] = ""
    GENERATOR_STATE["stage_started_at"] = {}
    GENERATOR_STATE["stage_completed_at"] = {}
    trace(
        f"Queueing pipeline thread section={section or 'all'} "
        f"reason={reason} force_refresh={force_refresh} "
        f"preserve_visible_sections={preserve_visible_sections or []}"
    )
    target = run_ai_updates_generator if should_use_ai_updates_generator(section, preserve_visible_sections) else run_generator
    if target is run_ai_updates_generator:
        GENERATOR_STATE["sections"] = ["items"]
        trace("Generate routed to SearXNG AI updates pipeline")
    thread = threading.Thread(
        target=target,
        args=(section, force_refresh, preserve_visible_sections),
        daemon=True,
    )
    thread.start()
    message = section_feedback(section) if section else "Fetching more content..."
    return {"success": True, "running": True, "message": message}
