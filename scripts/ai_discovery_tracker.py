# Discovers new AI launches with Exa and SearXNG without touching the main system.
from __future__ import annotations

import json
import os
import re
import sys
from datetime import timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config.settings import MONTHLY_TOOLS_FILE, SEARXNG_URL, clean_text, load_json, safe_write_json, utc_now  # noqa: E402

OUTPUT_PATH = PROJECT_DIR / "data" / "news" / "ai_discovery.json"
EXA_SEARCH_URL = "https://api.exa.ai/search"
HEADERS = {"User-Agent": "AINewsletterBot/1.0 (+https://localhost)"}

DISCOVERY_QUERIES = [
    '"introducing" AI assistant',
    '"announcing" new AI app',
    '"launches" AI productivity tool',
    '"launches" AI design tool',
    '"launches" AI video tool',
    '"launches" AI education tool',
    '"launches" AI meeting assistant',
    '"AI company" launches productivity',
    '"generally available" AI feature',
    '"early access" AI product',
    '"AI service" launch',
]

LAUNCH_SIGNALS = [
    "introducing",
    "announcing",
    "launches",
    "unveils",
    "releases",
    "debuts",
    "open sources",
    "generally available",
    "now available",
    "public beta",
]

NOISE_INDICATORS = [
    "medium.com/@",
    "substack.com/p/",
    "reddit.com/r/",
    "linkedin.com/pulse",
    "opinion",
    "analysis",
    "explained",
    "how to",
    "tutorial",
    "guide",
    "review",
]

DEVELOPER_TOOL_TERMS = [
    "github copilot",
    "vs code",
    "visual studio code",
    "api",
    "sdk",
    "coding agent",
    "coding agents",
    "developer tool",
    "developers",
    "framework",
    "library",
    "repository",
    "repo",
    "github",
    "cli",
    "ide",
    "code editor",
    "programming",
    "software development",
    "devtools",
    "open source model",
    "open-source model",
    "benchmark",
    "inference",
    "fine-tuning",
    "deployment",
    "kubernetes",
    "python package",
    "npm",
    "برمجة",
    "مطورين",
    "واجهة برمجة",
    "إطار عمل",
    "مكتبة",
]

GENERAL_USER_DOMAINS = [
    "writing",
    "writer",
    "search",
    "meeting",
    "meetings",
    "notes",
    "presentation",
    "design",
    "image",
    "video",
    "audio",
    "music",
    "productivity",
    "education",
    "learning",
    "teacher",
    "student",
    "tourism",
    "culture",
    "government service",
    "public service",
    "customer service",
    "workflow",
    "workspace",
    "document",
    "spreadsheet",
    "email",
    "browser",
]

USER_VALUE_TERMS = [
    "users can",
    "lets users",
    "helps users",
    "teams can",
    "customers can",
    "creators can",
    "teachers can",
    "students can",
    "now you can",
    "available to users",
    "for teams",
    "for creators",
    "for students",
    "for businesses",
    "for employees",
    "no-code",
    "without coding",
]


# Loads the Exa API key from backend/.env or the current environment.
def load_exa_api_key() -> str:
    load_dotenv(PROJECT_DIR / "backend" / ".env")
    return os.getenv("EXA_API_KEY", "").strip()


# Loads known tool and company names from the existing registry.
def load_known_terms() -> list[str]:
    data = load_json(MONTHLY_TOOLS_FILE, {"tool_records": [], "tools": []})
    terms = []
    for item in data.get("tools") or []:
        if isinstance(item, str):
            terms.append(item.lower())
    for item in data.get("tool_records") or []:
        if isinstance(item, dict):
            for key in ("tool", "company"):
                value = clean_text(item.get(key) or "")
                if value:
                    terms.append(value.lower())
    extras = ["openai", "anthropic", "google ai", "xai", "llama", "dall-e", "microsoft copilot"]
    return list(dict.fromkeys(terms + extras))


