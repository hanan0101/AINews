"""Live measurement of the two SearXNG fixes applied 2026-07-18 to
news_discovery.py (expanded UPDATE_TERMS, SEARXNG_UNRELATED_TOPIC_DOMAINS
skip). Calls the real, now-patched fetch_searxng_query_rows() against live
SearXNG with the same real tool-driven query rows production uses.

SAFETY: install_guards() MUST run before any other backend import touches
discovery_rows/fetch_searxng_query_rows - a prior ad-hoc script skipped this
and triggered 13 real Gemini API calls from the monthly tool-registry
auto-expansion path as a side effect of building query rows. This script
installs the same guard used in test_fetch_performance.py /
analyze_news_funnel.py before calling anything.

Usage:
    python scripts/test_searxng_fix_live.py
"""

from __future__ import annotations

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

# Guards installed BEFORE importing anything that could call discovery_rows.
import backend.pipeline.tool_discovery.tools_aware as tools_aware  # noqa: E402
import backend.pipeline.modeling.model_client as model_client  # noqa: E402
import backend.pipeline.modeling.gemini_client as gemini_client  # noqa: E402
import backend.pipeline.modeling.openai_client as openai_client  # noqa: E402

BLOCKED_MODEL_CALLS: list[str] = []


def _block(label: str):
    def _blocked(*_args, **_kwargs):
        BLOCKED_MODEL_CALLS.append(label)
        raise RuntimeError(f"test_searxng_fix_live tried to call the model via {label}()")
    return _blocked


tools_aware.maintain_monthly_tool_files = lambda **_kwargs: None
tools_aware.generate_json = _block("tools_aware.generate_json")
model_client.generate_json = _block("model_client.generate_json")
model_client.embed_texts = _block("model_client.embed_texts")
gemini_client.generate_json = _block("gemini_client.generate_json")
gemini_client.embed_texts = _block("gemini_client.embed_texts")
openai_client.generate_json = _block("openai_client.generate_json")
openai_client.embed_texts = _block("openai_client.embed_texts")

safe_print("Guards installed (tool-registry maintenance stubbed, model calls blocked). Now importing discovery_rows...")

from backend.pipeline.fetching.news_discovery import (  # noqa: E402
    discovery_rows,
    fetch_searxng_query_rows,
)


def main() -> None:
    safe_print("Building real SearXNG tool-driven query rows (discovery_rows)...")
    rows = discovery_rows("searxng")
    url_rows = [row for row in rows if row.get("searxng_url_discovery_only")]
    safe_print(f"{len(url_rows)} queries to run\n")

    started = time.time()
    items, diagnostics = fetch_searxng_query_rows(url_rows)
    elapsed = time.time() - started

    safe_print("-" * 78)
    safe_print(f"SearXNG fetch (WITH fixes) finished in {elapsed:.1f}s")
    safe_print(f"queries={diagnostics.get('queries')} raw_results={diagnostics.get('raw_results')} unique_results={diagnostics.get('unique_results')}")
    if diagnostics.get("errors"):
        safe_print(f"errors: {diagnostics.get('errors')}")

    if items:
        safe_print(f"\nSurviving candidates ({len(items)}):")
        for item in items:
            safe_print(f"  - [{item.get('tool')}] {item.get('title')}")
            safe_print(f"      {item.get('url')}  (acceptance_reason={item.get('acceptance_reason')})")
    else:
        safe_print("\nNo candidates survived.")

    query_results = diagnostics.get("query_results") or []
    rejection_counts: dict[str, int] = {}
    for query_audit in query_results:
        for rejection in query_audit.get("rejections") or []:
            reason = rejection.get("reason") or "unknown"
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
    safe_print(f"\nRejection reasons across all {len(query_results)} queries:")
    for reason, count in sorted(rejection_counts.items(), key=lambda pair: -pair[1]):
        safe_print(f"  {reason}: {count}")

    output_path = PROJECT_DIR / "data" / "news" / "searxng_fix_live_result.json"
    output_path.write_text(
        json.dumps(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "elapsed_seconds": round(elapsed, 2),
                "queries": diagnostics.get("queries"),
                "raw_results": diagnostics.get("raw_results"),
                "unique_results": diagnostics.get("unique_results"),
                "errors": diagnostics.get("errors", []),
                "rejection_counts": rejection_counts,
                "query_results": query_results,
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    safe_print(f"\nSaved to {output_path}")
    if BLOCKED_MODEL_CALLS:
        safe_print(f"!! MODEL GUARD TRIGGERED: {BLOCKED_MODEL_CALLS}")
    else:
        safe_print("Model calls made: 0 (confirmed by guard)")


if __name__ == "__main__":
    main()
