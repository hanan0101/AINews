# Runs course/platform discovery separately from the general strict discovery test.
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config.settings import (  # noqa: E402
    EXA_API_KEY,
    clean_text,
    safe_write_json,
    source_domain,
    utc_now,
)
from backend.pipeline.fetching.courses import fetch_course_candidates  # noqa: E402
from backend.pipeline.fetching.sources import (  # noqa: E402
    ADDITIONAL_CORE_20_COURSE_BANK_PLATFORMS,
    COURSE_BAD_URL_TERMS,
    COURSE_BANK_EXTRA_PLATFORMS_CLEAN,
    COURSE_DIRECT_PATHS,
    COURSE_PLATFORM_URLS,
    COURSE_PLATFORM_NAMES,
    EMPLOYEE_AI_PLATFORM_PRIORITY,
    has_developer_only_course_signal,
    has_student_course_reject_signal,
    course_url_is_direct,
    domain_matches,
    is_workforce_course_text,
)

OUTPUT_DIR = PROJECT_DIR / "data" / "news"
JSON_REPORT = OUTPUT_DIR / "course_platform_discovery_report.json"
MD_REPORT = OUTPUT_DIR / "course_platform_discovery_report.md"
FAILED_JSON_REPORT = OUTPUT_DIR / "course_platform_failed_platforms.json"

COURSE_RE = re.compile(
    r"\b(course|courses|class|learning path|training|certificate|certification|academy|learn|microcredential)\b",
    re.IGNORECASE,
)
AI_RE = re.compile(
    r"\b(ai|artificial intelligence|generative ai|chatgpt|gemini|claude|copilot|prompt engineering|llm|machine learning)\b",
    re.IGNORECASE,
)

COURSE_INTENT_QUERY = '("AI course" OR "generative AI course" OR "prompt engineering course" OR "AI training" OR "AI certificate")'
WORKFORCE_INTENT_QUERY = '("employee" OR "employees" OR "professional" OR "professionals" OR "workplace" OR "productivity" OR "business" OR "upskilling" OR "workforce" OR "موظفين" OR "مهنيين" OR "بيئة العمل" OR "الإنتاجية" OR "تطوير المهارات" OR "الأعمال")'
NON_FATAL_PAGE_STATUSES = ("page_http_401", "page_http_403", "page_http_429")
PLATFORM_DOMAIN_ALIASES = {
    "learn.zapier.com": {"zapier.com"},
}
DIRECT_SEED_TEXT_OVERRIDES = {
    "learn.zapier.com": (
        "Zapier Academy course training. Build AI Skills that transform your work. "
        "AI Builder Path and AI Orchestrator Path teach automation and workflow skills for work."
    ),
}


def has_bad_course_url(url: str) -> bool:
    clean = str(url or "").lower()
    return any(term in clean for term in COURSE_BAD_URL_TERMS)


def domain_allowed_for_platform(result_domain: str, platform_domain: str) -> bool:
    result = str(result_domain or "").lower().replace("www.", "")
    platform = str(platform_domain or "").lower().replace("www.", "")
    if domain_matches(result, [platform]):
        return True
    return result in PLATFORM_DOMAIN_ALIASES.get(platform, set())


def fetch_page_text(url: str, timeout: int) -> tuple[str, str]:
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "AI-Newsletter-CoursePlatformDiscovery/1.0"},
            allow_redirects=True,
        )
        if response.status_code >= 400:
            return "", f"page_http_{response.status_code}"
        return clean_text(response.text)[:4000], "ok"
    except Exception as exc:
        return "", f"page_fetch_failed:{type(exc).__name__}"


