# Tests SearXNG with tool update/release/launch queries and a last-week filter.
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from urllib.parse import urljoin, urlparse, urlunparse

import extruct
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config.settings import MONTHLY_TOOLS_FILE, SEARXNG_URL, clean_text, load_json, safe_write_json, utc_now  # noqa: E402

OUTPUT_DIR = PROJECT_DIR / "data" / "news"
JSON_REPORT = OUTPUT_DIR / "searxng_tool_name_week_test.json"
MD_REPORT = OUTPUT_DIR / "searxng_tool_name_week_test.md"
UPDATE_TERMS = (
    "latest update",
    "update",
    "updates",
    "updated",
    "release",
    "release notes",
    "new release",
    "launch",
    "launched",
    "new feature",
    "rollout",
    "what's new",
    "whats new",
    "changelog",
)
FRESH_UPDATE_TERMS = (
    "latest update",
    "new release",
    "new feature",
    "what's new",
    "whats new",
    "changelog",
    "release notes",
    "product update",
    "product updates",
    "major update",
    "adds",
    "now available",
)
BAD_PAGE_TERMS = (
    "/auth/",
    "/login",
    "/sign-in",
    "/signin",
    "/app",
    "/apps",
    "/download",
    "/pricing",
    "download ",
    "official site",
    "chatgpt.com/",
)
HUB_PATH_TERMS = ("changelog", "releases", "whats-new")
REQUEST_HEADERS = {
    "User-Agent": "AINewsletterBot/1.0 (+https://localhost)",
}


# Loads tool names from the current monthly registry.
def load_tool_names() -> list[str]:
    data = load_json(MONTHLY_TOOLS_FILE, {"tool_records": [], "tools": []})
    names = []
    for item in data.get("tool_records") or []:
        if isinstance(item, dict):
            name = clean_text(item.get("tool") or item.get("company") or "")
            if name:
                names.append(name)
    for item in data.get("tools") or []:
        if isinstance(item, str) and clean_text(item):
            names.append(clean_text(item))
    return list(dict.fromkeys(names))


# Extracts a readable source domain from a result URL.
def source_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


# Runs one SearXNG request and returns results with the response time.
def canonical_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.rstrip("/")
    return urlunparse((scheme, host, path, "", "", ""))


# Parses a date-like value into a timezone-aware UTC datetime.
def parse_result_date(value: str = "") -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = date_parser.parse(text, fuzzy=True)
    except Exception:
        return None
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# Fetches a URL so local code can inspect the page.
def fetch_html(url: str, timeout: int) -> tuple[str, str]:
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        return response.text, ""
    except Exception as exc:
        return "", f"fetch_failed:{type(exc).__name__}"


# Detects hub pages that contain several updates.
def is_hub_page(html: str, url: str) -> bool:
    soup = BeautifulSoup(html or "", "html.parser")
    time_count = len(soup.find_all("time"))
    container_count = len(soup.find_all("article"))
    container_count += len(soup.select('[class*="changelog-entry"], [class*="release-note"], [class*="update-item"], [class*="post-card"]'))
    url_has_hub_term = any(term in str(url or "").lower() for term in HUB_PATH_TERMS)
    return sum(1 for value in (time_count >= 3, container_count >= 3, url_has_hub_term) if value) >= 2


