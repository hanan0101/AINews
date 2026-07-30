"""Health check for the self-hosted SearXNG instance used by discovery.

Runs a representative battery of tool-update queries against the real
SEARXNG_URL endpoint and reports, per query: result count, latency, and
which upstream engines were unresponsive (CAPTCHA/rate-limited/timeout).
Prints an overall pass rate so a config change (timeout, engine list) in
searxng/settings.yml can be verified with real numbers instead of guessing.

Usage:
    python scripts/test_searxng_health.py
    python scripts/test_searxng_health.py --queries 20
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import requests  # noqa: E402

from backend.pipeline.fetching.fetch_utils import SEARXNG_RELIABLE_ENGINES, safe_print  # noqa: E402
from backend.pipeline.tool_discovery.queries import search_url  # noqa: E402

DEFAULT_TEST_QUERIES = [
    '"ChatGPT" update',
    '"Claude" update',
    '"Gemini" update',
    '"Midjourney" update',
    '"Canva" update',
    '"Runway" update',
    '"Perplexity" update',
    '"Cursor" update',
    '"Grammarly" update',
    '"ElevenLabs" update',
    '"SDAIA" OR "سدايا" ذكاء اصطناعي',
    '"AI tool" "new feature" OR "product update"',
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check SearXNG query health with real requests.")
    parser.add_argument("--queries", type=int, default=len(DEFAULT_TEST_QUERIES), help="How many test queries to run (default: all).")
    parser.add_argument("--engines", default=SEARXNG_RELIABLE_ENGINES, help=f"Engines param to send (default: {SEARXNG_RELIABLE_ENGINES}).")
    parser.add_argument("--timeout", type=float, default=10.0, help="Client request timeout in seconds.")
    return parser.parse_args()


def run_query(endpoint: str, query: str, engines: str, timeout: float) -> dict:
    params = {
        "q": query,
        "format": "json",
        "language": "en",
        "engines": engines,
        "categories": "general",
        "pageno": 1,
    }
    started = time.time()
    try:
        response = requests.get(endpoint, params=params, timeout=timeout)
        elapsed = round(time.time() - started, 2)
        response.raise_for_status()
        data = response.json()
        results = data.get("results") or []
        return {
            "query": query,
            "ok": True,
            "result_count": len(results),
            "seconds": elapsed,
            "unresponsive_engines": data.get("unresponsive_engines") or [],
        }
    except Exception as exc:
        elapsed = round(time.time() - started, 2)
        return {
            "query": query,
            "ok": False,
            "result_count": 0,
            "seconds": elapsed,
            "error": f"{type(exc).__name__}: {exc}",
            "unresponsive_engines": [],
        }


def main() -> None:
    args = parse_args()
    endpoint = search_url()
    queries = DEFAULT_TEST_QUERIES[: max(1, args.queries)]
    safe_print(f"SearXNG health check -> endpoint={endpoint} engines={args.engines!r} queries={len(queries)}")
    safe_print("-" * 78)

    outcomes = [run_query(endpoint, query, args.engines, args.timeout) for query in queries]

    passed = 0
    total_seconds = 0.0
    engine_failures: dict[str, int] = {}
    for outcome in outcomes:
        total_seconds += outcome["seconds"]
        status = "OK" if outcome["ok"] and outcome["result_count"] > 0 else "EMPTY" if outcome["ok"] else "FAIL"
        if status == "OK":
            passed += 1
        for engine, reason in outcome.get("unresponsive_engines") or []:
            engine_failures[engine] = engine_failures.get(engine, 0) + 1
        detail = outcome.get("error") or f"results={outcome['result_count']}"
        safe_print(f"[{status:5}] {outcome['seconds']:5.2f}s  {outcome['query'][:50]:50}  {detail}")

    safe_print("-" * 78)
    safe_print(f"Pass rate: {passed}/{len(queries)} ({round(100 * passed / len(queries))}%)")
    safe_print(f"Average latency: {round(total_seconds / len(queries), 2)}s")
    if engine_failures:
        safe_print("Engine failures seen:")
        for engine, count in sorted(engine_failures.items(), key=lambda item: -item[1]):
            safe_print(f"  - {engine}: {count}/{len(queries)} queries")
    else:
        safe_print("No unresponsive-engine reports.")


if __name__ == "__main__":
    main()
