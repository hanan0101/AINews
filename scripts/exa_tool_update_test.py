# Tests Exa with official-site tool update queries.
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config.settings import EXA_API_KEY, MONTHLY_TOOLS_FILE, clean_text, load_json, safe_write_json, source_domain, utc_now  # noqa: E402

OUTPUT_DIR = PROJECT_DIR / "data" / "news"
JSON_REPORT = OUTPUT_DIR / "exa_tool_update_test.json"
MD_REPORT = OUTPUT_DIR / "exa_tool_update_test.md"


# Loads tool records from the monthly registry.
def load_tool_records() -> list[dict]:
    data = load_json(MONTHLY_TOOLS_FILE, {"tool_records": [], "tools": []})
    records = [dict(item) for item in data.get("tool_records") or [] if isinstance(item, dict)]
    if records:
        return records
    return [{"tool": item, "company": "", "official_site": ""} for item in data.get("tools") or [] if isinstance(item, str)]


# Normalizes an official site into the root domain for flexible Exa site search.
def site_token(site: str = "") -> str:
    value = str(site or "").strip().replace("https://", "").replace("http://", "").strip("/")
    if not value:
        return ""
    parsed = urlparse(f"https://{value}")
    return parsed.netloc.lower().replace("www.", "")


# Builds the exact Exa query style requested for one tool.
def build_query(tool: str, official_site: str) -> str:
    if official_site:
        return f'site:{official_site} last "{tool}" update'
    return f'last "{tool}" update'


# Calls Exa search and returns raw results plus timing and error details.
# Parses Exa date values for newest-first sorting.
def parse_result_date(value: str = "") -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


# Sorts Exa results by published date, keeping undated items last.
def newest_first(results: list[dict]) -> list[dict]:
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(results, key=lambda item: parse_result_date(item.get("publishedDate") or item.get("date") or "") or oldest, reverse=True)


def exa_search(query: str, *, results: int, timeout: int, start_published_date: str = "", newest: bool = False, fetch_results: int = 0) -> tuple[list[dict], float, str]:
    started = time.perf_counter()
    if not EXA_API_KEY:
        return [], 0.0, "missing_exa_api_key"
    try:
        payload = {
            "query": query,
            "numResults": max(results, fetch_results) if newest else results,
            "type": "neural",
            "contents": {"text": True, "highlights": True},
        }
        if start_published_date:
            payload["startPublishedDate"] = start_published_date
        response = requests.post(
            "https://api.exa.ai/search",
            headers={"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY},
            json=payload,
            timeout=timeout,
        )
        elapsed = round(time.perf_counter() - started, 3)
        if response.status_code >= 400:
            return [], elapsed, f"exa_http_{response.status_code}:{response.text[:220]}"
        rows = list((response.json() or {}).get("results") or [])
        return (newest_first(rows)[:results] if newest else rows), elapsed, ""
    except Exception as exc:
        elapsed = round(time.perf_counter() - started, 3)
        return [], elapsed, f"{type(exc).__name__}:{exc}"


# Converts Exa result objects into report-friendly rows.
def normalize_results(results: list[dict]) -> list[dict]:
    rows = []
    for item in results:
        url = str(item.get("url") or "").strip()
        rows.append(
            {
                "title": clean_text(item.get("title") or ""),
                "url": url,
                "domain": source_domain(url),
                "published": clean_text(item.get("publishedDate") or item.get("date") or ""),
            }
        )
    return rows


# Writes JSON and Markdown reports for review.
def write_reports(report: dict) -> None:
    safe_write_json(JSON_REPORT, report)
    lines = [
        "# Exa Tool Update Test",
        "",
        f"- Generated: {report['generated_at']}",
        "- Query style: `site:official-site last \"Tool\" update`",
        f"- Tools tested: {report['summary']['tools_tested']}",
        f"- Tools with results: {report['summary']['tools_with_results']}",
        f"- Average response seconds: {report['summary']['average_response_seconds']}",
        "",
        "| Tool | Official Site | Query | Seconds | # | Title | Link | Domain | Published |",
        "|---|---|---|---:|---:|---|---|---|---|",
    ]
    for row in report["queries"]:
        if not row["results"]:
            reason = row["error"] or "no_results"
            lines.append(f"| {row['tool']} | {row['official_site'] or '-'} | `{row['query']}` | {row['seconds']} | 0 | {reason} | - | - | - |")
            continue
        for index, item in enumerate(row["results"], 1):
            title = (item["title"] or "-").replace("|", "\\|")
            lines.append(
                f"| {row['tool']} | {row['official_site'] or '-'} | `{row['query']}` | {row['seconds']} | "
                f"{index} | {title} | {item['url'] or '-'} | {item['domain'] or '-'} | {item['published'] or '-'} |"
            )
    MD_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Parses command-line options for the Exa diagnostic run.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test Exa with site:official-site last Tool update queries.")
    parser.add_argument("--results", type=int, default=4, help="Results to fetch for every tool.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout per Exa request.")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds to wait between tools.")
    parser.add_argument("--limit", type=int, default=0, help="Optional number of tools to test; 0 means all tools.")
    parser.add_argument("--last-week", action="store_true", help="Only request results published in the last 7 days.")
    parser.add_argument("--newest", action="store_true", help="Fetch more results and keep the newest ones by published date.")
    parser.add_argument("--fetch-results", type=int, default=12, help="Results to fetch before newest-first sorting.")
    return parser.parse_args()


# Runs the full Exa test and saves reports.
def main() -> int:
    args = parse_args()
    records = load_tool_records()
    if args.limit > 0:
        records = records[: args.limit]
    start_published_date = (utc_now() - timedelta(days=7)).date().isoformat() if args.last_week else ""
    rows = []
    for record in records:
        tool = clean_text(record.get("tool") or record.get("company") or "")
        official_site = site_token(record.get("official_site") or "")
        query = build_query(tool, official_site)
        raw, seconds, error = exa_search(
            query,
            results=args.results,
            timeout=args.timeout,
            start_published_date=start_published_date,
            newest=args.newest,
            fetch_results=args.fetch_results,
        )
        results = normalize_results(raw)
        rows.append(
            {
                "tool": tool,
                "company": clean_text(record.get("company") or ""),
                "official_site": official_site,
                "query": query,
                "seconds": seconds,
                "error": error,
                "raw_count": len(raw),
                "results": results,
            }
        )
        print(f"{tool}: {len(results)} results, seconds={seconds}, query={query}", flush=True)
        if args.delay > 0:
            time.sleep(args.delay)
    timings = [row["seconds"] for row in rows if row["seconds"]]
    report = {
        "generated_at": utc_now().isoformat(),
        "settings": {
            "results_per_tool": args.results,
            "timeout_seconds": args.timeout,
            "delay_seconds": args.delay,
            "start_published_date": start_published_date,
            "newest": args.newest,
            "fetch_results": args.fetch_results,
        },
        "summary": {
            "tools_tested": len(rows),
            "tools_with_results": sum(1 for row in rows if row["results"]),
            "average_response_seconds": round(sum(timings) / len(timings), 3) if timings else 0,
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