# Splits a hub page into individual dated update entries.
def split_hub(html: str, url: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    containers = []
    for selector in ("article", '[class*="changelog-entry"]', '[class*="release-note"]', "section:has(time)"):
        containers = soup.select(selector)
        if containers:
            break
    entries = []
    for container in containers:
        time_tag = container.find("time")
        date_value = parse_result_date(time_tag.get("datetime") if time_tag else "")
        if not date_value and time_tag:
            date_value = parse_result_date(time_tag.get_text(" ", strip=True))
        title_tag = container.find(["h2", "h3"])
        link_tag = container.find("a", href=True)
        title = clean_text(title_tag.get_text(" ", strip=True) if title_tag else "")
        entry_url = urljoin(url, link_tag["href"]) if link_tag else url
        if date_value and title:
            entries.append({"date": date_value, "title": title, "url": entry_url})
    return entries


# Rejects date nodes that appear to describe modification or update time.
def has_modified_context(tag) -> bool:
    if not tag:
        return False
    attrs = " ".join(str(value) for value in tag.attrs.values()).lower()
    nearby = tag.parent.get_text(" ", strip=True).lower()[:160] if tag.parent else ""
    evidence = f"{attrs} {nearby}"
    return "modified" in evidence or "updated" in evidence


# Extracts the highest-confidence published date without using modified dates.
def extract_date_confident(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html or "", "html.parser")
    candidates = []
    try:
        metadata = extruct.extract(html or "", base_url=url, syntaxes=["json-ld"], uniform=True)
    except Exception:
        metadata = {"json-ld": []}
    for item in metadata.get("json-ld") or []:
        if "datePublished" in item:
            parsed = parse_result_date(item.get("datePublished"))
            if parsed:
                candidates.append({"date": parsed, "confidence": 10, "source": "json_ld_datePublished"})
    for attrs in ({"property": "article:published_time"}, {"name": "article:published_time"}):
        tag = soup.find("meta", attrs=attrs)
        parsed = parse_result_date(tag.get("content") if tag else "")
        if parsed:
            candidates.append({"date": parsed, "confidence": 9, "source": "meta_article_published_time"})
    for tag in soup.find_all("time"):
        if has_modified_context(tag):
            continue
        parsed = parse_result_date(tag.get("datetime") or "")
        if parsed:
            candidates.append({"date": parsed, "confidence": 7, "source": "time_datetime"})
    head_text = soup.get_text(" ", strip=True)[:2000]
    for match in re.finditer(r"\d{4}-\d{2}-\d{2}", head_text):
        context = head_text[max(0, match.start() - 40) : match.end() + 40].lower()
        if "modified" in context or "updated" in context:
            continue
        parsed = parse_result_date(match.group(0))
        if parsed:
            candidates.append({"date": parsed, "confidence": 3, "source": "regex_first_2000"})
            break
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item["confidence"], reverse=True)[0]


# Checks whether a date is inside the last seven days.
def is_recent(date_value: datetime, now: datetime) -> bool:
    return date_value >= now - timedelta(days=7)