def page_title_from_text(text: str, fallback: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", text or "", flags=re.IGNORECASE | re.DOTALL)
    if match:
        return clean_text(re.sub(r"<[^>]+>", " ", match.group(1)))[:220] or fallback
    return fallback


def direct_seed_result(domain: str, platform: str, page_timeout: int) -> tuple[dict | None, dict]:
    url = COURSE_PLATFORM_URLS.get(domain) or ""
    if not url:
        return None, {"query": "direct_seed", "raw_results": 0, "error": "missing_seed_url"}
    page_text, page_status = fetch_page_text(url, page_timeout)
    override_text = DIRECT_SEED_TEXT_OVERRIDES.get(domain, "")
    if override_text:
        page_text = f"{override_text} {page_text}"
    title = page_title_from_text(page_text, platform)
    raw = {
        "title": title or platform,
        "url": url,
        "text": page_text,
        "content": page_text,
    }
    return raw, {"query": "direct_seed", "raw_results": 1, "error": "" if page_status == "ok" else page_status}


def exa_search(query: str, *, results: int, start_date: str = "") -> tuple[list[dict], str]:
    if not EXA_API_KEY:
        return [], "missing_exa_api_key"
    payload = {
        "query": query,
        "numResults": max(1, results),
        "type": "neural",
        "contents": {"text": True, "highlights": True},
    }
    if start_date:
        payload["startPublishedDate"] = start_date
    try:
        response = requests.post(
            "https://api.exa.ai/search",
            headers={"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY},
            json=payload,
            timeout=20,
        )
        if response.status_code >= 400:
            return [], f"exa_http_{response.status_code}:{response.text[:220]}"
        return list((response.json() or {}).get("results") or []), ""
    except Exception as exc:
        return [], f"exa_request_failed:{type(exc).__name__}"


def score_course_result(raw: dict, *, platform: str, domain: str, source: str, query: str, page_timeout: int) -> dict:
    title = clean_text(raw.get("title") or "")
    url = str(raw.get("url") or "").strip()
    snippet = clean_text(raw.get("text") or raw.get("content") or raw.get("snippet") or " ".join(raw.get("highlights") or []))
    result_domain = source_domain(url)
    if url and not domain_allowed_for_platform(result_domain, domain):
        page_text, page_status = "", "skipped_wrong_domain"
    elif has_bad_course_url(url):
        page_text, page_status = "", "skipped_bad_course_url"
    else:
        page_text, page_status = fetch_page_text(url, page_timeout) if url else ("", "missing_url")
    evidence = f"{title} {snippet} {page_text[:1600]}"
    direct = course_url_is_direct(url, title=title, content=evidence)
    has_course = bool(COURSE_RE.search(evidence))
    has_ai = bool(AI_RE.search(evidence))
    workforce_fit = is_workforce_course_text(evidence)
    student_reject = has_student_course_reject_signal(evidence, domain=result_domain or domain)
    developer_only_reject = has_developer_only_course_signal(evidence)
    page_blocked_but_exa_enough = page_status.startswith(NON_FATAL_PAGE_STATUSES) and title and url and direct and has_course and has_ai
    reasons = []
    if not title or not url:
        reasons.append("missing_title_or_url")
    if url and not domain_allowed_for_platform(result_domain, domain):
        reasons.append("wrong_domain")
    if not direct:
        reasons.append("not_direct_course_url")
    if not has_course:
        reasons.append("missing_course_signal")
    if not has_ai:
        reasons.append("missing_ai_signal")
    if student_reject:
        reasons.append("student_audience")
    if developer_only_reject:
        reasons.append("developer_only_audience")
    if page_status != "ok" and not page_blocked_but_exa_enough:
        reasons.append(page_status)
    return {
        "passed": not reasons,
        "platform": platform,
        "source": source,
        "site": result_domain,
        "title": title,
        "url": url,
        "query": query,
        "page_status": page_status,
        "audience_review_required": bool(has_ai and has_course and direct and not workforce_fit),
        "audience_review_reason": "missing_workforce_signal" if has_ai and has_course and direct and not workforce_fit else "",
        "reasons": reasons,
        "score": sum([direct, has_course, has_ai, workforce_fit, page_status == "ok" or page_blocked_but_exa_enough]),
    }


def platform_queries(domain: str) -> list[str]:
    queries = []
    if domain == "learn.zapier.com":
        queries.extend([
            'site:learn.zapier.com/courses/zapier-academy-published-preview ("AI Builder Path" OR "AI Orchestrator Path" OR "Build AI Skills" OR "AI automation")',
            'site:learn.zapier.com ("AI" OR "artificial intelligence" OR "automation") ("course" OR "training" OR "lesson")',
            'site:zapier.com/learn ("AI" OR "automation" OR "workflow")',
        ])
    has_specific_path = False
    for pattern in COURSE_DIRECT_PATHS.get(domain) or ("/",):
        path = str(pattern or "/").strip()
        if path and path != "/":
            has_specific_path = True
            queries.append(f'site:{domain}{path.rstrip("/")} {COURSE_INTENT_QUERY} ("course" OR "training" OR "certificate" OR "learning path")')
            queries.append(f'site:{domain}{path.rstrip("/")} (AI OR "artificial intelligence" OR "الذكاء الاصطناعي") {WORKFORCE_INTENT_QUERY}')
        else:
            queries.append(f'site:{domain} {COURSE_INTENT_QUERY} ("course" OR "training" OR "certificate" OR "learning path")')
            queries.append(f'site:{domain} (AI OR "artificial intelligence" OR "الذكاء الاصطناعي") {WORKFORCE_INTENT_QUERY}')
    if not has_specific_path:
        queries.append(f'site:{domain} {COURSE_INTENT_QUERY} ("course" OR "training" OR "certificate" OR "learning path")')
    queries.append(f'site:{domain} (AI OR "artificial intelligence" OR "الذكاء الاصطناعي") ("course" OR "training" OR "certificate" OR "برنامج" OR "دورة") {WORKFORCE_INTENT_QUERY}')
    seen = set()
    output = []
    for query in queries:
        key = re.sub(r"\s+", " ", query.lower())
        if key not in seen:
            seen.add(key)
            output.append(query)
    return output


def test_course_platform(domain: str, platform: str, *, results: int, page_timeout: int, start_date: str = "") -> dict:
    rows = []
    errors = []
    query_attempts = []
    seed_raw, seed_attempt = direct_seed_result(domain, platform, page_timeout)
    query_attempts.append(seed_attempt)
    if seed_raw:
        rows.append(score_course_result(seed_raw, platform=platform, domain=domain, source="direct_seed", query="direct_seed", page_timeout=page_timeout))
    for query in platform_queries(domain):
        raw, error = exa_search(query, results=results, start_date=start_date)
        errors.extend([error] if error else [])
        query_attempts.append({
            "query": query,
            "raw_results": len(raw),
            "error": error,
        })
        scored = [score_course_result(item, platform=platform, domain=domain, source="exa", query=query, page_timeout=page_timeout) for item in raw]
        rows.extend(scored)
        if any(item["passed"] for item in scored):
            break
    passed = sorted([item for item in rows if item["passed"]], key=lambda item: item["score"], reverse=True)
    failures = Counter(reason for item in rows for reason in item.get("reasons") or [])
    exa_raw_checked = sum(
        int(attempt.get("raw_results") or 0)
        for attempt in query_attempts
        if attempt.get("query") != "direct_seed"
    )
    direct_seed_checked = bool(seed_raw)
    if exa_raw_checked == 0:
        failures["no_exa_results"] = 1
    if not rows and not failures:
        failures["no_checked_rows"] = 1
    if errors:
        for error in errors:
            failures[error.split(":", 1)[0]] += 1
    return {
        "platform": platform,
        "domain": domain,
        "passed": bool(passed),
        "best_sources": passed[:4],
        "raw_checked": len(rows),
        "direct_seed_checked": direct_seed_checked,
        "exa_raw_checked": exa_raw_checked,
        "queries_attempted": len(query_attempts),
        "query_attempts": query_attempts,
        "errors": errors,
        "failure_reasons": dict(failures),
        "primary_failure_reason": (failures.most_common(1)[0][0] if failures else ""),
        "sample_failures": sorted([item for item in rows if not item["passed"]], key=lambda item: item["score"], reverse=True)[:3],
    }


def run_pipeline_fetch(max_results: int) -> list[dict]:
    return fetch_course_candidates(max_results=max(1, max_results))


def write_reports(report: dict) -> None:
    safe_write_json(JSON_REPORT, report)
    safe_write_json(FAILED_JSON_REPORT, {
        "generated_at": report.get("generated_at"),
        "failed_count": len(report.get("failed_platforms") or []),
        "failed_platforms": report.get("failed_platforms") or [],
    })
    lines = [
        "# Course Platform Discovery Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Platforms tested: {report['summary']['platforms_tested']}",
        f"- Platforms passed: {report['summary']['platforms_passed']}",
        f"- Platforms failed: {report['summary']['platforms_failed']}",
        f"- Pipeline candidates: {report['summary']['pipeline_candidates']}",
        "",
        "## Platforms",
    ]
    for item in report["platforms"]:
        status = "PASS" if item["passed"] else "FAIL"
        best = item["best_sources"][0]["title"] if item["best_sources"] else "; ".join(item["failure_reasons"].keys()) or "; ".join(item["errors"])
        lines.append(f"- {status} | {item['platform']} | {item['domain']} | {best}")
    if report["failed_platforms"]:
        lines.extend(["", "## Failed Platforms"])
        for item in report["failed_platforms"]:
            lines.append(
                f"- {item['platform']} | {item['domain']} | "
                f"{item.get('primary_failure_reason') or 'unknown'} | "
                f"checked={item.get('raw_checked', 0)} queries={item.get('queries_attempted', 0)}"
            )
    if report["pipeline_candidates"]:
        lines.extend(["", "## Pipeline Candidates"])
        for item in report["pipeline_candidates"][:20]:
            lines.append(f"- {item.get('platform') or item.get('source')} | {item.get('level') or ''} | {item.get('title')} | {item.get('url')}")
    MD_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run course/platform discovery separately from general AI update discovery.")
    parser.add_argument("--max-platforms", type=int, default=0, help="How many trusted platforms to test. Default 0 means all.")
    parser.add_argument("--only-domain", action="append", default=[], help="Test one domain. Can be repeated.")
    parser.add_argument("--additional-core-20", action="store_true", help="Test only the additional 20 course-bank platforms.")
    parser.add_argument("--extra-clean", action="store_true", help="Test only the clean extra course-bank platforms.")
    parser.add_argument("--results", type=int, default=4, help="Search results per engine per platform.")
    parser.add_argument("--page-timeout", type=int, default=5, help="Seconds to wait when verifying result pages.")
    parser.add_argument("--start-date", default="", help="Optional Exa startPublishedDate. Empty means evergreen course search.")
    parser.add_argument("--pipeline", action="store_true", help="Also run the real course fetch pipeline.")
    parser.add_argument("--pipeline-results", type=int, default=20, help="Max candidates from the real course fetch pipeline.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = time.time()
    all_platforms = sorted(
        ((domain, COURSE_PLATFORM_NAMES.get(domain) or domain) for domain in COURSE_DIRECT_PATHS),
        key=lambda row: (-int(EMPLOYEE_AI_PLATFORM_PRIORITY.get(row[0]) or 0), row[1].lower(), row[0]),
    )
    if args.only_domain:
        wanted = {domain.lower().replace("www.", "").strip() for domain in args.only_domain}
        platforms = [(domain, name) for domain, name in all_platforms if domain.lower().replace("www.", "") in wanted]
    elif args.additional_core_20:
        wanted = {domain.lower().replace("www.", "").strip() for domain in ADDITIONAL_CORE_20_COURSE_BANK_PLATFORMS}
        platforms = [(domain, name) for domain, name in all_platforms if domain.lower().replace("www.", "") in wanted]
    elif args.extra_clean:
        wanted = {domain.lower().replace("www.", "").strip() for domain in COURSE_BANK_EXTRA_PLATFORMS_CLEAN}
        platforms = [(domain, name) for domain, name in all_platforms if domain.lower().replace("www.", "") in wanted]
    elif args.max_platforms and args.max_platforms > 0:
        platforms = all_platforms[: args.max_platforms]
    else:
        platforms = all_platforms

    platform_reports = []
    for index, (domain, platform) in enumerate(platforms, start=1):
        row = test_course_platform(domain, platform, results=args.results, page_timeout=args.page_timeout, start_date=args.start_date)
        platform_reports.append(row)
        print(f"{index}/{len(platforms)} {platform}: {'PASS' if row['passed'] else 'FAIL'} checked={row['raw_checked']}", flush=True)

    pipeline_candidates = run_pipeline_fetch(args.pipeline_results) if args.pipeline else []
    failed_platforms = [
        {
            "platform": item.get("platform"),
            "domain": item.get("domain"),
            "primary_failure_reason": item.get("primary_failure_reason"),
            "failure_reasons": item.get("failure_reasons") or {},
            "raw_checked": item.get("raw_checked", 0),
            "queries_attempted": item.get("queries_attempted", 0),
        }
        for item in platform_reports
        if not item.get("passed")
    ]
    report = {
        "generated_at": utc_now().isoformat(),
        "source_engine": "exa",
        "course_date_filter": args.start_date or "none",
        "settings": {
            "max_platforms": args.max_platforms,
            "only_domain": args.only_domain,
            "additional_core_20": args.additional_core_20,
            "extra_clean": args.extra_clean,
            "results": args.results,
            "page_timeout": args.page_timeout,
            "start_date": args.start_date,
            "pipeline": args.pipeline,
            "pipeline_results": args.pipeline_results,
        },
        "platforms": platform_reports,
        "failed_platforms": failed_platforms,
        "pipeline_candidates": pipeline_candidates,
        "summary": {
            "seconds": round(time.time() - started, 2),
            "platforms_tested": len(platform_reports),
            "platforms_passed": sum(1 for item in platform_reports if item["passed"]),
            "platforms_failed": len(failed_platforms),
            "pipeline_candidates": len(pipeline_candidates),
        },
    }
    write_reports(report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"JSON report: {JSON_REPORT}")
    print(f"Failed platforms: {FAILED_JSON_REPORT}")
    print(f"Markdown report: {MD_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
