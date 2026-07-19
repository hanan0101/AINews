"""Fetch + real OpenAI selection test for news/courses/movies.

Builds on scripts/test_fetch_performance.py: runs the same real fetch+filter
stages, then goes one step further and actually calls the selection model -
forced to OpenAI for this run regardless of the project's configured default
provider (AI_UPDATES_MODEL_PROVIDER=gemini) - so you can see what OpenAI
picks from the exact candidate pool that would normally go to the model.

This DOES spend real OpenAI quota (news selection + rewrite = 2 calls,
course selection = 1 call, movie selection = 1 call). It does NOT publish
anything: the runtime newsletter JSON is never written, and
semantic memory is left disabled (AI_UPDATES_SEMANTIC_MEMORY_ENABLED=0) so no
embedding calls happen either. Token usage is recorded by the pipeline's own
cost tracker at data/news/runtime/model_usage_summary.json under this run's run_id,
same as it would be during a real run - that file is inspected at the end so
you get real input/output token counts, not an estimate.

The one guard kept from the fetch-only script: the monthly AI-tool registry
refresh (tools_aware.maintain_monthly_tool_files) is still stubbed to a
no-op, purely to avoid an unrelated Gemini call + wasted Exa credits as a
side effect of building this run's tool-driven queries - it has nothing to
do with selection and would run regardless of AI_UPDATES_MODEL_PROVIDER.

Usage:
    python scripts/test_openai_selection.py
    python scripts/test_openai_selection.py --types news
    python scripts/test_openai_selection.py --save
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ["AI_UPDATES_SEMANTIC_MEMORY_ENABLED"] = "0"
os.environ["AI_UPDATES_MODEL_PROVIDER"] = "openai"


def safe_print(message: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(str(message).encode(encoding, errors="backslashreplace").decode(encoding, errors="replace"), flush=True)


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config.settings import (  # noqa: E402
    DISPLAY_COUNTS,
    EXA_API_KEY,
    OPENAI_API_KEY,
    SEARXNG_URL,
    SUPPORTING_COURSE_FETCH_POOL,
    SUPPORTING_MOVIE_FETCH_POOL,
    TMDB_API_KEY,
)
from backend.logging.pipeline_logging import get_run_id, new_run_id, set_run_context  # noqa: E402
from backend.pipeline.fetching.news import fetch_news_candidates  # noqa: E402
from backend.pipeline.filtering.news import filter_news_candidates  # noqa: E402
from backend.pipeline.orchestrator import (  # noqa: E402
    build_large_scan_pool,
    shortlist_scan_pool_for_gpt,
)
from backend.pipeline.fetching.courses import fetch_course_candidates  # noqa: E402
from backend.pipeline.fetching.films import fetch_movie_candidates  # noqa: E402
from backend.pipeline.filtering.supporting import filter_supporting_candidates  # noqa: E402
from backend.pipeline.modeling.news import select_news_updates  # noqa: E402
from backend.pipeline.modeling.supporting import select_supporting_content_cards  # noqa: E402
from backend.pipeline.modeling.model_client import MODEL_PROVIDER, MODEL_FLASH_MODEL  # noqa: E402

import backend.pipeline.tool_discovery.tools_aware as tools_aware  # noqa: E402

MODEL_USAGE_FILE = PROJECT_DIR / "data" / "news" / "runtime" / "model_usage_summary.json"


def install_safety_guards() -> None:
    """Block the unrelated tool-registry-maintenance Gemini path; see module docstring."""
    tools_aware.maintain_monthly_tool_files = lambda **_kwargs: None


def fetch_news_shortlist() -> tuple[list[dict], dict]:
    t0 = time.time()
    candidates, diagnostics = fetch_news_candidates(cycle=1)
    fetch_seconds = time.time() - t0
    t0 = time.time()
    filtered = filter_news_candidates(candidates, diagnostics, single=False)
    scan_pool = build_large_scan_pool(filtered, diagnostics)
    shortlist = shortlist_scan_pool_for_gpt(scan_pool, diagnostics)
    filter_seconds = time.time() - t0
    safe_print(f"  news fetch={fetch_seconds:.1f}s filter={filter_seconds:.1f}s shortlist={len(shortlist)}")
    return shortlist, diagnostics


def run_news_selection() -> dict:
    shortlist, diagnostics = fetch_news_shortlist()
    t0 = time.time()
    report = select_news_updates(shortlist, diagnostics, single=False)
    gpt_seconds = time.time() - t0
    selected = report.get("latest_updates") or []
    return {
        "type": "news",
        "candidates_sent": len(shortlist),
        "selected_count": len(selected),
        "gpt_seconds": round(gpt_seconds, 2),
        "success": bool(report.get("success")),
        "error": report.get("error"),
        "selected": [
            {"title": item.get("title"), "url": item.get("official_url") or item.get("url"), "company": item.get("company") or item.get("owner_key")}
            for item in selected
        ],
    }


def run_supporting_selection(content_type: str) -> dict:
    started = time.time()
    if content_type == "course":
        display_count = DISPLAY_COUNTS["courses"]
        target_limit = max(display_count + 8, SUPPORTING_COURSE_FETCH_POOL, 10)
        raw = fetch_course_candidates(max_results=max(SUPPORTING_COURSE_FETCH_POOL, target_limit + 3))
    else:
        display_count = DISPLAY_COUNTS["movies"]
        target_limit = max(display_count, 1) + 3
        raw = fetch_movie_candidates(target_count=max(SUPPORTING_MOVIE_FETCH_POOL, target_limit + 8))
    fetch_seconds = time.time() - started

    t0 = time.time()
    filtered = filter_supporting_candidates(raw or [], content_type, target_limit)
    filter_seconds = time.time() - t0

    t0 = time.time()
    cards = select_supporting_content_cards(
        filtered,
        content_type,
        min(target_limit, len(filtered) or target_limit),
        visible_count=display_count,
    )
    gpt_seconds = time.time() - t0
    safe_print(f"  {content_type} fetch={fetch_seconds:.1f}s filter={filter_seconds:.1f}s candidates_sent={len(filtered)}")

    return {
        "type": "courses" if content_type == "course" else "movies",
        "candidates_sent": len(filtered),
        "selected_count": len(cards or []),
        "gpt_seconds": round(gpt_seconds, 2),
        "success": bool(cards),
        "selected": [{"title": item.get("title"), "url": item.get("url") or item.get("source_url")} for item in (cards or [])],
    }


def print_selection_report(report: dict) -> None:
    safe_print("-" * 78)
    status = "OK" if report["success"] else f"FAILED ({report.get('error')})"
    safe_print(
        f"{report['type'].upper():8} sent={report['candidates_sent']:<4} selected={report['selected_count']:<3} "
        f"gpt={report['gpt_seconds']}s  [{status}]"
    )
    for item in report["selected"]:
        safe_print(f"    - {item.get('title')}")


def read_this_run_usage() -> dict:
    run_id = get_run_id()
    try:
        summary = json.loads(MODEL_USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    run = (summary.get("runs") or {}).get(run_id) or {}
    return run.get("totals") or {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch + real OpenAI selection test.")
    parser.add_argument("--types", default="news,courses,movies", help="Comma list of: news,courses,movies")
    parser.add_argument("--save", action="store_true", help="Write the JSON report to data/news/diagnostics/openai_selection_test_report.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    types = {item.strip().lower() for item in args.types.split(",") if item.strip()}

    install_safety_guards()
    run_id = new_run_id("openai-selection-test")
    set_run_context(run_id, "openai_selection_test")

    safe_print(f"OpenAI selection test - provider forced to '{MODEL_PROVIDER}' model='{MODEL_FLASH_MODEL}'")
    safe_print(f"  EXA_API_KEY={'set' if EXA_API_KEY else 'MISSING'}  SEARXNG_URL={SEARXNG_URL}  TMDB_API_KEY={'set' if TMDB_API_KEY else 'missing'}  OPENAI_API_KEY={'set' if OPENAI_API_KEY else 'MISSING - will fail'}")
    safe_print(f"  types={sorted(types)}  run_id={run_id}")
    safe_print("  NOTE: does not publish - data/news/runtime/news.json is never written.\n")

    results = []
    started = time.time()

    if "news" in types:
        safe_print("[1/3] news: fetching + selecting...")
        r = run_news_selection()
        print_selection_report(r)
        results.append(r)

    if "courses" in types:
        safe_print("\n[2/3] courses: fetching + selecting...")
        r = run_supporting_selection("course")
        print_selection_report(r)
        results.append(r)

    if "movies" in types:
        safe_print("\n[3/3] movies: fetching + selecting...")
        r = run_supporting_selection("movie")
        print_selection_report(r)
        results.append(r)

    total_seconds = round(time.time() - started, 2)
    usage = read_this_run_usage()
    safe_print("-" * 78)
    safe_print(f"TOTAL wall-clock: {total_seconds}s")
    if usage:
        safe_print(
            f"OpenAI usage this run: calls={usage.get('calls', 0)} "
            f"input_tokens={usage.get('input_tokens', 0)} output_tokens={usage.get('output_tokens', 0)} "
            f"total_tokens={usage.get('total_tokens', 0)}"
        )
    else:
        safe_print("No usage recorded in model_usage_summary.json for this run_id (check for failures above).")

    if args.save:
        output_path = PROJECT_DIR / "data" / "news" / "diagnostics" / "openai_selection_test_report.json"
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "run_id": run_id,
            "provider": MODEL_PROVIDER,
            "model": MODEL_FLASH_MODEL,
            "total_seconds": total_seconds,
            "types": sorted(types),
            "usage": usage,
            "results": results,
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        safe_print(f"Saved report to {output_path}")


if __name__ == "__main__":
    main()
