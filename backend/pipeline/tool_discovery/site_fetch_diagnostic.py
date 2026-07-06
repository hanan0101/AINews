# This file is part of the AI newsletter system.
"""Raw official-site fetch diagnostics for active AI tools.

Run manually only. This script does not call GPT, does not write news.json,
and does not apply newsletter filtering. It only checks whether each saved
official site can return raw search results.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import requests

from backend.config.settings import (
    AI_UPDATES_EXA_TIMEOUT,
    AI_UPDATES_LOOKBACK_DAYS,
    AI_UPDATES_SEARXNG_TIME_RANGE,
    AI_UPDATES_SEARXNG_TIMEOUT,
    BACKEND_DIR,
    EXA_API_KEY,
    MONTHLY_TOOLS_FILE,
    clean_text,
    env_int,
    load_json,
    parse_result_datetime,
    safe_write_json,
    source_domain,
    utc_now,
)
from backend.pipeline.tool_discovery.official_sites import canonical_official_site
from backend.pipeline.tool_discovery.queries import search_url


DEFAULT_OUTPUT_FILE = BACKEND_DIR.parent / "data" / "news" / "official_site_raw_fetch_results.json"
DEFAULT_RESULTS_PER_SOURCE = env_int("OFFICIAL_SITE_DIAGNOSTIC_RESULTS_PER_SOURCE", "5")
DEFAULT_LIMIT = env_int("OFFICIAL_SITE_DIAGNOSTIC_LIMIT", "0")
DEFAULT_SEARXNG_ENGINES = os.getenv("OFFICIAL_SITE_DIAGNOSTIC_SEARXNG_ENGINES", "google,bing,brave").strip()
DEFAULT_SEARXNG_CATEGORIES = os.getenv("OFFICIAL_SITE_DIAGNOSTIC_SEARXNG_CATEGORIES", "general").strip()
DEFAULT_SEARXNG_TIME_RANGE = os.getenv(
    "OFFICIAL_SITE_DIAGNOSTIC_SEARXNG_TIME_RANGE",
    AI_UPDATES_SEARXNG_TIME_RANGE,
).strip() or "week"


# Performs the official site domain helper step.
def official_site_domain(site: str = "") -> str:
    clean = canonical_official_site(site)
    if not clean:
        return ""
    return clean.split("/", 1)[0].lower()


# Performs the official site matches result helper step.
def official_site_matches_result(site: str = "", result_url: str = "") -> bool:
    expected = official_site_domain(site)
    actual = source_domain(result_url)
    if not expected or not actual:
        return False
    return actual == expected or actual.endswith(f".{expected}")


# Performs the official site path matches result helper step.
def official_site_path_matches_result(site: str = "", result_url: str = "") -> bool:
    clean_site = canonical_official_site(site)
    if not clean_site or not result_url:
        return False
    expected_domain = official_site_domain(clean_site)
    expected_path = ""
    if "/" in clean_site:
        expected_path = "/" + clean_site.split("/", 1)[1].strip("/")
    try:
        parsed = urlparse_with_scheme(result_url)
    except Exception:
        return False
    actual_domain = parsed.netloc.lower().removeprefix("www.")
    actual_path = parsed.path.rstrip("/")
    if actual_domain != expected_domain:
        return False
    if not expected_path:
        return True
    return actual_path == expected_path or actual_path.startswith(f"{expected_path}/")


# Performs the urlparse with scheme helper step.
def urlparse_with_scheme(url: str):
    raw = str(url or "").strip()
    if raw and not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    from urllib.parse import urlparse

    return urlparse(raw)


# Performs the result date helper step.
def result_date(result: dict):
    raw_date = result.get("publishedDate") or result.get("published_date") or result.get("pubdate") or ""
    parsed = parse_result_datetime(raw_date)
    if parsed:
        return parsed
    text = clean_text(f"{result.get('title') or ''} {result.get('content') or ''}")
    import re

    match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
        text,
        flags=re.IGNORECASE,
    )
    return parse_result_datetime(match.group(0)) if match else None


# Performs the classify raw result helper step.
def classify_raw_result(result: dict, *, tool: str, official_site: str) -> tuple[str, list[str]]:
    title = clean_text(result.get("title") or result.get("name") or "")
    url = str(result.get("url") or result.get("id") or "").strip()
    content = clean_text(result.get("content") or result.get("summary") or result.get("text") or "")
    text = f"{title} {content}".lower()
    parsed = urlparse_with_scheme(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower().rstrip("/")
    reasons = []

    if not official_site_matches_result(official_site, url):
        reasons.append("wrong_domain")
    if not official_site_path_matches_result(official_site, url):
        reasons.append("outside_official_site_path")
    if host.startswith("developers.") or "/developers" in path or "/docs" in path or "/api" in path:
        reasons.append("developer_or_docs_page")
    if path.endswith("/blog") or "/topic/" in path or path.endswith("/news") or path.endswith("/changelog"):
        reasons.append("listing_or_index_page")
    if any(term in text for term in ("developer", "developers", "api", "sdk", "docs", "documentation", "quickstart")):
        reasons.append("developer_content")

    published = result_date(result)
    if published:
        age_days = max(0, (utc_now() - published).days)
        if age_days > max(1, AI_UPDATES_LOOKBACK_DAYS):
            reasons.append("outside_lookback_window")
    else:
        reasons.append("missing_date")

    news_terms = (
        "announce",
        "announces",
        "announced",
        "introducing",
        "introduces",
        "launch",
        "launched",
        "rolls out",
        "now available",
        "new feature",
        "update",
        "upgrade",
        "release",
        "latest",
    )
    if not any(term in text for term in news_terms):
        reasons.append("no_product_news_signal")
    if tool and tool.lower() not in text:
        reasons.append("tool_name_not_in_text")

    hard_reasons = {
        "wrong_domain",
        "outside_official_site_path",
        "developer_or_docs_page",
        "developer_content",
        "listing_or_index_page",
        "outside_lookback_window",
        "no_product_news_signal",
        "tool_name_not_in_text",
    }
    if any(reason in hard_reasons for reason in reasons):
        return "not_usable_news", reasons
    return "usable_news", reasons


# Reads load active tools with official sites from the current store or request context.
def load_active_tools_with_official_sites() -> list[dict]:
    registry = load_json(MONTHLY_TOOLS_FILE, {})
    records = list(registry.get("tool_records") or [])
    output = []
    seen = set()

    for record in records:
        if not isinstance(record, dict):
            continue
        tool = str(record.get("tool") or record.get("name") or "").strip()
        official_site = canonical_official_site(record.get("official_site") or "")
        status = str(record.get("status") or record.get("official_site_status") or "").strip().lower()
        key = (tool.lower(), official_site)
        if not tool or not official_site or key in seen:
            continue
        if status and status not in {"active", "ok", "verified"} and not status.startswith("ok:"):
            continue
        seen.add(key)
        output.append(
            {
                "tool": tool,
                "company": str(record.get("company") or tool).strip(),
                "official_site": official_site,
                "status": status or "active",
            }
        )

    return output


# Builds build official site queries for the next pipeline or API step.
def build_official_site_queries(tool: str, company: str, official_site: str) -> list[str]:
    clean_site = canonical_official_site(official_site)
    domain = official_site_domain(official_site) or official_site
    names = [tool]
    if company and company.lower() != tool.lower():
        names.append(company)

    queries = []
    for name in names:
        queries.extend(
            [
                f'"{name}"',
                f'"{name}" update',
                f'"{name}" release notes',
                f'"{name}" changelog',
                f'"{name}" new feature',
                f'"{name}" now available',
                f'"{name}" launch',
                f'"{name}" rollout',
                f'"{name}" product update',
                f'"{name}" announcement',
            ]
        )
        if clean_site:
            queries.append(f'"{name}" site:{clean_site}')
        if domain:
            queries.append(f'"{name}" site:{domain}')

    seen = set()
    output = []
    for query in queries:
        clean = " ".join(str(query or "").split())
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            output.append(clean)
    return output


# Performs the compact result helper step.
def compact_result(source: str, result: dict, official_site: str, query: str, tool: str) -> dict:
    url = str(result.get("url") or result.get("id") or "").strip()
    news_classification, rejection_reasons = classify_raw_result(result, tool=tool, official_site=official_site)
    return {
        "source": source,
        "query": query,
        "title": str(result.get("title") or result.get("name") or "").strip(),
        "url": url,
        "domain": source_domain(url),
        "published_date": str(result.get("publishedDate") or result.get("published_date") or "").strip(),
        "official_domain_match": official_site_matches_result(official_site, url),
        "official_site_path_match": official_site_path_matches_result(official_site, url),
        "news_classification": news_classification,
        "rejection_reasons": rejection_reasons,
        "raw": result,
    }


# Fetches fetch exa raw results from the configured external source.
def fetch_exa_raw_results(query: str, official_site: str, results_per_source: int, tool: str) -> tuple[list[dict], str]:
    if not EXA_API_KEY:
        return [], "missing_exa_api_key"

    domain = official_site_domain(official_site)
    payload = {
        "query": query,
        "type": "neural",
        "numResults": max(1, results_per_source),
        "contents": {"text": True, "highlights": True},
    }
    if domain:
        payload["includeDomains"] = [domain]

    headers = {"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY}
    try:
        response = requests.post(
            "https://api.exa.ai/search",
            headers=headers,
            json=payload,
            timeout=AI_UPDATES_EXA_TIMEOUT,
        )
        response.raise_for_status()
        results = list((response.json() or {}).get("results") or [])
        return [compact_result("exa", result, official_site, query, tool) for result in results], ""
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


# Fetches fetch searxng raw results from the configured external source.
def fetch_searxng_raw_results(
    query: str,
    official_site: str,
    results_per_source: int,
    tool: str,
    *,
    engines: str,
    categories: str,
    time_range: str,
) -> tuple[list[dict], str]:
    params = {
        "q": query,
        "format": "json",
        "language": "en",
        "engines": engines,
        "categories": categories,
        "time_range": time_range,
        "pageno": 1,
    }
    try:
        response = requests.get(search_url(), params=params, timeout=AI_UPDATES_SEARXNG_TIMEOUT)
        response.raise_for_status()
        results = list((response.json() or {}).get("results") or [])[: max(1, results_per_source)]
        return [compact_result("searxng", result, official_site, query, tool) for result in results], ""
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


# Performs the diagnose tool helper step.
def diagnose_tool(
    record: dict,
    *,
    sources: set[str],
    results_per_source: int,
    searxng_engines: str,
    searxng_categories: str,
    searxng_time_range: str,
) -> dict:
    tool = record["tool"]
    company = record.get("company") or tool
    official_site = record["official_site"]
    queries = build_official_site_queries(tool, company, official_site)
    source_results = {}
    errors = {}
    queries_tried = []

    for query in queries:
        query_log = {"query": query, "exa": 0, "searxng": 0}
        queries_tried.append(query_log)

        if "exa" in sources and not source_results.get("exa"):
            results, error = fetch_exa_raw_results(query, official_site, results_per_source, tool)
            query_log["exa"] = len(results)
            if results:
                source_results["exa"] = results
            if error:
                errors["exa"] = error

        if "searxng" in sources and not source_results.get("searxng"):
            results, error = fetch_searxng_raw_results(
                query,
                official_site,
                results_per_source,
                tool,
                engines=searxng_engines,
                categories=searxng_categories,
                time_range=searxng_time_range,
            )
            query_log["searxng"] = len(results)
            if results:
                source_results["searxng"] = results
            if error:
                errors["searxng"] = error

        if all(source_results.get(source) for source in sources):
            break

    for source in sources:
        source_results.setdefault(source, [])

    raw_results = [result for results in source_results.values() for result in results]
    official_matches = [result for result in raw_results if result.get("official_domain_match")]
    official_path_matches = [result for result in raw_results if result.get("official_site_path_match")]
    usable_news = [result for result in raw_results if result.get("news_classification") == "usable_news"]
    if raw_results and official_matches:
        fetch_status = "raw_results_with_official_domain"
    elif raw_results:
        fetch_status = "raw_results_wrong_or_mixed_domain"
    elif errors:
        fetch_status = "request_error"
    else:
        fetch_status = "no_raw_results"

    return {
        "tool": tool,
        "company": record.get("company") or tool,
        "status": record.get("status") or "",
        "official_site": official_site,
        "official_domain": official_site_domain(official_site),
        "queries_tried": queries_tried,
        "first_query": queries[0] if queries else "",
        "fetch_status": fetch_status,
        "raw_results_count": len(raw_results),
        "official_domain_matches": len(official_matches),
        "official_site_path_matches": len(official_path_matches),
        "usable_news_count": len(usable_news),
        "raw_rejection_reason_counts": count_rejection_reasons(raw_results),
        "errors": errors,
        "sample_titles": [result.get("title") for result in raw_results[:3] if result.get("title")],
        "results_by_source": source_results,
    }


# Performs the summarize helper step.
def summarize(rows: list[dict]) -> dict:
    return {
        "tools_checked": len(rows),
        "sites_returning_raw_results": sum(1 for row in rows if row["raw_results_count"] > 0),
        "sites_returning_official_domain_results": sum(1 for row in rows if row["official_domain_matches"] > 0),
        "sites_returning_official_path_results": sum(1 for row in rows if row["official_site_path_matches"] > 0),
        "sites_returning_usable_news": sum(1 for row in rows if row["usable_news_count"] > 0),
        "sites_returning_zero_results": sum(1 for row in rows if row["fetch_status"] == "no_raw_results"),
        "sites_with_request_errors": sum(1 for row in rows if row["fetch_status"] == "request_error"),
        "sites_with_mixed_or_wrong_domain_results": sum(
            1 for row in rows if row["fetch_status"] == "raw_results_wrong_or_mixed_domain"
        ),
        "zero_result_tools": [
            {"tool": row["tool"], "official_site": row["official_site"]}
            for row in rows
            if row["fetch_status"] == "no_raw_results"
        ],
        "error_tools": [
            {"tool": row["tool"], "official_site": row["official_site"], "errors": row["errors"]}
            for row in rows
            if row["errors"]
        ],
    }


# Performs the count rejection reasons helper step.
def count_rejection_reasons(results: list[dict]) -> dict:
    counts = {}
    for result in results:
        for reason in result.get("rejection_reasons") or []:
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


# Performs the parse sources helper step.
def parse_sources(value: str) -> set[str]:
    sources = {part.strip().lower() for part in str(value or "").split(",") if part.strip()}
    allowed = {"exa", "searxng"}
    selected = sources & allowed
    return selected or allowed


# Runs main as an executable pipeline or service step.
def main() -> int:
    parser = argparse.ArgumentParser(description="Check raw search results from saved official tool sites.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_FILE), help="JSON report path.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum tools to check. 0 means all.")
    parser.add_argument("--sources", default="exa,searxng", help="Comma-separated: exa,searxng")
    parser.add_argument("--results", type=int, default=DEFAULT_RESULTS_PER_SOURCE, help="Results per source per tool.")
    parser.add_argument("--searxng-engines", default=DEFAULT_SEARXNG_ENGINES, help="SearXNG engines to use.")
    parser.add_argument("--searxng-categories", default=DEFAULT_SEARXNG_CATEGORIES, help="SearXNG categories to use.")
    parser.add_argument("--searxng-time-range", default=DEFAULT_SEARXNG_TIME_RANGE, help="SearXNG time_range value.")
    args = parser.parse_args()

    records = load_active_tools_with_official_sites()
    if args.limit and args.limit > 0:
        records = records[: args.limit]

    sources = parse_sources(args.sources)
    checked = []
    for index, record in enumerate(records, start=1):
        print(f"[{index}/{len(records)}] Checking {record['tool']} on {record['official_site']}...", flush=True)
        checked.append(
            diagnose_tool(
                record,
                sources=sources,
                results_per_source=max(1, args.results),
                searxng_engines=args.searxng_engines,
                searxng_categories=args.searxng_categories,
                searxng_time_range=args.searxng_time_range,
            )
        )
    payload = {
        "generated_at": utc_now().isoformat(),
        "registry": str(MONTHLY_TOOLS_FILE),
        "sources": sorted(sources),
        "results_per_source": max(1, args.results),
        "searxng_engines": args.searxng_engines,
        "searxng_categories": args.searxng_categories,
        "searxng_time_range": args.searxng_time_range,
        "summary": summarize(checked),
        "tools": checked,
    }
    output_path = Path(args.output)
    safe_write_json(output_path, payload)

    summary = payload["summary"]
    print("Official-site raw fetch diagnostic complete")
    print(f"Tools checked: {summary['tools_checked']}")
    print(f"Sites returning raw results: {summary['sites_returning_raw_results']}")
    print(f"Sites returning official-domain results: {summary['sites_returning_official_domain_results']}")
    print(f"Sites returning official-path results: {summary['sites_returning_official_path_results']}")
    print(f"Sites returning usable news: {summary['sites_returning_usable_news']}")
    print(f"Sites returning zero results: {summary['sites_returning_zero_results']}")
    print(f"Sites with request errors: {summary['sites_with_request_errors']}")
    print(f"Report saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


