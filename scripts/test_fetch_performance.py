"""Fetch-only performance test for the news/course/movie pipeline.

Runs the REAL fetch + filter stages for every content type (news, courses,
movies) against live Exa / SearXNG / TMDb, and stops exactly at the point
where candidates would be handed to the selection model - i.e. right before
`select_news_updates()` / `select_supporting_content_cards()` would be
called. Reports timing and candidate-count breakdowns per stage/source so
fetch performance can be analyzed without spending any model quota.

Guarantees zero model calls:
- AI_UPDATES_SEMANTIC_MEMORY_ENABLED is forced to "0" before
  backend.config.settings loads, so the embedding call inside
  filter_candidates() (backend/pipeline/filtering/memory.py) never fires.
- The monthly AI-tool registry refresh (tools_aware.maintain_monthly_tool_files,
  which can call Gemini to extract/validate newly discovered tools as a side
  effect of building this run's tool-driven queries) is stubbed to a no-op;
  the existing registry already on disk is used as-is, same as any day that
  doesn't need a refresh.
- generate_json/embed_texts on every provider client (model_client,
  gemini_client, openai_client, and tools_aware's direct import of
  gemini_client.generate_json) are wrapped to raise immediately instead of
  making a live call, so any code path this script didn't anticipate fails
  loud instead of silently spending quota.

Usage:
    python scripts/test_fetch_performance.py
    python scripts/test_fetch_performance.py --types news,courses
    python scripts/test_fetch_performance.py --cycles 2 --save
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Must happen before backend.config.settings is imported anywhere (it reads
# this env var at import time) - see module docstring above.
os.environ["AI_UPDATES_SEMANTIC_MEMORY_ENABLED"] = "0"


def safe_print(message: str) -> None:
    """Print safely on narrow Windows console encodings (mirrors news_discovery.safe_print)."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(str(message).encode(encoding, errors="backslashreplace").decode(encoding, errors="replace"), flush=True)


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config.settings import (  # noqa: E402
    DISPLAY_COUNTS,
    EXA_API_KEY,
    SEARXNG_URL,
    SUPPORTING_COURSE_FETCH_POOL,
    SUPPORTING_MOVIE_FETCH_POOL,
    TMDB_API_KEY,
)
from backend.logging.pipeline_logging import new_run_id, set_run_context  # noqa: E402
from backend.pipeline.fetching.news import fetch_news_candidates  # noqa: E402
from backend.pipeline.filtering.news import filter_news_candidates  # noqa: E402
from backend.pipeline.orchestrator import (  # noqa: E402
    _merge_candidate_pools,
    _merge_cycle_diagnostics,
    build_large_scan_pool,
    shortlist_scan_pool_for_gpt,
)
from backend.pipeline.fetching.courses import fetch_course_candidates  # noqa: E402
from backend.pipeline.fetching.films import fetch_movie_candidates  # noqa: E402
from backend.pipeline.filtering.supporting import filter_supporting_candidates  # noqa: E402
from backend.pipeline.modeling.selection import compact_model_candidate  # noqa: E402
from backend.pipeline.modeling.supporting import compact_supporting_candidate  # noqa: E402

import backend.pipeline.modeling.model_client as model_client  # noqa: E402
import backend.pipeline.modeling.gemini_client as gemini_client  # noqa: E402
import backend.pipeline.modeling.openai_client as openai_client  # noqa: E402
import backend.pipeline.tool_discovery.tools_aware as tools_aware  # noqa: E402


BLOCKED_MODEL_CALLS: list[str] = []


def _block(label: str):
    def _blocked(*_args, **_kwargs):
        BLOCKED_MODEL_CALLS.append(label)
        raise RuntimeError(
            f"fetch-performance test tried to call the model via {label}() - "
            "this script must never reach the model."
        )
    return _blocked


def install_model_guards() -> None:
    """Block every known path to a real model call; see module docstring."""
    model_client.generate_json = _block("model_client.generate_json")
    model_client.embed_texts = _block("model_client.embed_texts")
    gemini_client.generate_json = _block("gemini_client.generate_json")
    gemini_client.embed_texts = _block("gemini_client.embed_texts")
    openai_client.generate_json = _block("openai_client.generate_json")
    openai_client.embed_texts = _block("openai_client.embed_texts")
    # tools_aware imported gemini_client.generate_json by name at module load,
    # so patching gemini_client.generate_json above does not reach it.
    tools_aware.generate_json = _block("tools_aware.generate_json")
    # This is what would actually trigger the tools_aware Gemini calls above
    # (tool extraction/validation runs as a side effect of building this
    # run's tool-driven Exa/SearXNG queries) - skip it and use today's
    # existing registry on disk, exactly like a day that isn't due a refresh.
    tools_aware.maintain_monthly_tool_files = lambda **_kwargs: None


