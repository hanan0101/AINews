"""A/B test: does trusting TRUSTED_MEDIA_SOURCES (not just each tool's own
official domain) raise SearXNG's yield? Does NOT touch news_discovery.py -
every helper below is imported unmodified from production. Only the single
decision branch under test (what counts as "trusted enough to accept without
a confidently-extracted published date") is reimplemented twice, side by
side, using the exact same fetched page for both variants so this is a fair
same-request comparison, not two separate fetch passes.

Background: analyze_news_funnel.py showed SearXNG contributing 0 of 127
surviving unique news candidates in the latest real run. Root cause traced
into fetch_searxng_query_rows(): a raw SearXNG hit only survives without a
confidently-extracted published date (JSON-LD/meta/time-tag/regex) if its
domain matches that specific tool's own official site - most surviving hits
then get dropped again by combine_source_results() for duplicating an Exa
hit. This script tests loosening that single fallback to also accept
TRUSTED_MEDIA_SOURCES domains (the same list Exa's trusted-media lane
already uses), and reports how many additional real candidates would have
survived, so the change can be judged before touching production code.

Uses the SAME real query rows discovery_rows("searxng") would build this
run, hits the real SearXNG endpoint and fetches each result page for real
(read-only network calls, no model, no writes to any pipeline state file).

Usage:
    python scripts/test_searxng_trusted_media_fix.py
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

import requests  # noqa: E402
from datetime import timedelta  # noqa: E402

from backend.config.settings import (  # noqa: E402
    AI_UPDATES_LOOKBACK_DAYS,
    AI_UPDATES_SEARXNG_CATEGORIES,
    AI_UPDATES_SEARXNG_RESULTS_PER_QUERY,
    AI_UPDATES_SEARXNG_TIME_RANGE,
    AI_UPDATES_SEARXNG_TIMEOUT,
    clean_text,
    utc_now,
)
from backend.pipeline.fetching.news_discovery import (  # noqa: E402
    discovery_rows,
    domain_matches,
    official_site_domain,
    result_looks_like_update,
    search_url,
    searxng_discovery_canonical_url,
    searxng_discovery_extract_date_confident,
    searxng_discovery_fetch_html,
    searxng_discovery_is_hub_page,
    searxng_discovery_split_hub,
    source_domain,
    SEARXNG_DISCOVERY_FETCH_RESULTS,
    SEARXNG_RELIABLE_ENGINES,
    TRUSTED_MEDIA_SOURCES,
)
import backend.pipeline.tool_discovery.tools_aware as tools_aware  # noqa: E402

TRUSTED_MEDIA_DOMAINS = {source["domain"] for source in TRUSTED_MEDIA_SOURCES}


def install_guards() -> None:
    tools_aware.maintain_monthly_tool_files = lambda **_kwargs: None


def fetch_raw_searxng_results(base_query: str) -> list[dict]:
    # Mirrors fetch_searxng_query_rows.fetch_row() EXACTLY for
    # searxng_url_discovery_only=True rows: clean_text (not the heavily
    # AND/negative-term-rewritten searxng_fetch_query), categories="general",
    # and no time_range param at all - all three differ from the non-url-
    # discovery lane, and getting any of them wrong silently zeroes results.
    query = clean_text(base_query)
    params = {
        "q": query,
        "format": "json",
        "language": "en",
        "engines": SEARXNG_RELIABLE_ENGINES,
        "categories": "general",
        "pageno": 1,
    }
    try:
        response = requests.get(search_url(), params=params, timeout=AI_UPDATES_SEARXNG_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        safe_print(f"  query failed: {exc}")
        return []
    return list(data.get("results") or [])[:SEARXNG_DISCOVERY_FETCH_RESULTS]


def evaluate_result(raw: dict, row: dict, cutoff) -> dict:
    """Fetch the page once, then decide CURRENT vs IMPROVED acceptance from the same HTML."""
    url = str(raw.get("url") or "").strip()
    title = raw.get("title") or ""
    outcome = {"title": title, "url": url, "current": "reject", "improved": "reject", "reason": ""}
    key = searxng_discovery_canonical_url(url)
    if not key:
        outcome["reason"] = "missing_url"
        return outcome

    html, final_url, error = searxng_discovery_fetch_html(url)
    if error:
        outcome["reason"] = error
        return outcome

    if searxng_discovery_is_hub_page(html, final_url):
        # Hub pages are handled identically by both variants (date-only
        # split, no domain-trust branch involved) - not part of this A/B.
        outcome["reason"] = "hub_page_not_in_scope"
        return outcome

    verified = searxng_discovery_extract_date_confident(html, final_url)
    if verified and verified["date"] >= cutoff:
        outcome["current"] = "accept"
        outcome["improved"] = "accept"
        outcome["reason"] = f"confident_date:{verified['source']}"
        return outcome
    if verified:
        outcome["reason"] = "confident_date_but_outside_window"
        return outcome

    # No confidently-extracted date: this is the branch under test.
    official_domain = official_site_domain(row.get("official_site") or "")
    result_domain = source_domain(final_url or url)
    content = raw.get("content") or raw.get("snippet") or ""
    looks_like_update = result_looks_like_update(title, final_url or url, content)

    is_official = bool(official_domain) and domain_matches(result_domain, (official_domain,))
    is_trusted_media = result_domain in TRUSTED_MEDIA_DOMAINS

    if is_official and looks_like_update:
        outcome["current"] = "accept"
        outcome["improved"] = "accept"
        outcome["reason"] = "official_domain_update_like"
    elif is_trusted_media and looks_like_update:
        outcome["improved"] = "accept"
        outcome["reason"] = "NEW:trusted_media_update_like"
    elif is_trusted_media:
        outcome["reason"] = "trusted_media_but_not_update_like"
    else:
        outcome["reason"] = "no_confident_date_untrusted_domain"
    return outcome


def main() -> None:
    install_guards()
    rows = discovery_rows("searxng")
    url_rows = [row for row in rows if row.get("searxng_url_discovery_only")]
    safe_print(f"Testing {len(url_rows)} real SearXNG tool-driven queries (url_discovery_only lane)")
    safe_print(f"TRUSTED_MEDIA_DOMAINS available as fallback: {len(TRUSTED_MEDIA_DOMAINS)} domains\n")

    cutoff = utc_now() - timedelta(days=AI_UPDATES_LOOKBACK_DAYS)
    all_outcomes = []
    started = time.time()
    for index, row in enumerate(url_rows, 1):
        raw_results = fetch_raw_searxng_results(row["query"])
        safe_print(f"[{index}/{len(url_rows)}] {row.get('tool')}: {len(raw_results)} raw hits")
        for raw in raw_results:
            outcome = evaluate_result(raw, row, cutoff)
            outcome["tool"] = row.get("tool")
            outcome["query"] = row.get("query")
            all_outcomes.append(outcome)
    elapsed = time.time() - started

    current_accepts = [o for o in all_outcomes if o["current"] == "accept"]
    improved_accepts = [o for o in all_outcomes if o["improved"] == "accept"]
    new_only = [o for o in all_outcomes if o["improved"] == "accept" and o["current"] == "reject"]

    safe_print("\n" + "-" * 78)
    safe_print(f"Checked {len(all_outcomes)} raw results across {len(url_rows)} queries in {elapsed:.1f}s")
    safe_print(f"CURRENT logic (official-domain-only fallback): {len(current_accepts)} accepted")
    safe_print(f"IMPROVED logic (+ trusted-media fallback):     {len(improved_accepts)} accepted")
    safe_print(f"Net NEW candidates the improvement would add:  {len(new_only)}")
    if new_only:
        safe_print("\nNew candidates that would now survive:")
        for item in new_only:
            safe_print(f"  - [{item['tool']}] {item['title'][:80]}")
            safe_print(f"      {item['url']}")

    output_path = PROJECT_DIR / "data" / "news" / "searxng_trusted_media_ab_test.json"
    output_path.write_text(
        json.dumps(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "queries_tested": len(url_rows),
                "raw_results_checked": len(all_outcomes),
                "current_accepted": len(current_accepts),
                "improved_accepted": len(improved_accepts),
                "net_new": len(new_only),
                "outcomes": all_outcomes,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    safe_print(f"\nSaved full outcome log to {output_path}")


if __name__ == "__main__":
    main()
