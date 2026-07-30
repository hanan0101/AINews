"""News discovery: public orchestration."""

from .common import *
from .queries import *
from .normalization import *
from .searxng import *
from .exa import *
from .merge import *
from .tracker import *

def fetch_news_candidates(*, exclude_items: list[dict] | None = None, target_hint: str = "", single: bool = False, cycle: int = 1) -> tuple[list[dict], dict]:
    """Fetch news candidates from Exa and SearXNG in parallel."""
    started = time.time()
    exa_rows = discovery_rows("exa", single=single, target_hint=target_hint, cycle=cycle)
    searxng_rows = discovery_rows("searxng", single=single, target_hint=target_hint)
    mode = "single_parallel" if single else "full_parallel"
    safe_print(f"[AI Updates] Parallel fetch: exa={len(exa_rows)} searxng={len(searxng_rows)} mode={mode}")
    log_event(
        "source_fetch.plan",
        mode=mode,
        target_hint=target_hint,
        exa_queries=len(exa_rows),
        searxng_queries=len(searxng_rows),
        exa_query_sample=[row.get("query") for row in exa_rows[:8]],
        searxng_query_sample=[row.get("query") for row in searxng_rows[:8]],
        tool_discovery=dict(LAST_DISCOVERY_META),
        query_angles={
            source: meta.get("query_angle")
            for source, meta in LAST_DISCOVERY_META.items()
            if meta.get("query_angle")
        },
    )
    source_results = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(fetch_exa_query_rows, exa_rows, exclude_items=exclude_items, single=single): "exa",
            executor.submit(fetch_searxng_query_rows, searxng_rows, exclude_items=exclude_items, single=single): "searxng",
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                items, diagnostics = future.result()
            except Exception as exc:
                items, diagnostics = [], {"source": source, "error": f"{source}_fetch_exception", "exception": str(exc), "queries": 0, "raw_results": 0}
            source_results.append((source, items, diagnostics))
    items, diagnostics = combine_source_results(source_results, mode=mode)
    primary_unique_results = len(items)
    tracker_threshold = AI_UPDATES_TRACKER_RUN_WHEN_PRIMARY_BELOW
    tracker_should_run = (
        not single
        and AI_UPDATES_TRACKER_DISCOVERY_LAYER_ENABLED
        and primary_unique_results < tracker_threshold
    )
    if not single and AI_UPDATES_TRACKER_DISCOVERY_LAYER_ENABLED and not tracker_should_run:
        diagnostics["tracker_discovery_layer"] = {
            "enabled": True,
            "skipped": True,
            "skip_reason": "primary_candidates_above_threshold",
            "primary_unique_results": primary_unique_results,
            "run_when_primary_below": tracker_threshold,
        }
        log_event(
            "tracker_discovery_layer.skipped",
            reason="primary_candidates_above_threshold",
            primary_unique_results=primary_unique_results,
            run_when_primary_below=tracker_threshold,
        )
    if tracker_should_run:
        tracker_items, tracker_diagnostics = fetch_tracker_discovery_layer(exclude_items=exclude_items)
        merged_items, _ = combine_source_results(
            [
                ("tool_driven", items, {"raw_results": 0, "queries": 0}),
                ("tracker_discovery_layer", tracker_items, {"raw_results": 0, "queries": 0}),
            ],
            mode=f"{mode}_merged_tracker_discovery_layer",
        )
        items = merged_items
        diagnostics["raw_results"] = int(diagnostics.get("raw_results") or 0) + int(tracker_diagnostics.get("raw_results") or 0)
        diagnostics["queries"] = int(diagnostics.get("queries") or 0) + int(tracker_diagnostics.get("queries") or 0)
        diagnostics["unique_results"] = len(items)
        diagnostics.setdefault("source_diagnostics", {})["tracker_discovery_layer"] = tracker_diagnostics
        diagnostics.setdefault("source_failures", {}).update(tracker_diagnostics.get("source_failures") or {})
        diagnostics["tracker_discovery_layer"] = {
            "enabled": True,
            "queries": tracker_diagnostics.get("queries", 0),
            "raw_results": tracker_diagnostics.get("raw_results", 0),
            "unique_results": tracker_diagnostics.get("unique_results", 0),
            "layer_counts": tracker_diagnostics.get("layer_counts", {}),
            "seconds": tracker_diagnostics.get("tracker_discovery_layer_seconds", 0),
        }
        diagnostics["source_candidate_counts"] = dict(Counter(item.get("fetch_source") or "unknown" for item in items))
    # General layer merge: full weekly generation adds non-tool-list AI news
    # after the existing tool-driven fetch, then deduplicates by URL/title
    # before the shared quality and LLM filtering stages.
    # CHANGE: GENERAL_NEWS_EXA_ROWS/GENERAL_NEWS_SEARXNG_ROWS are fixed query
    # text with no per-cycle variable (same root cause as the
    # EXA_PRODUCT_UPDATE_BROAD_QUERIES fix above) - verified live 2026-07-11
    # that general_news_layer.finished logged byte-identical raw_results (239),
    # unique_results (23), and domain_allowlist_rejected (98) on both cycle 1
    # and cycle 2 of the same run. Only run it on the first cycle.
    if not single and AI_UPDATES_GENERAL_NEWS_LAYER_ENABLED and cycle <= 1:
        general_items, general_diagnostics = fetch_general_news_layer(exclude_items=exclude_items)
        merged_items, _ = combine_source_results(
            [
                ("tool_driven", items, {"raw_results": 0, "queries": 0}),
                ("general_news_layer", general_items, {"raw_results": 0, "queries": 0}),
            ],
            mode=f"{mode}_merged_general_layer",
        )
        items = merged_items
        diagnostics["raw_results"] = int(diagnostics.get("raw_results") or 0) + int(general_diagnostics.get("raw_results") or 0)
        diagnostics["queries"] = int(diagnostics.get("queries") or 0) + int(general_diagnostics.get("queries") or 0)
        diagnostics["unique_results"] = len(items)
        diagnostics.setdefault("source_diagnostics", {})["general_news_layer"] = general_diagnostics
        diagnostics.setdefault("source_failures", {}).update(general_diagnostics.get("source_failures") or {})
        diagnostics["general_news_layer"] = {
            "enabled": True,
            "queries": general_diagnostics.get("queries", 0),
            "raw_results": general_diagnostics.get("raw_results", 0),
            "unique_results": general_diagnostics.get("unique_results", 0),
            "layer_counts": general_diagnostics.get("layer_counts", {}),
            "seconds": general_diagnostics.get("general_news_layer_seconds", 0),
        }
        diagnostics["source_candidate_counts"] = dict(Counter(item.get("fetch_source") or "unknown" for item in items))
    diagnostics["tool_discovery"] = dict(LAST_DISCOVERY_META)
    diagnostics["tool_group_counts"] = {
        source: meta.get("tool_group_counts", {})
        for source, meta in LAST_DISCOVERY_META.items()
    }
    diagnostics["query_mix_counts"] = {
        source: meta.get("query_mix", {})
        for source, meta in LAST_DISCOVERY_META.items()
    }
    diagnostics["parallel_fetch_seconds"] = round(time.time() - started, 2)
    safe_print(f"[AI Updates] Parallel fetch collected unique={len(items)} raw={diagnostics.get('raw_results')} seconds={diagnostics['parallel_fetch_seconds']}")
    log_event(
        "source_fetch.finished",
        mode=mode,
        raw_results=diagnostics.get("raw_results"),
        unique_results=len(items),
        seconds=diagnostics["parallel_fetch_seconds"],
        source_candidate_counts=diagnostics.get("source_candidate_counts", {}),
        source_failures=diagnostics.get("source_failures", {}),
        source_failures_detail=diagnostics.get("source_failures_detail", {}),
        tool_group_counts=diagnostics.get("tool_group_counts", {}),
        query_mix_counts=diagnostics.get("query_mix_counts", {}),
    )
    return items, diagnostics

__all__ = [name for name in globals() if not name.startswith("__")]
