# Runs a strict Exa and SearXNG discovery test without calling Gemini.
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config.settings import (  # noqa: E402
    AI_UPDATES_LOOKBACK_DAYS,
    AI_UPDATES_SEARXNG_CATEGORIES,
    AI_UPDATES_SEARXNG_TIME_RANGE,
    AI_UPDATES_SEARXNG_TIMEOUT,
    BACKEND_DIR,
    EXA_API_KEY,
    MONTHLY_TOOLS_FILE,
    SEARXNG_URL,
    clean_text,
    load_json,
    parse_result_datetime,
    recency_cutoff_query_token,
    safe_write_json,
    source_domain,
    utc_now,
)
from backend.pipeline.fetching.sources import (  # noqa: E402
    COURSE_DIRECT_PATHS,
    COURSE_PLATFORM_NAMES,
    course_url_is_direct,
)

OUTPUT_DIR = PROJECT_DIR / "data" / "news"
JSON_REPORT = OUTPUT_DIR / "strict_discovery_test_report.json"
MD_REPORT = OUTPUT_DIR / "strict_discovery_test_report.md"
STRICT_EXA_VARIANT_LIMIT = int(os.getenv("STRICT_EXA_VARIANT_LIMIT", "2") or "2")
STRICT_PAGE_TIMEOUT_SECONDS = int(os.getenv("STRICT_PAGE_TIMEOUT_SECONDS", "5") or "5")

UPDATE_RE = re.compile(
    r"\b(update|updates|updated|new feature|release|released|launch|launched|rollout|announced|"
    r"announcement|available|changelog|release notes|introducing|now supports|what's new|whats new|deploying|redeploying)\b",
    re.IGNORECASE,
)
AI_TOOL_RE = re.compile(r"\b(ai|artificial intelligence|gemini|gpt|claude|copilot|agent|model|tool|app|platform)\b", re.IGNORECASE)
COURSE_RE = re.compile(r"\b(course|courses|class|learning path|training|certificate|certification|academy|learn)\b", re.IGNORECASE)


# Returns true when a timestamp is inside the configured weekly window.
def within_window(value: str) -> bool:
    dt = parse_result_datetime(value)
    if not dt:
        return False
    return dt >= (utc_now() - __import__("datetime").timedelta(days=max(1, AI_UPDATES_LOOKBACK_DAYS)))


# Loads tool records directly from the registry without refreshing it.
def load_tool_records() -> list[dict]:
    data = load_json(MONTHLY_TOOLS_FILE, {"tool_records": [], "tools": []})
    records = [dict(item) for item in data.get("tool_records") or [] if isinstance(item, dict)]
    if records:
        return records
    return [{"tool": item, "company": "", "official_site": ""} for item in data.get("tools") or [] if isinstance(item, str)]


# Builds a safe site token for search queries.
def site_token(site: str) -> str:
    value = str(site or "").strip().replace("https://", "").replace("http://", "").strip("/")
    return value


# Reads a result page so the test confirms the page itself is reachable.
def fetch_page_text(url: str) -> tuple[str, str]:
    try:
        response = requests.get(
            url,
            timeout=STRICT_PAGE_TIMEOUT_SECONDS,
            headers={"User-Agent": "AI-Newsletter-StrictDiscoveryTest/1.0"},
            allow_redirects=True,
        )
        if response.status_code >= 400:
            return "", f"page_http_{response.status_code}"
        text = clean_text(response.text)[:4000]
        return text, "ok"
    except Exception as exc:
        return "", f"page_fetch_failed:{type(exc).__name__}"


