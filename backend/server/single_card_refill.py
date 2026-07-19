# This file is part of the AI newsletter system.
"""Single-card refill orchestration and live progress state."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from backend.utils.debug_logging import trace
from backend.server.card_items import dedupe_store_items, normalize_item
from backend.storage.newsletter_store import (
    SECTION_KEYS,
    SECTION_TO_CONTENT_TYPE,
    client_visible_items,
    load_store,
    reorder_positions,
    safe_int,
    save_store,
    section_visible_index,
    update_card_at_index,
    visible_items,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env", override=True)

SINGLE_REFILL_LOCK = threading.Lock()
SINGLE_REFILL_STATE_LOCK = threading.Lock()
SINGLE_REFILL_SECONDS = int(os.getenv("SINGLE_REFILL_SECONDS", "45") or "45")
SINGLE_REFILL_SUPPORTING_TARGET = max(1, int(os.getenv("SINGLE_REFILL_SUPPORTING_TARGET", "2") or "2"))
SINGLE_REFILL_FAST_MODE = os.getenv("SINGLE_REFILL_FAST_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
if SINGLE_REFILL_FAST_MODE:
    SINGLE_REFILL_SECONDS = min(SINGLE_REFILL_SECONDS, 35)

USE_AI_UPDATES_PIPELINE_FOR_SINGLE_REFILL = os.getenv("USE_AI_UPDATES_PIPELINE_FOR_SINGLE_REFILL", "1").strip().lower() in {"1", "true", "yes", "on"}

from backend.pipeline.orchestrator import run_single_supporting_pipeline as run_ai_updates_single_supporting_pipeline
from backend.pipeline.orchestrator import run_single_update_pipeline as run_ai_updates_single_pipeline

SINGLE_REFILL_STATE = {
    "running": False,
    "section": "",
    "index": -1,
    "started_at": None,
    "finished_at": None,
    "refill": None,
    "refill_stages": [],
}


# Performs the refill response state helper step.
def refill_response_state(stage, success=False, started_at=None, angle=None, reason=""):
    elapsed = round(time.time() - started_at, 1) if started_at else 0
    return {
        "stage": stage,
        "success": success,
        "elapsed_seconds": elapsed,
        "angle": angle or "",
        "reason": reason,
        "target_seconds": SINGLE_REFILL_SECONDS,
    }


# Performs the publish single refill state helper step.
def publish_single_refill_state(section, index, stages, started_at, running=True):
    stages = list(stages or [])
    with SINGLE_REFILL_STATE_LOCK:
        SINGLE_REFILL_STATE.update({
            "running": bool(running),
            "section": section or "",
            "index": index if isinstance(index, int) else -1,
            "started_at": started_at,
            "finished_at": None if running else time.time(),
            "refill": stages[-1] if stages else None,
            "refill_stages": stages,
        })


# Reads current single refill state from the current store or request context.
def current_single_refill_state():
    with SINGLE_REFILL_STATE_LOCK:
        return dict(SINGLE_REFILL_STATE)


# Saves append single refill stage to the configured output or state store.
def append_single_refill_stage(stages, section, index, started_at, stage, success=False, angle=None, reason="", running=True):
    stages.append(refill_response_state(stage, success, started_at, angle=angle, reason=reason))
    publish_single_refill_state(section, index, stages, started_at, running=running)
    return stages[-1]


# Reads current exclusion items from the current store or request context.
def current_exclusion_items(store, section, target_id=None, extra_exclude=None, visible_exclude=None):
    # News replacement can start from card 5/6 in the toolbar view, so compare
    # against the same client-visible pool instead of only the default 4 cards.
    source_items = visible_exclude if isinstance(visible_exclude, list) else client_visible_items(store, section)
    current = [
        item for item in source_items
        if isinstance(item, dict)
        if not target_id or item.get("id") != target_id
    ]
    current.extend(item for item in (extra_exclude or []) if isinstance(item, dict))
    return current


# Prepares normalize generated refill item so downstream stages receive consistent data.
def normalize_generated_refill_item(item, section):
    normalized = normalize_item(item, SECTION_TO_CONTENT_TYPE.get(section, "news"))
    if not normalized.get("id") or normalized["id"].startswith(("news-", "course-", "movie-")):
        raw = f"{normalized.get('type')}|{normalized.get('title')}|{normalized.get('url')}"
        normalized["id"] = hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()
    return normalized


# Builds apply single refill for the next pipeline or API step.
def apply_single_refill(store, section, index, item, target_id=None):
    original_visible = list(visible_items(store, section))
    original_visible_count = len(original_visible)
    target_item = next((entry for entry in store.get(section, []) if entry.get("id") == target_id), None)
    normalized = normalize_generated_refill_item(item, section)
    saved_item = update_card_at_index(store, section, index, normalized)
    if target_item and not any(entry.get("id") == target_item.get("id") for entry in store.get(section, [])):
        archived_target = normalize_item(dict(target_item), SECTION_TO_CONTENT_TYPE.get(section, "news"))
        archived_target["status"] = "replaced_archive"
        store[section] = reorder_positions(dedupe_store_items(list(store.get(section, [])) + [archived_target]))
    save_store(store)
    refreshed = load_store()
    if len(visible_items(refreshed, section)) != original_visible_count:
        trace(
            "single refill visible-count changed unexpectedly after replace: "
            f"before={original_visible_count} after={len(visible_items(refreshed, section))}"
        )
    return refreshed, saved_item


# Performs the try ai updates single refill helper step.
def try_ai_updates_single_refill(store, section, index, action, item_id, target_item, current_items, stages, started, requested_level=""):
    if not (
        section == "items"
        and USE_AI_UPDATES_PIPELINE_FOR_SINGLE_REFILL
        and run_ai_updates_single_pipeline is not None
    ):
        return None
    append_single_refill_stage(stages, section, index, started, "source_fetch", angle="ai_updates_single", reason="modular_single_pipeline")
    exclude_items = list(current_items or [])
    if target_item:
        exclude_items.append(target_item)
    trace("single refill routed to modular AI updates pipeline")
    try:
        report = run_ai_updates_single_pipeline(exclude_items=exclude_items)
    except Exception as exc:
        trace(f"single refill modular AI updates pipeline failed: {exc}")
        report = {"success": False, "error": "single_pipeline_exception", "exception": str(exc)}

    performance = report.get("performance") if isinstance(report, dict) else {}
    append_single_refill_stage(
        stages,
        section,
        index,
        started,
        "quality_check",
        angle="ai_updates_single",
        reason=(
            f"{safe_int(performance.get('selected_count'))}/"
            f"{safe_int(performance.get('valid_candidates'))} valid "
            f"{float(performance.get('total_seconds') or 0):.1f}s"
        ),
    )
    selected = list(report.get("news_items") or []) if isinstance(report, dict) else []
    if selected:
        final_item = normalize_generated_refill_item(selected[0], section)
        append_single_refill_stage(stages, section, index, started, "duplicate_check", angle="ai_updates_single", reason="ok")
        append_single_refill_stage(stages, section, index, started, "updating_card", angle="ai_updates_single", reason="fresh_modular")
        store, item = apply_single_refill(store, section, index, final_item, item_id)
        completed = append_single_refill_stage(
            stages,
            section,
            index,
            started,
            "completed",
            True,
            angle="ai_updates_single",
            reason=f"{float(performance.get('total_seconds') or 0):.1f}s",
            running=False,
        )
        return store, {
            "success": True,
            "index": index,
            "item": item,
            "replacement_source": "single_refill:ai_updates_single",
            "refill": completed,
            "refill_stages": stages,
            "performance": performance,
        }

    reject_reason = "single_pipeline_no_model_item"
    append_single_refill_stage(stages, section, index, started, "failed", False, angle="ai_updates_single", reason=reject_reason, running=False)
    return store, {
        "success": False,
        "needs_fetch": False,
        "running": False,
        "index": index,
        "message": "لم يتم العثور على خبر مناسب من مسار الجلب الموحد ضمن الوقت القصير. لم يتم استخدام الأخبار المحفوظة كبديل.",
        "refill": stages[-1],
        "refill_stages": stages,
        "diagnostics": {
            "reason": reject_reason,
            "performance": performance,
            "error": report.get("error") if isinstance(report, dict) else "",
        },
    }


# Performs the try ai updates supporting single refill helper step.
def try_ai_updates_supporting_single_refill(store, section, index, action, item_id, current_items, stages, started, requested_level=""):
    if section not in {"courses", "movies"}:
        return None
    content_type = SECTION_TO_CONTENT_TYPE.get(section)
    if section == "movies":
        requested_level = ""
    if run_ai_updates_single_supporting_pipeline is None:
        return store, {
            "success": False,
            "needs_fetch": False,
            "running": False,
            "index": index,
            "message": "المسار الجديد للكورسات والأفلام غير متاح حاليًا.",
            "refill": refill_response_state("failed", False, started, angle="ai_updates_supporting", reason="modular_supporting_pipeline_unavailable"),
            "refill_stages": stages,
        }

    append_single_refill_stage(stages, section, index, started, "source_fetch", angle="ai_updates_supporting", reason=content_type)
    try:
        report = run_ai_updates_single_supporting_pipeline(
            content_type,
            exclude_items=current_items or [],
            target_count=SINGLE_REFILL_SUPPORTING_TARGET,
            requested_level=requested_level,
        )
    except Exception as exc:
        trace(f"single refill modular supporting pipeline failed: {exc}")
        report = {"success": False, "error": "single_supporting_pipeline_exception", "exception": str(exc), "cards": []}

    performance = report.get("performance") if isinstance(report, dict) else {}
    append_single_refill_stage(
        stages,
        section,
        index,
        started,
        "quality_check",
        angle="ai_updates_supporting",
        reason=(
            f"{safe_int(performance.get('selected_count'))}/"
            f"{safe_int(performance.get('valid_candidates'))} valid "
            f"{float(performance.get('total_seconds') or 0):.1f}s"
        ),
    )
    selected = list(report.get("cards") or []) if isinstance(report, dict) else []
    append_single_refill_stage(stages, section, index, started, "preparing_content", angle="ai_updates_supporting", reason=f"{len(selected or [])}/1")

    if selected:
        normalized = normalize_generated_refill_item(selected[0], section)
        append_single_refill_stage(stages, section, index, started, "duplicate_check", angle="ai_updates_supporting", reason="ok")
        append_single_refill_stage(stages, section, index, started, "updating_card", angle="ai_updates_supporting", reason="fresh_modular")
        store, item = apply_single_refill(store, section, index, normalized, item_id)
        completed = append_single_refill_stage(stages, section, index, started, "completed", True, angle="ai_updates_supporting", reason="fresh_modular", running=False)
        return store, {
            "success": True,
            "index": index,
            "item": item,
            "replacement_source": f"single_refill:ai_updates_{content_type}",
            "refill": completed,
            "refill_stages": stages,
            "performance": performance,
        }

    reject_reason = "supporting_pipeline_no_model_item"
    failed = append_single_refill_stage(stages, section, index, started, "failed", False, angle="ai_updates_supporting", reason=reject_reason, running=False)
    return store, {
        "success": False,
        "needs_fetch": False,
        "running": False,
        "index": index,
        "message": "لم يتم العثور على بديل مناسب من المسار الجديد ضمن الوقت القصير.",
        "refill": failed,
        "refill_stages": stages,
        "diagnostics": {
            "reason": reject_reason,
            "raw_candidates": safe_int(performance.get("raw_candidates")),
            "filtered_candidates": safe_int(performance.get("valid_candidates")),
            "performance": performance,
            "error": report.get("error") if isinstance(report, dict) else "",
        },
    }


# Performs the single item refill helper step.
def single_item_refill(store, section, item_id=None, index=None, action="replace", extra_exclude=None, visible_exclude=None, allow_fetch=False, live_fetch=False, requested_level=""):
    started = time.time()
    if not SINGLE_REFILL_LOCK.acquire(blocking=False):
        safe_index = index if isinstance(index, int) else -1
        return store, {
            "success": False,
            "running": True,
            "index": safe_index,
            "message": "جاري البحث عن بديل آخر. يرجى الانتظار قليلًا.",
            "refill": refill_response_state("searching", started_at=started, reason="single_refill_busy"),
            "refill_stages": [refill_response_state("searching", started_at=started, reason="single_refill_busy")],
        }
    try:
        return _single_item_refill_impl(store, section, item_id=item_id, index=index, action=action, extra_exclude=extra_exclude, visible_exclude=visible_exclude, allow_fetch=allow_fetch, live_fetch=live_fetch, requested_level=requested_level)
    finally:
        SINGLE_REFILL_LOCK.release()


# Performs the single item refill impl helper step.
def _single_item_refill_impl(store, section, item_id=None, index=None, action="replace", extra_exclude=None, visible_exclude=None, allow_fetch=False, live_fetch=False, requested_level=""):
    started = time.time()
    stages = [refill_response_state("searching", started_at=started, reason="single_pipeline_fetch_one")]
    if section not in SECTION_KEYS:
        publish_single_refill_state(section, index if isinstance(index, int) else -1, stages, started, running=False)
        return store, {"success": False, "error": "Invalid refill section", "refill": stages[-1]}

    if index is None or index < 0:
        index = section_visible_index(store, section, item_id) if item_id else len(visible_items(store, section))
    publish_single_refill_state(section, index, stages, started, running=True)
    if index < 0:
        publish_single_refill_state(section, index, stages, started, running=False)
        return store, {"success": False, "error": "Content item not found", "index": -1, "refill": stages[-1]}

    # Use the UI-visible replacement pool so item_id/index from the 6-card
    # toolbar view maps to the intended stored news card.
    visible = client_visible_items(store, section)
    target_item = None
    if item_id:
        target_item = next((item for item in visible if item.get("id") == item_id), None)
    if target_item is None and 0 <= index < len(visible):
        target_item = visible[index]
    if target_item:
        item_id = target_item.get("id") or item_id
    current_items = current_exclusion_items(
        store,
        section,
        target_id=item_id,
        extra_exclude=extra_exclude,
        visible_exclude=visible_exclude,
    )

    if section == "items" and USE_AI_UPDATES_PIPELINE_FOR_SINGLE_REFILL:
        fast_result = try_ai_updates_single_refill(
            store,
            section,
            index,
            action,
            item_id,
            target_item,
            current_items,
            stages,
            started,
            requested_level=requested_level,
        )
        if fast_result is not None:
            return fast_result

    if section in {"courses", "movies"}:
        supporting_result = try_ai_updates_supporting_single_refill(
            store,
            section,
            index,
            action,
            item_id,
            current_items,
            stages,
            started,
        )
        if supporting_result is not None:
            return supporting_result

    if section == "items":
        failed = append_single_refill_stage(stages, section, index, started, "failed", False, reason="modular_single_pipeline_unavailable", running=False)
        return store, {
            "success": False,
            "needs_fetch": False,
            "running": False,
            "index": index,
            "message": "مسار الاستبدال الجديد غير متاح، ولم يتم استخدام المولد القديم.",
            "refill": failed,
            "refill_stages": stages,
        }

    failed = append_single_refill_stage(stages, section, index, started, "failed", False, reason="modular_supporting_pipeline_no_selection", running=False)
    return store, {
        "success": False,
        "needs_fetch": False,
        "running": False,
        "index": index,
        "message": "لم يتم العثور على بديل مناسب من المسار الجديد، ولم يتم استخدام المولد القديم.",
        "refill": failed,
        "refill_stages": stages,
    }