def fetch_news_stage(cycles: int) -> dict:
    candidates: list[dict] = []
    diagnostics: dict = {}
    fetch_seconds = 0.0
    filter_seconds = 0.0
    started = time.time()
    for cycle in range(1, cycles + 1):
        t0 = time.time()
        cycle_candidates, cycle_diag = fetch_news_candidates(cycle=cycle)
        fetch_seconds += time.time() - t0
        candidates = _merge_candidate_pools(candidates, cycle_candidates)
        diagnostics = _merge_cycle_diagnostics(diagnostics, cycle_diag, cycle, len(candidates))

    t0 = time.time()
    filtered = filter_news_candidates(candidates, diagnostics, single=False)
    scan_pool = build_large_scan_pool(filtered, diagnostics)
    shortlist = shortlist_scan_pool_for_gpt(scan_pool, diagnostics)
    filter_seconds += time.time() - t0

    source_diag = diagnostics.get("source_diagnostics") if isinstance(diagnostics.get("source_diagnostics"), dict) else {}
    source_breakdown = {}
    for source, diag in source_diag.items():
        if not isinstance(diag, dict):
            continue
        source_breakdown[source] = {
            "queries": diag.get("queries", 0),
            "raw_results": diag.get("raw_results", 0),
            "unique_results": diag.get("unique_results", 0),
            "seconds": round(float(diag.get("seconds") or 0), 2),
            "error": diag.get("error"),
            "error_count": len(diag.get("errors") or []),
        }

    return {
        "type": "news",
        "cycles_run": cycles,
        "fetch_seconds": round(fetch_seconds, 2),
        "filter_seconds": round(filter_seconds, 2),
        "total_seconds": round(time.time() - started, 2),
        "raw_candidates": diagnostics.get("raw_results", 0),
        "unique_after_fetch": diagnostics.get("unique_results", len(candidates)),
        "filtered_candidates": len(filtered),
        "scan_pool_count": len(scan_pool),
        "candidates_entering_model": len(shortlist),
        "source_breakdown": source_breakdown,
        "source_lane_counts_in_shortlist": (diagnostics.get("large_scan") or {}).get("gpt_shortlist_source_lane_counts", {}),
        "editorial_rule_rejected": diagnostics.get("editorial_rule_rejected", {}),
        "old_news_skipped": diagnostics.get("old_news_skipped", 0),
        "memory_exact_skipped": diagnostics.get("memory_exact_skipped", 0),
        "source_failures": diagnostics.get("source_failures", {}),
        # Exact payload shape select_news_updates() would send to the model
        # (selection.py:535 compact_model_candidate) - this is the literal
        # "candidates entering the model" list, not just a count.
        "candidates": [compact_model_candidate(item) for item in shortlist],
    }


def fetch_supporting_stage(content_type: str) -> dict:
    started = time.time()
    if content_type == "course":
        target_limit = max(DISPLAY_COUNTS["courses"] + 8, SUPPORTING_COURSE_FETCH_POOL, 10)
        t0 = time.time()
        raw = fetch_course_candidates(max_results=max(SUPPORTING_COURSE_FETCH_POOL, target_limit + 3))
        fetch_seconds = time.time() - t0
    else:
        target_limit = max(DISPLAY_COUNTS["movies"], 1) + 3
        t0 = time.time()
        raw = fetch_movie_candidates(target_count=max(SUPPORTING_MOVIE_FETCH_POOL, target_limit + 8))
        fetch_seconds = time.time() - t0

    t0 = time.time()
    filtered = filter_supporting_candidates(raw or [], content_type, target_limit)
    filter_seconds = time.time() - t0

    return {
        "type": "courses" if content_type == "course" else "movies",
        "fetch_seconds": round(fetch_seconds, 2),
        "filter_seconds": round(filter_seconds, 2),
        "total_seconds": round(time.time() - started, 2),
        "raw_candidates": len(raw or []),
        "candidates_entering_model": len(filtered),
        # Exact payload shape select_supporting_content_cards() would send to
        # the model (modeling/supporting.py:34 compact_supporting_candidate).
        "candidates": [compact_supporting_candidate(item, content_type, index) for index, item in enumerate(filtered)],
    }