def request_searxng(query: str, *, engine: str, timeout: int, fetch_limit: int) -> tuple[list[dict], float, str, int]:
    started = time.perf_counter()
    try:
        response = requests.get(
            f"{SEARXNG_URL.rstrip('/')}/search",
            params={
                "q": query,
                "format": "json",
                "language": "en",
                "engines": engine,
                "categories": "general",
                "pageno": 1,
            },
            timeout=timeout,
        )
        elapsed = round(time.perf_counter() - started, 3)
        if response.status_code >= 400:
            return [], elapsed, f"http_{response.status_code}:{response.text[:180]}", 0
        payload = response.json() or {}
        raw_results = list(payload.get("results") or [])[:fetch_limit]
        hinted = sorted(
            raw_results,
            key=lambda item: parse_result_date(str(item.get("publishedDate") or item.get("date") or "")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return hinted, elapsed, "", len(raw_results)
    except Exception as exc:
        elapsed = round(time.perf_counter() - started, 3)
        return [], elapsed, f"{type(exc).__name__}:{exc}", 0


# Retries one query until it gets results or reaches the maximum wait time.
def search_until_result(query: str, *, engines: list[str], timeout: int, fetch_limit: int, retry_delay: float, max_wait: float) -> dict:
    started = time.perf_counter()
    attempts = []
    while True:
        results = []
        for engine in engines:
            results, response_seconds, error, raw_count = request_searxng(
                query,
                engine=engine,
                timeout=timeout,
                fetch_limit=fetch_limit,
            )
            attempts.append({"engine": engine, "response_seconds": response_seconds, "raw_count": raw_count, "result_count": len(results), "error": error})
            if results:
                break
        if results:
            break
        if time.perf_counter() - started >= max_wait:
            break
        time.sleep(retry_delay)
    total_wait = round(time.perf_counter() - started, 3)
    return {
        "query": query,
        "attempts": len(attempts),
        "attempts_detail": attempts,
        "total_wait_seconds": total_wait,
        "average_attempt_response_seconds": round(mean(item["response_seconds"] for item in attempts), 3),
        "last_error": attempts[-1]["error"],
        "results": normalize_results(results),
    }


# Keeps only the fields needed for the review table.
# Processes one tool by letting SearXNG find URLs and local code verify pages.
def process_tool(tool: str, *, engines: list[str], args: argparse.Namespace, now: datetime) -> dict:
    query = f'last "{tool}" update'
    search = search_until_result(
        query,
        engines=engines,
        timeout=args.timeout,
        fetch_limit=max(args.fetch_results, args.results),
        retry_delay=args.retry_delay,
        max_wait=args.max_wait,
    )
    accepted = []
    rejected = []
    seen = set()
    for item in search["results"]:
        url = item["url"]
        key = canonical_url(url)
        if not key or key in seen:
            continue
        seen.add(key)
        html, error = fetch_html(url, args.page_timeout)
        if error:
            rejected.append({**item, "reason": error})
            continue
        if is_hub_page(html, url):
            hub_entries = split_hub(html, url)
            if not hub_entries:
                rejected.append({**item, "reason": "hub_without_entries"})
                continue
            for entry in hub_entries:
                entry_key = canonical_url(entry["url"])
                if not entry_key or entry_key in seen:
                    continue
                seen.add(entry_key)
                entry_row = {
                    "title": entry["title"],
                    "url": entry["url"],
                    "domain": source_domain(entry["url"]),
                    "date": entry["date"].isoformat(),
                    "date_source": "hub_time",
                    "source_result": url,
                }
                if is_recent(entry["date"], now):
                    accepted.append(entry_row)
                else:
                    rejected.append({**entry_row, "reason": "outside_last_7_days"})
            continue
        verified = extract_date_confident(html, url)
        if not verified:
            rejected.append({**item, "reason": "no_confident_published_date"})
            continue
        verified_row = {
            **item,
            "date": verified["date"].isoformat(),
            "date_source": verified["source"],
            "date_confidence": verified["confidence"],
        }
        if not is_recent(verified["date"], now):
            rejected.append({**verified_row, "reason": "outside_last_7_days"})
            continue
        accepted.append(verified_row)
        if len(accepted) >= args.results:
            break
    return {
        "tool": tool,
        "query": query,
        "attempts": search["attempts"],
        "attempts_detail": search["attempts_detail"],
        "total_wait_seconds": search["total_wait_seconds"],
        "average_attempt_response_seconds": search["average_attempt_response_seconds"],
        "last_error": search["last_error"],
        "results": accepted[: args.results],
        "rejected": rejected,
        "candidate_urls": search["results"],
    }


def normalize_results(results: list[dict]) -> list[dict]:
    output = []
    for item in results:
        url = str(item.get("url") or "").strip()
        output.append(
            {
                "title": clean_text(item.get("title") or ""),
                "url": url,
                "domain": source_domain(url),
                "published": clean_text(item.get("publishedDate") or item.get("date") or ""),
                "engine": clean_text(item.get("engine") or ""),
            }
        )
    return output


# Writes JSON and Markdown reports for manual review.
def write_reports(report: dict) -> None:
    safe_write_json(JSON_REPORT, report)
    lines = [
        "# SearXNG Tool Name Week Test",
        "",
        f"- Generated: {report['generated_at']}",
        f"- SearXNG URL: {report['searxng_url']}",
        "- Query style: last quoted tool update",
        "- SearXNG role: URL discovery only",
        "- Date filter: local page verification only; SearXNG dates are ranking hints",
        "- Hub pages: split locally when multiple dated updates are detected",
        "- Category: general",
        "- Time filter: disabled",
        f"- Average response time: {report['summary']['average_response_seconds']}s",
        "",
        "## Results",
        "",
        "| Tool | Query | Attempts | Wait Seconds | # | Title | Link | Domain |",
        "|---|---|---:|---:|---:|---|---|---|",
    ]
    for row in report["queries"]:
        if not row["results"]:
            reason = row["last_error"] or "no_results"
            lines.append(f"| {row['tool']} | `{row['query']}` | {row['attempts']} | {row['total_wait_seconds']} | 0 | {reason} | - | - |")
            continue
        for index, item in enumerate(row["results"], 1):
            title = (item["title"] or "-").replace("|", "\\|")
            lines.append(
                f"| {row['tool']} | `{row['query']}` | {row['attempts']} | {row['total_wait_seconds']} | "
                f"{index} | {title} | {item['url'] or '-'} | {item['domain'] or '-'} |"
            )
    MD_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Parses command-line options for the SearXNG diagnostic run.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test SearXNG with weekly tool update/release/launch queries.")
    parser.add_argument("--results", type=int, default=4, help="Results to keep from every query.")
    parser.add_argument("--fetch-results", type=int, default=12, help="Results to fetch before newest-first sorting.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout per SearXNG request.")
    parser.add_argument("--page-timeout", type=int, default=20, help="HTTP timeout per candidate page fetch.")
    parser.add_argument("--retry-delay", type=float, default=15.0, help="Seconds to wait between retries.")
    parser.add_argument("--max-wait", type=float, default=90.0, help="Maximum seconds to wait for one query.")
    parser.add_argument("--engines", default="brave,startpage,google,bing", help="Comma-separated engine fallback order.")
    parser.add_argument("--limit", type=int, default=0, help="Optional number of tools to test; 0 means all tools.")
    return parser.parse_args()


# Runs the full SearXNG update-query test and saves reports.
def main() -> int:
    args = parse_args()
    tools = load_tool_names()
    engines = [item.strip() for item in args.engines.split(",") if item.strip()]
    if args.limit > 0:
        tools = tools[: args.limit]
    rows = []
    now = utc_now()
    for tool in tools:
        result = process_tool(tool, engines=engines, args=args, now=now)
        rows.append(result)
        print(f"{tool}: {len(result['results'])} results, attempts={result['attempts']}, wait={result['total_wait_seconds']}s", flush=True)
    attempt_times = [attempt["response_seconds"] for row in rows for attempt in row.get("attempts_detail", [])]
    row_times = [row["average_attempt_response_seconds"] for row in rows]
    report = {
        "generated_at": utc_now().isoformat(),
        "searxng_url": SEARXNG_URL,
        "settings": {
            "results_per_query": args.results,
            "fetched_before_sort": max(args.fetch_results, args.results),
            "timeout_seconds": args.timeout,
            "page_timeout_seconds": args.page_timeout,
            "retry_delay_seconds": args.retry_delay,
            "max_wait_seconds": args.max_wait,
            "time_range": "",
            "categories": "general",
            "engines": engines,
            "date_policy": "manual_page_verification_only",
            "dedupe": "canonical_url_without_query_or_fragment",
        },
        "summary": {
            "tools_tested": len(rows),
            "tools_with_results": sum(1 for row in rows if row["results"]),
            "accepted_results": sum(len(row["results"]) for row in rows),
            "rejected_results": sum(len(row.get("rejected", [])) for row in rows),
            "average_response_seconds": round(mean(row_times), 3) if row_times else 0,
            "average_attempt_response_seconds": round(mean(attempt_times), 3) if attempt_times else None,
        },
        "queries": rows,
    }
    write_reports(report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"JSON report: {JSON_REPORT}")
    print(f"Markdown report: {MD_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