# Scores one news result against the strict tool-update rules.
def score_news_result(raw: dict, *, tool: str, source: str, query: str) -> dict:
    title = clean_text(raw.get("title") or "")
    url = str(raw.get("url") or "").strip()
    snippet = clean_text(raw.get("text") or raw.get("content") or raw.get("snippet") or " ".join(raw.get("highlights") or []))
    published = str(raw.get("publishedDate") or raw.get("published_date") or raw.get("date") or "")
    page_text, page_status = fetch_page_text(url) if url else ("", "missing_url")
    evidence = f"{title} {snippet} {page_text[:1600]}"
    result_evidence = f"{title} {snippet} {url}"
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.strip("/").split("/") if part]
    tool_key = clean_text(tool).lower()
    title_url_evidence = f"{title} {url}"
    has_tool = bool(tool_key and tool_key in title_url_evidence.lower())
    date_ok = within_window(published) if published else source == "searxng" and AI_UPDATES_SEARXNG_TIME_RANGE == "week"
    release_path = any(part in {"changelog", "release-notes", "release_notes", "releases", "updates", "whats-new", "what-is-new"} for part in path_parts)
    reasons = []
    if not title or not url:
        reasons.append("missing_title_or_url")
    if not has_tool:
        reasons.append("missing_tool_name_on_page")
    if not date_ok:
        reasons.append("outside_or_missing_week_window")
    if page_status != "ok":
        reasons.append(page_status)
    passed = not reasons
    return {
        "passed": passed,
        "tool": tool,
        "source": source,
        "site": source_domain(url),
        "title": title,
        "url": url,
        "published": published,
        "query": query,
        "page_status": page_status,
        "reasons": reasons,
        "score": sum([has_tool, date_ok, page_status == "ok", release_path]),
    }


# Scores one course result against direct-course page rules.
def score_course_result(raw: dict, *, platform: str, source: str, query: str) -> dict:
    title = clean_text(raw.get("title") or "")
    url = str(raw.get("url") or "").strip()
    snippet = clean_text(raw.get("text") or raw.get("content") or raw.get("snippet") or " ".join(raw.get("highlights") or []))
    page_text, page_status = fetch_page_text(url) if url else ("", "missing_url")
    evidence = f"{title} {snippet} {page_text[:1600]}"
    direct = course_url_is_direct(url, title=title, content=evidence)
    has_course = bool(COURSE_RE.search(evidence))
    has_ai = bool(AI_TOOL_RE.search(evidence))
    reasons = []
    if not title or not url:
        reasons.append("missing_title_or_url")
    if not direct:
        reasons.append("not_direct_course_url")
    if not has_course:
        reasons.append("missing_course_signal")
    if not has_ai:
        reasons.append("missing_ai_signal")
    if page_status != "ok":
        reasons.append(page_status)
    passed = not reasons
    return {
        "passed": passed,
        "platform": platform,
        "source": source,
        "site": source_domain(url),
        "title": title,
        "url": url,
        "query": query,
        "page_status": page_status,
        "reasons": reasons,
        "score": sum([direct, has_course, has_ai, page_status == "ok"]),
    }


