"""Full accept/reject funnel audit for one real news fetch (no model calls).

Unlike test_fetch_performance.py (which only kept aggregate rejection
counts), this traces every single post-fetch-dedup candidate through the
real production functions - editorial rules, freshness check, exact-memory
dedupe, scan-pool ranking, GPT shortlist - and records a verdict + reason
for EVERY item, not just the ones that survived. It does this by wrapping
the real editorial_rules.production_news_reject_reason and
memory.news_candidate_is_recent functions (so the actual production logic
runs unmodified), not by reimplementing the rules.

Zero model calls: same three guards as test_fetch_performance.py
(AI_UPDATES_SEMANTIC_MEMORY_ENABLED=0, tools_aware.maintain_monthly_tool_files
stubbed, generate_json/embed_texts blocked on every client).

Usage:
    python scripts/analyze_news_funnel.py
    python scripts/analyze_news_funnel.py --cycles 2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ["AI_UPDATES_SEMANTIC_MEMORY_ENABLED"] = "0"


def safe_print(message: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(str(message).encode(encoding, errors="backslashreplace").decode(encoding, errors="replace"), flush=True)


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.logging.pipeline_logging import new_run_id, set_run_context  # noqa: E402
from backend.pipeline.fetching.news import fetch_news_candidates  # noqa: E402
from backend.pipeline.orchestrator import (  # noqa: E402
    _merge_candidate_pools,
    _merge_cycle_diagnostics,
    build_large_scan_pool,
    shortlist_scan_pool_for_gpt,
    candidate_source_lane,
)
from backend.pipeline.modeling.prompts.news_prompt import build_news_selection_prompt  # noqa: E402

import backend.pipeline.filtering.memory as memory_module  # noqa: E402
import backend.pipeline.filtering.editorial_rules as editorial_rules_module  # noqa: E402
import backend.pipeline.modeling.model_client as model_client  # noqa: E402
import backend.pipeline.modeling.gemini_client as gemini_client  # noqa: E402
import backend.pipeline.modeling.openai_client as openai_client  # noqa: E402
import backend.pipeline.tool_discovery.tools_aware as tools_aware  # noqa: E402

BLOCKED_MODEL_CALLS: list[str] = []


def _block(label: str):
    def _blocked(*_args, **_kwargs):
        BLOCKED_MODEL_CALLS.append(label)
        raise RuntimeError(f"analyze_news_funnel tried to call the model via {label}()")
    return _blocked


def install_guards() -> None:
    model_client.generate_json = _block("model_client.generate_json")
    model_client.embed_texts = _block("model_client.embed_texts")
    gemini_client.generate_json = _block("gemini_client.generate_json")
    gemini_client.embed_texts = _block("gemini_client.embed_texts")
    openai_client.generate_json = _block("openai_client.generate_json")
    openai_client.embed_texts = _block("openai_client.embed_texts")
    tools_aware.generate_json = _block("tools_aware.generate_json")
    tools_aware.maintain_monthly_tool_files = lambda **_kwargs: None


# --- instrumentation: wrap the REAL rule functions, don't reimplement them ---
EDITORIAL_LOG: dict[int, str] = {}   # audit_id -> reason ("" = passed)
FRESHNESS_LOG: dict[int, bool] = {}  # audit_id -> is_recent


def install_tracers() -> None:
    real_reject_reason = editorial_rules_module.production_news_reject_reason
    real_is_recent = memory_module.news_candidate_is_recent

    def traced_reject_reason(item: dict) -> str:
        reason = real_reject_reason(item)
        audit_id = item.get("_audit_id")
        if audit_id is not None:
            EDITORIAL_LOG[audit_id] = reason
        return reason

    def traced_is_recent(item: dict) -> bool:
        result = real_is_recent(item)
        audit_id = item.get("_audit_id")
        if audit_id is not None:
            FRESHNESS_LOG[audit_id] = result
        return result

    memory_module.production_news_reject_reason = traced_reject_reason
    memory_module.news_candidate_is_recent = traced_is_recent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Full news candidate funnel audit.")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--output", default="", help="Override output JSON path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cycles = max(1, min(2, args.cycles))

    install_guards()
    install_tracers()
    run_id = new_run_id("news-funnel-audit")
    set_run_context(run_id, "news_funnel_audit")

    safe_print(f"News funnel audit - run_id={run_id} cycles={cycles}")

    candidates: list[dict] = []
    diagnostics: dict = {}
    started = time.time()
    for cycle in range(1, cycles + 1):
        cycle_candidates, cycle_diag = fetch_news_candidates(cycle=cycle)
        candidates = _merge_candidate_pools(candidates, cycle_candidates)
        diagnostics = _merge_cycle_diagnostics(diagnostics, cycle_diag, cycle, len(candidates))
    fetch_seconds = time.time() - started
    unique_after_fetch = len(candidates)  # captured BEFORE filtering overwrites diagnostics["unique_results"]
    safe_print(f"Fetched {unique_after_fetch} unique candidates (post source-dedup) in {fetch_seconds:.1f}s")

    for index, item in enumerate(candidates):
        item["_audit_id"] = index

    # Import here (after tracers installed) so the module-level bare-name
    # lookups inside filter_candidates resolve to the wrapped functions.
    from backend.pipeline.filtering.news import filter_news_candidates

    t0 = time.time()
    filtered = filter_news_candidates(candidates, diagnostics, single=False)
    filter_seconds = time.time() - t0
    filtered_ids = {item.get("_audit_id") for item in filtered}

    scan_pool = build_large_scan_pool(filtered, diagnostics)
    scan_pool_ids = {item.get("_audit_id") for item in scan_pool}
    shortlist = shortlist_scan_pool_for_gpt(scan_pool, diagnostics)
    shortlist_ids = {item.get("_audit_id") for item in shortlist}

    rows = []
    for item in candidates:
        audit_id = item.get("_audit_id")
        editorial_reason = EDITORIAL_LOG.get(audit_id, "")
        is_fresh = FRESHNESS_LOG.get(audit_id)
        survived_filter = audit_id in filtered_ids
        if editorial_reason:
            stage = "editorial_rules"
            reason = editorial_reason
        elif is_fresh is False:
            stage = "freshness"
            reason = "old_news_skipped"
        elif not survived_filter:
            stage = "memory_dedupe"
            reason = "duplicate_or_memory_match"
        elif audit_id in shortlist_ids:
            stage = "selected_for_model"
            reason = ""
        elif audit_id in scan_pool_ids:
            stage = "scan_pool_not_shortlisted"
            reason = "lower_rank_than_shortlist_cutoff"
        else:
            stage = "unknown"
            reason = "not_in_scan_pool"
        rows.append({
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "source_domain": item.get("source_domain") or "",
            "company": item.get("company") or "",
            "tool": item.get("tool") or "",
            "source_lane": candidate_source_lane(item),
            "query_mix": item.get("query_mix") or "",
            "published_date": item.get("published_date") or "",
            "content": (item.get("content") or item.get("summary") or "")[:500],
            "verdict": "accepted_shortlisted" if stage == "selected_for_model" else "rejected",
            "stage": stage,
            "reason": reason,
        })

    accepted = [row for row in rows if row["verdict"] == "accepted_shortlisted"]
    rejected = [row for row in rows if row["verdict"] == "rejected"]
    reason_counts: dict[str, int] = {}
    for row in rejected:
        reason_counts[row["reason"]] = reason_counts.get(row["reason"], 0) + 1

    safe_print(f"Filter: {filter_seconds:.1f}s -> filtered={len(filtered)} scan_pool={len(scan_pool)} shortlist={len(shortlist)}")
    safe_print(f"TOTAL: {len(rows)} candidates -> {len(accepted)} accepted/shortlisted, {len(rejected)} rejected")
    safe_print("Rejection reasons:")
    for reason, count in sorted(reason_counts.items(), key=lambda pair: -pair[1]):
        safe_print(f"  {reason}: {count}")

    output_path = Path(args.output) if args.output else PROJECT_DIR / "data" / "news" / "news_funnel_audit.json"
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "run_id": run_id,
        "cycles": cycles,
        "fetch_seconds": round(fetch_seconds, 2),
        "filter_seconds": round(filter_seconds, 2),
        "unique_after_fetch": unique_after_fetch,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "rejection_reason_counts": reason_counts,
        "selection_prompt": build_news_selection_prompt(50, single=False, batch_mode=False),
        "candidates": rows,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    safe_print(f"Saved full funnel audit to {output_path}")
    if BLOCKED_MODEL_CALLS:
        safe_print(f"!! MODEL GUARD TRIGGERED: {BLOCKED_MODEL_CALLS}")
    else:
        safe_print("Model calls made: 0 (confirmed by guard)")


if __name__ == "__main__":
    main()