# Normalizes a URL by removing query parameters and fragments for dedupe.
def canonical_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    return urlunparse((parsed.scheme.lower() or "https", parsed.netloc.lower().replace("www.", ""), parsed.path.rstrip("/"), "", "", ""))


# Returns the lowercase source domain.
def source_domain(url: str) -> str:
    return urlparse(str(url or "")).netloc.lower().replace("www.", "")


# Parses a date string into a timezone-aware UTC datetime.
def parse_date(value: object):
    if not value:
        return None
    try:
        parsed = date_parser.parse(str(value), fuzzy=True)
    except Exception:
        return None
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# Searches Exa for one discovery query.
def search_exa(query: str, api_key: str, days: int, results: int) -> list[dict]:
    start_date = (utc_now() - timedelta(days=days)).date().isoformat()
    try:
        response = httpx.post(
            EXA_SEARCH_URL,
            headers={"Accept": "application/json", "Content-Type": "application/json", "x-api-key": api_key},
            json={
                "query": query,
                "numResults": results,
                "type": "auto",
                "startPublishedDate": start_date,
                "contents": {"text": True},
            },
            timeout=30,
        )
        if response.status_code >= 400:
            return []
        return [
            {
                "title": clean_text(item.get("title") or ""),
                "url": str(item.get("url") or "").strip(),
                "text_preview": clean_text(item.get("text") or "")[:500],
                "source_engine": "exa",
                "query_used": query,
            }
            for item in (response.json() or {}).get("results") or []
            if item.get("url")
        ]
    except Exception:
        return []


# Searches SearXNG for one discovery query.
def search_searxng(query: str, results: int) -> list[dict]:
    try:
        response = httpx.get(
            f"{SEARXNG_URL.rstrip('/')}/search",
            params={"q": query, "format": "json", "language": "en", "categories": "general,news", "time_range": "week", "pageno": 1},
            timeout=30,
        )
        if response.status_code >= 400:
            return []
        return [
            {
                "title": clean_text(item.get("title") or ""),
                "url": str(item.get("url") or "").strip(),
                "text_preview": clean_text(item.get("content") or "")[:500],
                "source_engine": "searxng",
                "query_used": query,
            }
            for item in ((response.json() or {}).get("results") or [])[:results]
            if item.get("url")
        ]
    except Exception:
        return []


# Opens a page and extracts a publication date without accepting modified dates.
def verify_page_date(url: str, timeout: int = 12) -> dict | None:
    try:
        response = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
    except Exception:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
        except Exception:
            continue
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            if isinstance(row, dict) and row.get("datePublished"):
                parsed = parse_date(row["datePublished"])
                if parsed:
                    return {"date": parsed, "source": "json_ld_datePublished", "confidence": 10}
    for attrs in ({"property": "article:published_time"}, {"name": "article:published_time"}):
        tag = soup.find("meta", attrs=attrs)
        parsed = parse_date(tag.get("content") if tag else "")
        if parsed:
            return {"date": parsed, "source": "meta_article_published_time", "confidence": 9}
    for tag in soup.find_all("time"):
        context = f"{tag.attrs} {tag.parent.get_text(' ', strip=True)[:120] if tag.parent else ''}".lower()
        if "modified" in context or "updated" in context:
            continue
        parsed = parse_date(tag.get("datetime") or tag.get_text(" ", strip=True))
        if parsed:
            return {"date": parsed, "source": "time_tag", "confidence": 7}
    return None


# Checks whether a result is about a known tool and should be separated.
def is_known_tool(item: dict, known_terms: list[str]) -> bool:
    text = f"{item.get('title', '')} {item.get('text_preview', '')}".lower()
    return any(term and term in text for term in known_terms)


# Checks whether the item has a launch-style signal.
def has_launch_signal(item: dict) -> bool:
    text = f"{item.get('title', '')} {item.get('text_preview', '')}".lower()
    return any(signal in text for signal in LAUNCH_SIGNALS)


# Checks whether a result is likely low-value noise.
def is_noise(item: dict) -> bool:
    evidence = f"{item.get('title', '')} {item.get('url', '')}".lower()
    return any(noise in evidence for noise in NOISE_INDICATORS)