def print_news_report(report: dict) -> None:
    safe_print("-" * 78)
    safe_print(
        f"NEWS  fetch={report['fetch_seconds']}s  filter={report['filter_seconds']}s  "
        f"total={report['total_seconds']}s  cycles={report['cycles_run']}"
    )
    safe_print(
        f"  raw={report['raw_candidates']}  unique_after_fetch={report['unique_after_fetch']}  "
        f"filtered={report['filtered_candidates']}  scan_pool={report['scan_pool_count']}  "
        f"-> candidates_entering_model={report['candidates_entering_model']}"
    )
    for source, diag in report["source_breakdown"].items():
        status = f"error={diag['error']}" if diag.get("error") else "ok"
        safe_print(
            f"    [{source:24}] queries={diag['queries']:<4} raw={diag['raw_results']:<5} "
            f"unique={diag['unique_results']:<5} seconds={diag['seconds']:<6} {status}"
        )
    if report["source_lane_counts_in_shortlist"]:
        safe_print(f"  shortlist lanes: {report['source_lane_counts_in_shortlist']}")
    if report["editorial_rule_rejected"]:
        safe_print(f"  editorial rejects: {report['editorial_rule_rejected']}")
    safe_print(
        f"  old_news_skipped={report['old_news_skipped']}  memory_exact_skipped={report['memory_exact_skipped']}"
    )
    if report["source_failures"]:
        safe_print(f"  SOURCE FAILURES: {report['source_failures']}")
    safe_print(f"  candidates entering model (first 10 of {len(report['candidates'])}):")
    for item in report["candidates"][:10]:
        safe_print(f"    - [{item.get('source_lane') or '?':16}] {item.get('title')[:90]}  ({item.get('source_domain')})")


def print_supporting_report(report: dict) -> None:
    safe_print("-" * 78)
    safe_print(
        f"{report['type'].upper():6} fetch={report['fetch_seconds']}s  filter={report['filter_seconds']}s  "
        f"total={report['total_seconds']}s  raw={report['raw_candidates']}  "
        f"-> candidates_entering_model={report['candidates_entering_model']}"
    )
    for item in report["candidates"][:10]:
        safe_print(f"    - {item.get('title')[:90]}  ({item.get('source')})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch-only performance test (no model calls).")
    parser.add_argument("--types", default="news,courses,movies", help="Comma list of: news,courses,movies")
    parser.add_argument("--cycles", type=int, default=1, help="News fetch cycles to run (1-2, mirrors production).")
    parser.add_argument("--save", action="store_true", help="Write the JSON report to data/news/diagnostics/fetch_performance_test_report.json")
    parser.add_argument("--output", default="", help="Override the output path used with --save.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    types = {item.strip().lower() for item in args.types.split(",") if item.strip()}
    cycles = max(1, min(2, args.cycles))

    install_model_guards()
    set_run_context(new_run_id("fetch-perf-test"), "fetch_perf_test")

    safe_print("Fetch performance test - real Exa/SearXNG/TMDb calls, zero model calls")
    safe_print(f"  EXA_API_KEY={'set' if EXA_API_KEY else 'MISSING'}  SEARXNG_URL={SEARXNG_URL}  TMDB_API_KEY={'set' if TMDB_API_KEY else 'missing (movies will return empty)'}")
    safe_print(f"  types={sorted(types)}  news_cycles={cycles}")

    results: list[dict] = []
    run_started = time.time()

    if "news" in types:
        safe_print("\n[1/3] Fetching news candidates...")
        news_report = fetch_news_stage(cycles)
        print_news_report(news_report)
        results.append(news_report)

    if "courses" in types:
        safe_print("\n[2/3] Fetching course candidates...")
        courses_report = fetch_supporting_stage("course")
        print_supporting_report(courses_report)
        results.append(courses_report)

    if "movies" in types:
        safe_print("\n[3/3] Fetching movie candidates...")
        movies_report = fetch_supporting_stage("movie")
        print_supporting_report(movies_report)
        results.append(movies_report)

    total_seconds = round(time.time() - run_started, 2)
    safe_print("-" * 78)
    safe_print(f"TOTAL wall-clock: {total_seconds}s")
    if BLOCKED_MODEL_CALLS:
        safe_print(f"!! MODEL GUARD TRIGGERED {len(BLOCKED_MODEL_CALLS)}x: {BLOCKED_MODEL_CALLS}")
        safe_print("!! A code path reached the model and was blocked before any real API call was made.")
    else:
        safe_print("Model calls made: 0 (confirmed by guard)")

    if args.save:
        output_path = Path(args.output) if args.output else PROJECT_DIR / "data" / "news" / "diagnostics" / "fetch_performance_test_report.json"
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_seconds": total_seconds,
            "types": sorted(types),
            "news_cycles": cycles,
            "model_calls_blocked": BLOCKED_MODEL_CALLS,
            "results": results,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        safe_print(f"Saved report to {output_path}")


if __name__ == "__main__":
    main()