# Calls Exa search with the weekly window and compact result payload.
def exa_search(query: str, *, results: int = 4) -> tuple[list[dict], str]:
    if not EXA_API_KEY:
        return [], "missing_exa_api_key"
    try:
        response = requests.post(
            "https://api.exa.ai/search",
            headers={"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY},
            json={
                "query": query,
                "numResults": results,
                "type": "neural",
                "startPublishedDate": recency_cutoff_query_token(),
                "contents": {"text": True, "highlights": True},
            },
            timeout=20,
        )
        if response.status_code >= 400:
            return [], f"exa_http_{response.status_code}:{response.text[:220]}"
        return list((response.json() or {}).get("results") or []), ""
    except Exception as exc:
        return [], f"exa_request_failed:{type(exc).__name__}"


# Calls SearXNG search with the weekly window.
def searxng_search(query: str, *, results: int = 4) -> tuple[list[dict], str]:
    try:
        response = requests.get(
            f"{SEARXNG_URL.rstrip('/')}/search",
            params={
                "q": query,
                "format": "json",
                "language": "en",
                "engines": "google,bing,brave",
                "time_range": AI_UPDATES_SEARXNG_TIME_RANGE,
                "categories": AI_UPDATES_SEARXNG_CATEGORIES,
                "pageno": 1,
            },
            timeout=AI_UPDATES_SEARXNG_TIMEOUT,
        )
        if response.status_code >= 400:
            return [], f"searxng_http_{response.status_code}:{response.text[:220]}"
        return list((response.json() or {}).get("results") or [])[:results], ""
    except Exception as exc:
        return [], f"searxng_request_failed:{type(exc).__name__}"


# Builds Exa query variants for one tool before the test marks it failed.
def news_exa_queries(tool: str, company: str, official_site: str) -> list[str]:
    root = official_site.split("/", 1)[0] if official_site else ""
    update_terms = '(update OR updates OR changelog OR "release notes" OR "what\'s new" OR "new feature" OR release OR launch OR rollout)'
    queries = []
    if official_site:
        queries.append(f'site:{official_site} "{tool}" {update_terms}')
    if root and root != official_site:
        queries.append(f'site:{root} "{tool}" {update_terms}')
    if company and company.lower() != tool.lower():
        queries.append(f'"{tool}" "{company}" {update_terms}')
    queries.append(f'"{tool}" {update_terms}')
    seen = set()
    output = []
    for query in queries:
        key = re.sub(r"\s+", " ", query.lower())
        if key not in seen:
            seen.add(key)
            output.append(query)
    return output


# Tests one news tool through Exa official-site search and SearXNG open-web search.
def test_news_tool(tool_record: dict) -> dict:
    tool = clean_text(tool_record.get("tool") or tool_record.get("company") or "")
    company = clean_text(tool_record.get("company") or "")
    official_site = site_token(tool_record.get("official_site") or "")
    searxng_query = f'"{tool}" "{company}" update OR changelog OR "new feature" OR release OR launch'
    results = []
    errors = []
    exa_queries = news_exa_queries(tool, company, official_site)
    if official_site:
        for index, exa_query in enumerate(exa_queries):
            raw, error = exa_search(exa_query, results=2)
            errors.extend([error] if error else [])
            scored = [score_news_result(item, tool=tool, source="exa", query=exa_query) for item in raw]
            results.extend(scored)
            if any(item["passed"] for item in scored):
                break
            if index + 1 >= max(1, STRICT_EXA_VARIANT_LIMIT):
                break
    else:
        errors.append("missing_official_site")
        exa_query = exa_queries[-1]
        raw, error = exa_search(exa_query, results=3)
        errors.extend([error] if error else [])
        results.extend(score_news_result(item, tool=tool, source="exa", query=exa_query) for item in raw)
    raw, error = searxng_search(searxng_query)
    errors.extend([error] if error else [])
    results.extend(score_news_result(item, tool=tool, source="searxng", query=searxng_query) for item in raw)
    passed_results = sorted([item for item in results if item["passed"]], key=lambda item: item["score"], reverse=True)
    failed_reasons = Counter(reason for item in results for reason in item.get("reasons") or [])
    return {
        "tool": tool,
        "company": company,
        "official_site": official_site,
        "passed": bool(passed_results),
        "best_4_sources": passed_results[:4],
        "raw_checked": len(results),
        "errors": errors,
        "failure_reasons": dict(failed_reasons),
        "sample_failures": sorted([item for item in results if not item["passed"]], key=lambda item: item["score"], reverse=True)[:3],
    }


# Tests one course platform through Exa site search and SearXNG platform-name search.
def test_course_platform(domain: str, platform: str) -> dict:
    exa_query = f'site:{domain} "AI course" OR "generative AI course" OR "prompt engineering course" certificate'
    searxng_query = f'"{platform}" "AI course" OR "generative AI course" OR "prompt engineering course" certificate'
    results = []
    errors = []
    raw, error = exa_search(exa_query)
    errors.extend([error] if error else [])
    results.extend(score_course_result(item, platform=platform, source="exa", query=exa_query) for item in raw)
    raw, error = searxng_search(searxng_query)
    errors.extend([error] if error else [])
    results.extend(score_course_result(item, platform=platform, source="searxng", query=searxng_query) for item in raw)
    passed_results = sorted([item for item in results if item["passed"]], key=lambda item: item["score"], reverse=True)
    failed_reasons = Counter(reason for item in results for reason in item.get("reasons") or [])
    return {
        "platform": platform,
        "domain": domain,
        "passed": bool(passed_results),
        "best_4_sources": passed_results[:4],
        "raw_checked": len(results),
        "errors": errors,
        "failure_reasons": dict(failed_reasons),
        "sample_failures": sorted([item for item in results if not item["passed"]], key=lambda item: item["score"], reverse=True)[:3],
    }


# Runs general AI-tool update queries, including Saudi-focused queries.
def test_general_news_queries() -> list[dict]:
    queries = [
        "AI tool update news this week new feature release",
        "new AI product update launch this week tool",
        "Saudi Arabia AI tool update launch news",
        "Saudi Arabia generative AI platform new feature news",
    ]
    rows = []
    for query in queries:
        source_rows = []
        for source, search in (("exa", exa_search), ("searxng", searxng_search)):
            raw, error = search(query)
            scored = [score_news_result(item, tool="AI", source=source, query=query) for item in raw]
            source_rows.append({
                "source": source,
                "query": query,
                "passed": any(item["passed"] for item in scored),
                "best_4_sources": sorted([item for item in scored if item["passed"]], key=lambda item: item["score"], reverse=True)[:4],
                "raw_checked": len(scored),
                "error": error,
                "failure_reasons": dict(Counter(reason for item in scored for reason in item.get("reasons") or [])),
            })
        rows.append({"query": query, "sources": source_rows})
    return rows


# Writes the JSON and Markdown reports for human review.
def write_reports(report: dict) -> None:
    safe_write_json(JSON_REPORT, report)
    lines = [
        "# Strict Discovery Test Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Window: last {report['lookback_days']} days, cutoff {report['cutoff_date']}",
        f"- Tools tested: {report['summary']['news_tools_tested']}",
        f"- News tools passed: {report['summary']['news_tools_passed']}",
        f"- Course platforms tested: {report['summary']['course_platforms_tested']}",
        f"- Course platforms passed: {report['summary']['course_platforms_passed']}",
        "",
        "## News Tools",
    ]
    for item in report["news_tools"]:
        status = "PASS" if item["passed"] else "FAIL"
        best = item["best_4_sources"][0]["title"] if item["best_4_sources"] else "; ".join(item["failure_reasons"].keys()) or "; ".join(item["errors"])
        lines.append(f"- {status} | {item['tool']} | {item['official_site']} | {best}")
    lines.extend(["", "## Courses"])
    for item in report["courses"]:
        status = "PASS" if item["passed"] else "FAIL"
        best = item["best_4_sources"][0]["title"] if item["best_4_sources"] else "; ".join(item["failure_reasons"].keys()) or "; ".join(item["errors"])
        lines.append(f"- {status} | {item['platform']} | {item['domain']} | {best}")
    MD_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Runs the full strict discovery test.
def main() -> int:
    started = time.time()
    tools = load_tool_records()
    course_rows = sorted((domain, COURSE_PLATFORM_NAMES.get(domain) or domain) for domain in COURSE_DIRECT_PATHS)
    news_reports = [test_news_tool(item) for item in tools]
    course_reports = [test_course_platform(domain, platform) for domain, platform in course_rows]
    general_reports = test_general_news_queries()
    report = {
        "generated_at": utc_now().isoformat(),
        "lookback_days": AI_UPDATES_LOOKBACK_DAYS,
        "cutoff_date": recency_cutoff_query_token(),
        "registry_path": str(MONTHLY_TOOLS_FILE),
        "backend_dir": str(BACKEND_DIR),
        "searxng_url": SEARXNG_URL,
        "general_news_queries": general_reports,
        "news_tools": news_reports,
        "courses": course_reports,
        "summary": {
            "seconds": round(time.time() - started, 2),
            "news_tools_tested": len(news_reports),
            "news_tools_passed": sum(1 for item in news_reports if item["passed"]),
            "course_platforms_tested": len(course_reports),
            "course_platforms_passed": sum(1 for item in course_reports if item["passed"]),
            "general_query_sources_passed": sum(1 for row in general_reports for source in row["sources"] if source["passed"]),
        },
    }
    write_reports(report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"JSON report: {JSON_REPORT}")
    print(f"Markdown report: {MD_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