# Extracts a possible tool or company name from a launch title.
def general_user_fit_score(item: dict) -> tuple[int, list[str]]:
    text = f"{item.get('title', '')} {item.get('text_preview', '')} {item.get('url', '')}".lower()
    reasons = []
    score = 0
    developer_hits = [term for term in DEVELOPER_TOOL_TERMS if term in text]
    if developer_hits:
        score -= 8
        reasons.append(f"developer_tool:{','.join(developer_hits[:3])}")
    domain_hits = [term for term in GENERAL_USER_DOMAINS if term in text]
    if domain_hits:
        score += min(6, len(domain_hits) * 2)
        reasons.append(f"general_user_domain:{','.join(domain_hits[:4])}")
    value_hits = [term for term in USER_VALUE_TERMS if term in text]
    if value_hits:
        score += min(6, len(value_hits) * 3)
        reasons.append(f"user_value:{','.join(value_hits[:3])}")
    if "launch" in text or "now available" in text or "generally available" in text:
        score += 2
        reasons.append("available_now_signal")
    if not domain_hits and not value_hits:
        score -= 4
        reasons.append("no_clear_nontechnical_user_value")
    return score, reasons


# Extracts a possible tool or company name from a launch title.
def extract_potential_tool_name(title: str) -> str:
    patterns = [
        r"Introducing\s+([A-Z][a-zA-Z0-9\-]+)",
        r"Announcing\s+([A-Z][a-zA-Z0-9\-]+)",
        r"([A-Z][a-zA-Z0-9\-]+)\s+(?:launches|announces|unveils|releases)",
        r"Meet\s+([A-Z][a-zA-Z0-9\-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, title or "", re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if len(value) >= 3 and value.lower() not in {"the", "new", "our", "this"}:
                return value
    return ""


# Removes duplicate URLs after normalizing them.
def dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for item in items:
        key = canonical_url(item.get("url", ""))
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


# Runs the discovery tracker and writes the JSON report.
def main() -> int:
    api_key = load_exa_api_key()
    known_terms = load_known_terms()
    raw = []
    for query in DISCOVERY_QUERIES:
        if api_key:
            raw.extend(search_exa(query, api_key, days=7, results=8))
        raw.extend(search_searxng(query, results=8))
    unique = dedupe(raw)
    clean = [item for item in unique if not is_noise(item) and has_launch_signal(item)]
    new_discoveries = []
    known_updates = []
    rejected_for_audience = []
    cutoff = utc_now() - timedelta(days=7)
    for item in clean:
        item["potential_tool"] = extract_potential_tool_name(item["title"])
        verification = verify_page_date(item["url"])
        if not verification or verification["date"] < cutoff:
            continue
        item["verified_date"] = verification["date"].isoformat()
        item["date_source"] = verification["source"]
        item["confidence"] = verification["confidence"]
        item["domain"] = source_domain(item["url"])
        audience_score, audience_reasons = general_user_fit_score(item)
        item["general_user_fit_score"] = audience_score
        item["audience_fit_reasons"] = audience_reasons
        if audience_score < 1:
            item["reject_reason"] = "developer_or_unclear_general_user_value"
            rejected_for_audience.append(item)
            continue
        if is_known_tool(item, known_terms):
            known_updates.append(item)
        else:
            new_discoveries.append(item)
    report = {
        "generated_at": utc_now().isoformat(),
        "window": {"days": 7, "start": cutoff.isoformat(), "end": utc_now().isoformat()},
        "summary": {
            "raw_results": len(raw),
            "after_dedupe": len(unique),
            "clean_launch_candidates": len(clean),
            "rejected_for_audience": len(rejected_for_audience),
            "new_discoveries": len(new_discoveries),
            "known_tools_updates": len(known_updates),
        },
        "new_discoveries": new_discoveries[:15],
        "known_tools_updates_hint": known_updates[:10],
        "rejected_for_audience": rejected_for_audience[:30],
    }
    safe_write_json(OUTPUT_PATH, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"JSON report: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
