import sys
import time


# Debugging role: Force UTF-8 console output so Arabic logs remain readable.
def configure_console_encoding():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


# Debugging role: Print timestamped backend diagnostics.
def trace(message, prefix="server"):
    stamp = time.strftime("%H:%M:%S")
    print(f"[{prefix} {stamp}] {message}", flush=True)


# Debugging role: Estimate completed generator steps from pipeline logs.
def generator_completed_steps_from_log(log_text, running, last_result, stages):
    total = len(stages)
    if not running and isinstance(last_result, dict) and last_result.get("success"):
        return total

    log_text = (log_text or "").lower()
    completed = 0
    stage_markers = [
        (1, ("parallel fetch collected", "source fetch complete", "fetch sources complete", "memory filter kept")),
        (2, ("memory filter kept", "quality filters complete", "pre_gpt_candidate_prep", "semantic_vector_filter")),
        (3, ("live results to gpt", "gpt selected", "gpt failed", "news selected")),
        (4, ("saving frontend/news.json", "json saved", "saved frontend/news.json")),
        (5, ("supporting content complete", "courses and movies complete", "supporting courses", "supporting movies")),
    ]
    for step_count, markers in stage_markers:
        if any(marker in log_text for marker in markers):
            completed = max(completed, step_count)
    return min(completed, total)


# Debugging role: Map one pipeline log line to a frontend progress stage.
def timeline_stage_key(line):
    text = str(line or "").strip().lower()
    if not text:
        return ""
    if "prefetch" in text or "background courses" in text or "background course" in text:
        return ""
    if (
        "starting news fetch" in text
        or "parallel fetch" in text
        or "source fetch" in text
        or "fetch sources" in text
        or "fetching and processing" in text
        or "product update monitor" in text
        or "sources fetched" in text
    ):
        return "source_fetch"
    if (
        "memory filter" in text
        or "quality filter" in text
        or "semantic" in text
        or "dedup" in text
        or "pre_gpt_candidate_prep" in text
    ):
        return "quality_filter"
    if "gpt" in text or "model" in text or "news selected" in text or "selected " in text:
        return "ai_model"
    if (
        "processing course" in text
        or "processing movie" in text
        or text.startswith("course ")
        or text.startswith("movie ")
        or "supporting content" in text
        or "courses and movies" in text
        or "supporting courses" in text
        or "supporting movies" in text
    ):
        return "supporting"
    if "saving frontend/news.json" in text or "json saved" in text or "saved frontend/news.json" in text:
        return "save"
    if "ready for review" in text or "fetch finished successfully" in text or "newsletter ready" in text:
        return "ready"
    return ""


