# Searches Exa for recent AI tool updates and verifies dates from each page.
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import extruct
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config.settings import MONTHLY_TOOLS_FILE, clean_text, load_json, safe_write_json, utc_now  # noqa: E402

HEADERS = {
    "User-Agent": "AINewsletterBot/1.0 (+https://localhost)",
}

EXA_SEARCH_URL = "https://api.exa.ai/search"
OUTPUT_PATH = PROJECT_DIR / "data" / "news" / "exa_recent_tool_updates.json"
SAMPLE_URLS = [
    "https://support.claude.com/en/articles/12138966-release-notes",
    "https://cursor.com/changelog",
    "https://blog.google/innovation-and-ai/models-and-research/google-labs/flow-updates/",
]


# Parses a date-like value into a timezone-aware UTC datetime.
def parse_date(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = date_parser.parse(text, fuzzy=True)
    except (TypeError, ValueError, OverflowError):
        return None
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# Reads JSON-LD objects and returns the first datePublished value found.
def date_from_json_ld(html: str, url: str) -> datetime | None:
    try:
        metadata = extruct.extract(html, base_url=url, syntaxes=["json-ld"], uniform=True)
    except Exception:
        return None
    for item in metadata.get("json-ld") or []:
        parsed = parse_date(item.get("datePublished"))
        if parsed:
            return parsed
    return None


# Reads article:published_time meta tags and returns the first usable date.
def date_from_meta(soup: BeautifulSoup) -> datetime | None:
    selectors = [
        {"property": "article:published_time"},
        {"name": "article:published_time"},
    ]
    for attrs in selectors:
        tag = soup.find("meta", attrs=attrs)
        parsed = parse_date(tag.get("content") if tag else "")
        if parsed:
            return parsed
    return None


# Reads time tags and returns the first usable datetime value.
def date_from_time_tag(soup: BeautifulSoup) -> datetime | None:
    for tag in soup.find_all("time"):
        parsed = parse_date(tag.get("datetime") or tag.get_text(" ", strip=True))
        if parsed:
            return parsed
    return None


# Finds date-like text in the page body and returns the first usable date.
def date_from_text(soup: BeautifulSoup) -> datetime | None:
    text = soup.get_text(" ", strip=True)
    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            parsed = parse_date(match.group(0))
            if parsed:
                return parsed
    return None


# Fetches a page and returns parsed HTML details for date verification.
def fetch_page(url: str, timeout: int) -> tuple[str, str, str]:
    try:
        response = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        return response.text, str(response.url), ""
    except httpx.HTTPError as exc:
        return "", url, f"fetch_failed:{type(exc).__name__}"


# Returns a verified date, its source, and a rejection reason when unavailable.
def verify_date_details(url: str, timeout: int = 20) -> tuple[datetime | None, str, str]:
    html, final_url, error = fetch_page(url, timeout)
    if error:
        return None, "", error
    soup = BeautifulSoup(html, "html.parser")
    sources = [
        ("json_ld_datePublished", date_from_json_ld(html, final_url)),
        ("meta_article_published_time", date_from_meta(soup)),
        ("time_datetime", date_from_time_tag(soup)),
        ("text_date", date_from_text(soup)),
    ]
    for source, date_value in sources:
        if date_value:
            return date_value, source, ""
    return None, "", "no_verified_date"


# Opens a page and returns its verified publication date, or None when missing.
def verify_date(url: str, timeout: int = 20) -> datetime | None:
    date_value, _, _ = verify_date_details(url, timeout)
    return date_value


# Loads the Exa API key from backend/.env or the current environment.
def load_exa_api_key() -> str:
    load_dotenv(PROJECT_DIR / "backend" / ".env")
    return os.getenv("EXA_API_KEY", "").strip()


# Loads tool names and official sites from the project registry.
def load_tools(limit: int = 0) -> list[dict]:
    data = load_json(MONTHLY_TOOLS_FILE, {"tool_records": [], "tools": []})
    records = [dict(item) for item in data.get("tool_records") or [] if isinstance(item, dict)]
    if not records:
        records = [{"tool": item, "official_site": ""} for item in data.get("tools") or [] if isinstance(item, str)]
    selected = records[:limit] if limit > 0 else records
    return [
        {
            "tool": clean_text(item.get("tool") or item.get("company") or ""),
            "official_site": normalize_site(item.get("official_site") or ""),
            "official_domain": normalize_domain(item.get("official_site") or ""),
        }
        for item in selected
        if clean_text(item.get("tool") or item.get("company") or "")
    ]


# Normalizes an official site so Exa can use it inside site: queries.
def normalize_site(site: str) -> str:
    value = str(site or "").strip().replace("https://", "").replace("http://", "").strip("/")
    if not value:
        return ""
    parsed = urlparse(f"https://{value}")
    path = parsed.path.strip("/")
    host = parsed.netloc.lower().removeprefix("www.")
    return f"{host}/{path}" if path else host


# Normalizes an official site down to the root domain for broad phase-one search.
def normalize_domain(site: str) -> str:
    value = str(site or "").strip().replace("https://", "").replace("http://", "").strip("/")
    if not value:
        return ""
    parsed = urlparse(f"https://{value}")
    return parsed.netloc.lower().removeprefix("www.")


# Builds the three requested Exa search phases for one tool.
def build_old_search_phases(tool: str, official_domain: str) -> list[dict]:
    if official_domain:
        query = f'site:{official_domain} last "{tool}" update'
    else:
        query = f'last "{tool}" update'
    return [{"strategy": "old_site_last_update", "phase": 1, "query": query}]


# Builds the newer three-phase Exa search strategy for one tool.
def build_new_search_phases(tool: str, official_site: str) -> list[dict]:
    phases = []
    if official_site:
        phases.append({"strategy": "new_three_phase", "phase": 1, "query": f'site:{official_site} "changelog" OR "release notes"'})
        phases.append({"strategy": "new_three_phase", "phase": 2, "query": f'"{tool}" changelog site:{official_site}'})
    phases.append({"strategy": "new_three_phase", "phase": 3, "query": f'"{tool}" release notes'})
    return phases


# Builds every enabled strategy so each tool gets the old and new searches.
def build_search_strategies(tool: str, official_site: str, official_domain: str) -> list[dict]:
    return [
        {"strategy": "old_site_last_update", "phases": build_old_search_phases(tool, official_domain)},
        {"strategy": "new_three_phase", "phases": build_new_search_phases(tool, official_site)},
    ]


# Calls Exa and returns raw result rows for one query.
def exa_search(api_key: str, query: str, results: int, timeout: int) -> tuple[list[dict], str]:
    payload = {
        "query": query,
        "numResults": results,
        "type": "neural",
        "contents": {"text": False, "highlights": False},
    }
    try:
        response = httpx.post(
            EXA_SEARCH_URL,
            headers={"Accept": "application/json", "Content-Type": "application/json", "x-api-key": api_key},
            json=payload,
            timeout=timeout,
        )
        if response.status_code >= 400:
            return [], f"exa_http_{response.status_code}:{response.text[:220]}"
        return list((response.json() or {}).get("results") or []), ""
    except httpx.HTTPError as exc:
        return [], f"exa_failed:{type(exc).__name__}"


# Decides whether a verified page date is inside the last seven days.
def is_recent(date_value: datetime, now: datetime) -> bool:
    return date_value >= now - timedelta(days=7)


# Converts one Exa result into an accepted or rejected report row.
def evaluate_result(result: dict, now: datetime, timeout: int) -> tuple[dict | None, dict | None]:
    url = str(result.get("url") or "").strip()
    title = clean_text(result.get("title") or "")
    if not url:
        return None, {"title": title, "url": "", "reason": "missing_url"}
    date_value, source, reason = verify_date_details(url, timeout)
    row = {"title": title, "url": url}
    if reason:
        return None, {**row, "reason": reason}
    if not date_value:
        return None, {**row, "reason": "no_verified_date"}
    if not is_recent(date_value, now):
        return None, {**row, "date": date_value.isoformat(), "date_source": source, "reason": "outside_last_7_days"}
    return {**row, "date": date_value.isoformat(), "date_source": source}, None


# Runs all three Exa phases until one phase accepts at least one update.
def canonical_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return urlunparse((scheme, host, path, "", parsed.query, ""))


# Merges accepted updates from both strategies and keeps strategy provenance.
def merge_accepted_updates(rows: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for row in rows:
        key = canonical_url(row.get("url", ""))
        if not key:
            continue
        strategy = row.get("strategy")
        phase = row.get("phase")
        if key not in merged:
            clean_row = {name: value for name, value in row.items() if name not in {"strategy", "phase"}}
            clean_row["strategies"] = [strategy] if strategy else []
            clean_row["strategy_phases"] = [{"strategy": strategy, "phase": phase}] if strategy else []
            merged[key] = clean_row
            continue
        existing = merged[key]
        if strategy and strategy not in existing["strategies"]:
            existing["strategies"].append(strategy)
        strategy_phase = {"strategy": strategy, "phase": phase}
        if strategy and strategy_phase not in existing["strategy_phases"]:
            existing["strategy_phases"].append(strategy_phase)
    return list(merged.values())


# Runs one search strategy until a phase accepts at least one update.
def search_strategy(api_key: str, strategy: dict, args: argparse.Namespace, now: datetime) -> dict:
    accepted = []
    rejected = []
    phase_reports = []
    pages_checked = 0
    for phase in strategy["phases"]:
        raw_results, error = exa_search(api_key, phase["query"], args.results, args.timeout)
        phase_report = {
            "strategy": phase["strategy"],
            "phase": phase["phase"],
            "query": phase["query"],
            "raw_results": len(raw_results),
            "error": error,
        }
        phase_reports.append(phase_report)
        if error:
            rejected.append({"strategy": phase["strategy"], "phase": phase["phase"], "query": phase["query"], "reason": error})
            continue
        for result in raw_results:
            if args.max_pages_per_tool and pages_checked >= args.max_pages_per_tool:
                rejected.append({"strategy": phase["strategy"], "phase": phase["phase"], "query": phase["query"], "reason": "max_pages_per_tool_reached"})
                break
            pages_checked += 1
            accepted_row, rejected_row = evaluate_result(result, now, args.page_timeout)
            if accepted_row:
                accepted.append({**accepted_row, "strategy": phase["strategy"], "phase": phase["phase"]})
            if rejected_row:
                rejected.append({**rejected_row, "strategy": phase["strategy"], "phase": phase["phase"]})
        if accepted:
            return {
                "strategy": strategy["strategy"],
                "successful_phase": phase["phase"],
                "pages_checked": pages_checked,
                "accepted_updates": accepted,
                "rejected_updates": rejected,
                "phases": phase_reports,
            }
        if args.delay > 0:
            time.sleep(args.delay)
    return {
        "strategy": strategy["strategy"],
        "successful_phase": None,
        "pages_checked": pages_checked,
        "accepted_updates": accepted,
        "rejected_updates": rejected,
        "phases": phase_reports,
    }


# Runs old and new Exa strategies for one tool, then deduplicates accepted updates.
def search_tool(api_key: str, tool: dict, args: argparse.Namespace, now: datetime) -> dict:
    strategy_reports = []
    all_accepted = []
    all_rejected = []
    all_phases = []
    for strategy in build_search_strategies(tool["tool"], tool["official_site"], tool["official_domain"]):
        report = search_strategy(api_key, strategy, args, now)
        strategy_reports.append(report)
        all_accepted.extend(report["accepted_updates"])
        all_rejected.extend(report["rejected_updates"])
        all_phases.extend(report["phases"])
        if args.stop_after_first_accepted and report["accepted_updates"]:
            break
    accepted = merge_accepted_updates(all_accepted)
    successful_strategies = [item["strategy"] for item in strategy_reports if item["accepted_updates"]]
    successful_phases = {
        item["strategy"]: item["successful_phase"]
        for item in strategy_reports
        if item["successful_phase"] is not None
    }
    return {
        "tool": tool["tool"],
        "official_site": tool["official_site"],
        "official_domain": tool["official_domain"],
        "successful_strategies": successful_strategies,
        "successful_phases": successful_phases,
        "accepted_updates": accepted,
        "rejected_updates": all_rejected,
        "phases": all_phases,
        "strategy_reports": strategy_reports,
    }


# Writes the final JSON report to data/news.
def write_report(report: dict) -> None:
    safe_write_json(OUTPUT_PATH, report)


# Runs the first verification sample before the full Exa workflow is added.
def failed_tool_row(tool: dict, reason: str) -> dict:
    return {
        "tool": tool["tool"],
        "official_site": tool.get("official_site", ""),
        "official_domain": tool.get("official_domain", ""),
        "successful_strategies": [],
        "successful_phases": {},
        "accepted_updates": [],
        "rejected_updates": [{"reason": reason}],
        "phases": [],
        "strategy_reports": [],
        "error": reason,
    }


def run_verify_sample() -> int:
    rows = []
    for url in SAMPLE_URLS:
        date_value = verify_date(url)
        rows.append({"url": url, "date": date_value.isoformat() if date_value else None})
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


# Runs the full Exa recent-update scan for all configured tools.
def run_full_scan(args: argparse.Namespace) -> int:
    api_key = load_exa_api_key()
    if not api_key:
        print("Missing EXA_API_KEY in backend/.env or environment.")
        return 2
    now = utc_now()
    tools = load_tools(args.limit)
    rows: list[dict | None] = [None] * len(tools)
    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(search_tool, api_key, tool, args, now): (index, tool)
                for index, tool in enumerate(tools)
            }
            for future in as_completed(futures):
                index, tool = futures[future]
                try:
                    row = future.result()
                except Exception as exc:
                    row = failed_tool_row(tool, f"parallel_tool_failed:{type(exc).__name__}:{exc}")
                rows[index] = row
                print(
                    f"{index + 1}/{len(tools)} {tool['tool']}: "
                    f"{len(row['accepted_updates'])} accepted, strategies={','.join(row['successful_strategies']) or '-'}",
                    flush=True,
                )
    else:
        for index, tool in enumerate(tools):
            row = search_tool(api_key, tool, args, now)
            rows[index] = row
            print(
                f"{index + 1}/{len(tools)} {tool['tool']}: "
                f"{len(row['accepted_updates'])} accepted, strategies={','.join(row['successful_strategies']) or '-'}",
                flush=True,
            )
            if args.delay > 0:
                time.sleep(args.delay)
    rows = [row for row in rows if row is not None]
    report = {
        "generated_at": now.isoformat(),
        "window": {
            "days": 7,
            "start": (now - timedelta(days=7)).isoformat(),
            "end": now.isoformat(),
        },
        "settings": {
            "results_per_phase": args.results,
            "exa_timeout_seconds": args.timeout,
            "page_timeout_seconds": args.page_timeout,
            "delay_seconds": args.delay,
            "limit": args.limit,
            "workers": args.workers,
            "max_pages_per_tool": args.max_pages_per_tool,
            "stop_after_first_accepted": args.stop_after_first_accepted,
            "search_strategies": ["old_site_last_update", "new_three_phase"],
        },
        "summary": {
            "tools_tested": len(rows),
            "tools_with_accepted_updates": sum(1 for row in rows if row["accepted_updates"]),
            "tools_found_by_old_strategy": sum(1 for row in rows if "old_site_last_update" in row["successful_strategies"]),
            "tools_found_by_new_strategy": sum(1 for row in rows if "new_three_phase" in row["successful_strategies"]),
            "accepted_updates": sum(len(row["accepted_updates"]) for row in rows),
            "rejected_updates": sum(len(row["rejected_updates"]) for row in rows),
        },
        "tools": rows,
    }
    write_report(report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"JSON report: {OUTPUT_PATH}")
    return 0


# Parses command-line options for this diagnostic script.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find recent AI tool updates with Exa and verified page dates.")
    parser.add_argument("--verify-sample", action="store_true", help="Test verify_date on three real pages.")
    parser.add_argument("--fast", action="store_true", help="Use faster defaults for exploratory full runs.")
    parser.add_argument("--results", type=int, default=8, help="Exa results to inspect per phase.")
    parser.add_argument("--timeout", type=int, default=30, help="Exa request timeout in seconds.")
    parser.add_argument("--page-timeout", type=int, default=20, help="Page fetch timeout in seconds.")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between Exa phases and tools.")
    parser.add_argument("--limit", type=int, default=0, help="Optional number of tools to scan; 0 means all tools.")
    parser.add_argument("--workers", type=int, default=1, help="Number of tools to process in parallel.")
    parser.add_argument("--max-pages-per-tool", type=int, default=0, help="Maximum verified pages per strategy; 0 means unlimited.")
    parser.add_argument("--stop-after-first-accepted", action="store_true", help="Skip remaining strategies after one accepted result.")
    args = parser.parse_args()
    if args.fast:
        args.results = min(args.results, 3)
        args.page_timeout = min(args.page_timeout, 6)
        args.delay = 0
        if args.workers <= 1:
            args.workers = 4
        args.max_pages_per_tool = args.max_pages_per_tool or 6
        args.stop_after_first_accepted = True
    return args


# Dispatches the requested script mode.
def main() -> int:
    args = parse_args()
    if args.verify_sample:
        return run_verify_sample()
    return run_full_scan(args)


if __name__ == "__main__":
    raise SystemExit(main())