# Debugging role: Keep only useful generator log lines for the UI timeline.
def is_timeline_worthy_line(line):
    text = str(line or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith("fetching rss news:"):
        return False
    important_tokens = [
        "processing",
        "starting fetch",
        "starting news fetch",
        "fetch finished",
        "fetching and processing",
        "parallel fetch",
        "source fetch",
        "sources fetched",
        "quality filter",
        "product update monitor",
        "after ",
        "semantic",
        "gpt",
        "model",
        "stage timing",
        "supporting content",
        "saving frontend/news.json",
        "json saved",
        "final output count",
        "skipping",
        "source pool cap",
        "rule-based prefilter",
        "runtime budget",
        "background courses",
        "background course",
        "qdrant",
        "http failed",
        "error",
        "warning",
    ]
    return any(token in lowered for token in important_tokens)


# Debugging role: Append one progress entry to the public generator timeline.
def append_generator_timeline(line, generator_state, stage_key_to_index, timeline_limit):
    text = str(line or "").strip()
    if not is_timeline_worthy_line(text):
        return
    now = time.time()
    started_at = generator_state.get("started_at") or now
    elapsed = max(0.0, now - started_at)
    timeline = list(generator_state.get("timeline") or [])
    if timeline and timeline[-1].get("text") == text:
        return
    stage_key = timeline_stage_key(text)
    if stage_key in stage_key_to_index:
        stage_started_at = dict(generator_state.get("stage_started_at") or {})
        stage_completed_at = dict(generator_state.get("stage_completed_at") or {})
        active_stage_key = str(generator_state.get("active_stage_key") or "")
        active_index = stage_key_to_index.get(active_stage_key, -1)
        new_index = stage_key_to_index.get(stage_key, -1)

        if stage_key not in stage_started_at:
            stage_started_at[stage_key] = now
        if active_stage_key and active_stage_key != stage_key and active_stage_key not in stage_completed_at:
            stage_completed_at[active_stage_key] = now
        if new_index > active_index:
            for key, index in stage_key_to_index.items():
                if index < new_index and key in stage_started_at and key not in stage_completed_at:
                    stage_completed_at[key] = now
            generator_state["active_stage_key"] = stage_key

        generator_state["stage_started_at"] = stage_started_at
        generator_state["stage_completed_at"] = stage_completed_at
        generator_state["last_log_tail"] = (str(generator_state.get("last_log_tail") or "") + "\n" + text)[-6000:]
    timeline.append({
        "text": text,
        "elapsed_seconds": round(elapsed, 1),
        "timestamp": time.strftime("%H:%M:%S"),
        "stage_key": stage_key,
        "stage_index": stage_key_to_index.get(stage_key, -1),
    })
    generator_state["timeline"] = timeline[-timeline_limit:]


# Debugging role: Convert numeric diagnostics to float safely.
def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


# Debugging role: Read the latest generator performance payload.
def latest_generator_performance(generator_state, load_fetch_state):
    last_result = generator_state.get("last_result")
    if isinstance(last_result, dict):
        performance = last_result.get("performance")
        if isinstance(performance, dict) and performance:
            return performance
    if generator_state.get("running"):
        return {}
    fetch_state = load_fetch_state()
    run_performance = fetch_state.get("last_run_performance") if isinstance(fetch_state, dict) else {}
    if not isinstance(run_performance, dict):
        return {}
    performance = run_performance.get("performance", {})
    return performance if isinstance(performance, dict) else {}


# Debugging role: Convert pipeline timing diagnostics into per-stage durations.
def generator_stage_duration_map(performance):
    if not isinstance(performance, dict):
        return {}
    durations = {}
    for row in performance.get("stage_durations") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        durations[key] = round(max(0.0, safe_float(row.get("seconds"))), 1)
    fallback_pairs = {
        "source_fetch": "source_fetch_seconds",
        "quality_filter": "filter_seconds",
        "ai_model": "gpt_seconds",
        "supporting": "supporting_content_seconds",
        "save": "save_seconds",
    }
    for stage_key, perf_key in fallback_pairs.items():
        if stage_key not in durations and perf_key in performance:
            durations[stage_key] = round(max(0.0, safe_float(performance.get(perf_key))), 1)
    if "save" not in durations and "news_json_save_seconds" in performance:
        durations["save"] = round(max(0.0, safe_float(performance.get("news_json_save_seconds"))), 1)
    return durations


# Debugging role: Build the progress object consumed by the frontend.
def generator_progress_state(generator_state, stages, stage_key_to_index, load_fetch_state):
    total = len(stages)
    running = bool(generator_state.get("running"))
    last_result = generator_state.get("last_result")
    timeline = list(generator_state.get("timeline") or [])
    performance = latest_generator_performance(generator_state, load_fetch_state)
    duration_map = generator_stage_duration_map(performance)
    now = time.time()
    started_at = generator_state.get("started_at") or now
    finished_at = generator_state.get("finished_at") or now

    stage_started_at = {}
    stage_completed_at = {}
    active_index = 0
    completed = 0

    live_stage_started_at = generator_state.get("stage_started_at")
    live_stage_completed_at = generator_state.get("stage_completed_at")
    if isinstance(live_stage_started_at, dict):
        stage_started_at.update({str(key): safe_float(value) for key, value in live_stage_started_at.items()})
    if isinstance(live_stage_completed_at, dict):
        stage_completed_at.update({str(key): safe_float(value) for key, value in live_stage_completed_at.items()})

    for entry in timeline:
        stage_key = entry.get("stage_key") or ""
        if stage_key not in stage_key_to_index:
            continue
        idx = stage_key_to_index[stage_key]
        if stage_key not in stage_started_at:
            stage_started_at[stage_key] = started_at + float(entry.get("elapsed_seconds") or 0)
        active_index = max(active_index, idx)

    active_stage_key = str(generator_state.get("active_stage_key") or "")
    if active_stage_key in stage_key_to_index:
        active_index = max(active_index, stage_key_to_index[active_stage_key])

    ordered_keys = [stage["key"] for stage in stages]
    for idx, stage_key in enumerate(ordered_keys):
        start_ts = stage_started_at.get(stage_key)
        if start_ts is None:
            continue
        next_ts = None
        for next_key in ordered_keys[idx + 1:]:
            if next_key in stage_started_at:
                next_ts = stage_started_at[next_key]
                break
        stage_completed_at[stage_key] = next_ts or ((finished_at if not running else now) if active_index == idx or not running else None)

    if not running and isinstance(last_result, dict) and last_result.get("success"):
        completed = total
        active_step = total - 1
    else:
        completed = max(
            generator_completed_steps_from_log(
                generator_state.get("last_log_tail", ""),
                running,
                last_result,
                stages,
            ),
            min(active_index, total - 1),
        )
        active_step = min(active_index, total - 1)

    percent = round((completed / total) * 100) if total else 0
    step_states = []
    for idx, stage in enumerate(stages):
        key = stage["key"]
        start_ts = stage_started_at.get(key)
        end_ts = stage_completed_at.get(key)
        elapsed_seconds = 0.0
        if start_ts is not None:
            elapsed_seconds = max(0.0, (end_ts or (now if running and idx == active_step else finished_at)) - start_ts)
        if completed >= total:
            status = "done"
        elif idx < completed:
            status = "done"
        elif idx == active_step:
            status = "active"
        else:
            status = "idle"
        if key in duration_map and (status == "done" or not running):
            elapsed_seconds = duration_map[key]
        step_states.append({
            **stage,
            "status": status,
            "elapsed_seconds": round(elapsed_seconds, 1) if (start_ts is not None or key in duration_map) else None,
        })
    return {
        "source": "backend_log_steps",
        "percent": percent,
        "completed_steps": completed,
        "active_step": active_step,
        "total_steps": total,
        "steps": step_states,
    }


# Debugging role: Build the public generator state API payload.
def generator_public_state(generator_state, stages, stage_key_to_index, load_fetch_state, message_limit):
    last_result = generator_state.get("last_result")
    fetch_state = load_fetch_state()
    run_performance = fetch_state.get("last_run_performance") if isinstance(fetch_state, dict) else {}
    if not isinstance(run_performance, dict):
        run_performance = {}
    current_performance = latest_generator_performance(generator_state, load_fetch_state)
    stored_performance = run_performance.get("performance", {})
    if not isinstance(stored_performance, dict):
        stored_performance = {}
    performance = current_performance if current_performance else ({} if generator_state.get("running") else stored_performance)
    public_result = None
    if isinstance(last_result, dict):
        public_result = {
            "success": bool(last_result.get("success")),
            "message": str(last_result.get("message", "") or "")[:message_limit],
            "running": bool(last_result.get("running", False)),
        }
    return {
        "running": bool(generator_state.get("running")),
        "sections": list(generator_state.get("sections") or []),
        "started_at": generator_state.get("started_at"),
        "finished_at": generator_state.get("finished_at"),
        "last_result": public_result,
        "progress": generator_progress_state(generator_state, stages, stage_key_to_index, load_fetch_state),
        "timeline": list(generator_state.get("timeline") or []),
        "performance": performance,
        "diversity": run_performance.get("diversity", {}),
    }
