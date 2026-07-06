# Tracks official Saudi AI news with strict editorial filtering.
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from backend.config.settings import SEARXNG_URL, clean_text, safe_write_json, utc_now  # noqa: E402

OUTPUT_PATH = PROJECT_DIR / "data" / "news" / "saudi_ai_updates.json"
EXA_SEARCH_URL = "https://api.exa.ai/search"
HEADERS = {"User-Agent": "AINewsletterBot/1.0 (+https://localhost)"}

ACCEPTED_EDITORIAL_TYPES = {
    "official_ai_policy",
    "official_ai_platform",
    "official_ai_government_service",
    "official_ai_sector_adoption",
}

QUERIES = [
    "سدايا الذكاء الاصطناعي سياسة",
    "سدايا تطرح سياسة الذكاء الاصطناعي",
    "الذكاء الاصطناعي أولًا السعودية",
    "استطلاع مرئيات الذكاء الاصطناعي",
    "سياسة الذكاء الاصطناعي السعودية",
    "إطلاق منصة ذكاء اصطناعي السعودية",
    "رؤية الذكاء الاصطناعي السياحي",
    "وزارة السياحة تطلق الذكاء الاصطناعي السياحي",
    "منصة ذكاء اصطناعي حكومية السعودية",
    "الخدمات البلدية الذكاء الاصطناعي السعودية",
    "التعليم الذكاء الاصطناعي السعودية",
    "الصحة الذكاء الاصطناعي السعودية",
    "الثقافة الذكاء الاصطناعي السعودية",
    "المياه الذكاء الاصطناعي السعودية",
    "الطاقة الذكاء الاصطناعي السعودية",
    "HUMAIN Saudi Arabia AI launch",
    "SDAIA artificial intelligence policy Saudi Arabia",
    "Saudi Arabia AI policy public consultation",
    "Saudi AI platform launched",
    "Saudi government artificial intelligence initiative",
    "Saudi AI regulation governance framework",
    "Saudi ministry artificial intelligence service launched",
    "Saudi tourism AI platform TourismX",
]

OFFICIAL_DOMAINS = {
    "spa.gov.sa",
    "sdaia.gov.sa",
    "ndmo.gov.sa",
    "mcit.gov.sa",
    "humain.ai",
    "my.gov.sa",
    "ai.gov.sa",
    "gov.sa",
    "mofa.gov.sa",
    "moh.gov.sa",
    "moe.gov.sa",
    "mt.gov.sa",
    "moc.gov.sa",
    "momrah.gov.sa",
    "mewa.gov.sa",
    "moenergy.gov.sa",
    "tourism.gov.sa",
}

TRUSTED_MEDIA_DOMAINS = {
    "arabnews.com",
    "saudigazette.com.sa",
    "argaam.com",
    "reuters.com",
    "bloomberg.com",
}

SAUDI_TERMS = [
    "saudi",
    "saudi arabia",
    "riyadh",
    "kingdom",
    "vision 2030",
    "sdaia",
    "humain",
    "ndmo",
    "mcit",
    "kaust",
    "neom",
    "kacst",
    "سعود",
    "السعودية",
    "المملكة",
    "الرياض",
    "رؤية 2030",
    "سدايا",
    "هيومين",
    "نيوم",
    "كاوست",
    "وزارة",
    "هيئة",
]

AI_TERMS = [
    "ai",
    "artificial intelligence",
    "generative ai",
    "machine learning",
    "llm",
    "model",
    "الذكاء الاصطناعي",
    "ذكاء اصطناعي",
    "نموذج",
]

POLICY_TERMS = [
    "policy",
    "regulation",
    "governance",
    "framework",
    "public consultation",
    "consultation",
    "سياسة",
    "سياسات",
    "تنظيم",
    "لوائح",
    "لائحة",
    "حوكمة",
    "إطار تنظيمي",
    "أطر تنظيمية",
    "استطلاع مرئيات",
    "مرئيات",
    "الذكاء الاصطناعي أولًا",
]

PLATFORM_TERMS = [
    "platform",
    "service",
    "engine",
    "launch",
    "launched",
    "unveils",
    "introduces",
    "منصة",
    "خدمة",
    "محرك",
    "أطلقت",
    "يطلق",
    "تطلق",
    "إطلاق",
]

GOVERNMENT_SERVICE_TERMS = [
    "government service",
    "public service",
    "municipal",
    "ministry",
    "authority",
    "خدمة حكومية",
    "الخدمات الحكومية",
    "الخدمات البلدية",
    "وزارة",
    "هيئة",
]

SECTOR_TERMS = [
    "tourism",
    "education",
    "health",
    "culture",
    "municipal",
    "water",
    "energy",
    "السياحة",
    "التعليم",
    "الصحة",
    "الثقافة",
    "البلدية",
    "البلديات",
    "المياه",
    "الطاقة",
]

PARTNERSHIP_TERMS = [
    "partnership",
    "agreement",
    "signs",
    "cooperation",
    "collaboration",
    "شراكة",
    "اتفاقية",
    "تعاون",
    "وقعت",
    "يوقع",
]

TRAINING_TERMS = [
    "bootcamp",
    "course",
    "training",
    "academy",
    "workshop",
    "program",
    "معسكر",
    "دورة",
    "كورسات",
    "تدريب",
    "أكاديمية",
    "ورشة",
    "برنامج تدريبي",
]

MARKET_REPORT_TERMS = [
    "market size",
    "market growth",
    "forecast",
    "cagr",
    "market report",
    "حجم السوق",
    "نمو السوق",
    "توقعات السوق",
    "تقرير سوق",
]

LOW_VALUE_TERMS = [
    "opinion",
    "analysis",
    "explained",
    "how to",
    "tutorial",
    "review",
    "award",
    "conference",
    "رأي",
    "تحليل",
    "شرح",
    "دليل",
    "مراجعة",
    "جائزة",
    "مؤتمر",
]


# Loads the Exa API key from backend/.env or the current environment.
def load_exa_api_key() -> str:
    load_dotenv(PROJECT_DIR / "backend" / ".env")
    return os.getenv("EXA_API_KEY", "").strip()


# Normalizes a URL by removing query parameters and fragments for dedupe.
def canonical_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    return urlunparse((parsed.scheme.lower() or "https", parsed.netloc.lower().replace("www.", ""), parsed.path.rstrip("/"), "", "", ""))


# Returns the lowercase source domain.
def source_domain(url: str) -> str:
    return urlparse(str(url or "")).netloc.lower().replace("www.", "")


# Checks whether the source is official Saudi or semi-official.
def is_official_source(url: str) -> bool:
    domain = source_domain(url)
    return any(domain == item or domain.endswith(f".{item}") for item in OFFICIAL_DOMAINS)


# Parses a date string into a timezone-aware UTC datetime.
def parse_date(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = date_parser.parse(str(value), fuzzy=True)
    except Exception:
        return None
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# Builds searchable text from title and preview.
def item_text(item: dict) -> str:
    return f"{item.get('title', '')} {item.get('text_preview', '')}".lower()


# Checks whether any term exists in a text.
def has_any(text: str, terms: list[str]) -> bool:
    return any(term.lower() in text for term in terms)


# Searches Exa for one Saudi AI query.
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
                "text_preview": clean_text(item.get("text") or "")[:700],
                "source_engine": "exa",
                "query_used": query,
            }
            for item in (response.json() or {}).get("results") or []
            if item.get("url")
        ]
    except Exception:
        return []


# Searches SearXNG for one Saudi AI query.
def search_searxng(query: str, results: int) -> list[dict]:
    try:
        response = httpx.get(
            f"{SEARXNG_URL.rstrip('/')}/search",
            params={"q": query, "format": "json", "language": "all", "categories": "general,news", "time_range": "week", "pageno": 1},
            timeout=30,
        )
        if response.status_code >= 400:
            return []
        return [
            {
                "title": clean_text(item.get("title") or ""),
                "url": str(item.get("url") or "").strip(),
                "text_preview": clean_text(item.get("content") or "")[:700],
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


# Classifies the result into the requested editorial category.
def classify_editorial_type(item: dict) -> str:
    text = item_text(item)
    official = is_official_source(item.get("url", ""))
    if has_any(text, TRAINING_TERMS):
        return "training_or_bootcamp"
    if has_any(text, MARKET_REPORT_TERMS):
        return "market_report"
    if not has_any(text, SAUDI_TERMS) or not has_any(text, AI_TERMS):
        return "reject"
    if has_any(text, POLICY_TERMS):
        return "official_ai_policy" if official or has_any(text, ["sdaia", "سدايا", "ndmo", "mcit"]) else "reject"
    if has_any(text, PLATFORM_TERMS) and (official or has_any(text, ["humain", "sdaia", "هيومين", "سدايا"])):
        return "official_ai_platform"
    if has_any(text, GOVERNMENT_SERVICE_TERMS) and official:
        return "official_ai_government_service"
    if has_any(text, SECTOR_TERMS) and (official or has_any(text, ["ministry", "وزارة", "authority", "هيئة"])):
        return "official_ai_sector_adoption"
    if has_any(text, PARTNERSHIP_TERMS):
        return "private_ai_partnership" if not official else "official_ai_sector_adoption"
    return "reject"


# Scores editorial fit after date verification.
def editorial_fit_score(item: dict, editorial_type: str) -> int:
    text = item_text(item)
    score = 0
    official = is_official_source(item.get("url", ""))
    if official:
        score += 5
    if has_any(text, POLICY_TERMS):
        score += 4
    if has_any(text, PLATFORM_TERMS):
        score += 4
    if has_any(text, SECTOR_TERMS):
        score += 3
    if has_any(text, ["استطلاع مرئيات", "سياسة", "إطار تنظيمي", "حوكمة", "public consultation", "policy", "governance"]):
        score += 2
    if has_any(text, TRAINING_TERMS):
        score -= 5
    if has_any(text, MARKET_REPORT_TERMS):
        score -= 4
    if editorial_type == "private_ai_partnership":
        score -= 3
    if editorial_type == "reject":
        score -= 3
    if editorial_type not in ACCEPTED_EDITORIAL_TYPES:
        score -= 3
    return score


# Gives official and high-trust Saudi sources a better rank.
def priority(item: dict) -> int:
    domain = source_domain(item["url"])
    if is_official_source(item["url"]):
        return 1
    if any(domain == item or domain.endswith(f".{item}") for item in TRUSTED_MEDIA_DOMAINS):
        return 2
    return 4


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


# Runs the Saudi AI tracker and writes the JSON report.
def main() -> int:
    api_key = load_exa_api_key()
    raw = []
    for query in QUERIES:
        if api_key:
            raw.extend(search_exa(query, api_key, days=7, results=8))
        raw.extend(search_searxng(query, results=8))
    unique = dedupe(raw)
    prelim = [item for item in unique if has_any(item_text(item), SAUDI_TERMS) and has_any(item_text(item), AI_TERMS)]
    cutoff = utc_now() - timedelta(days=7)
    verified = []
    rejected = []
    accepted = []
    for item in prelim:
        verified_date = verify_page_date(item["url"])
        if not verified_date or verified_date["date"] < cutoff:
            rejected.append({**item, "editorial_type": "reject", "reject_reason": "date_not_verified_or_old"})
            continue
        item["verified_date"] = verified_date["date"].isoformat()
        item["date_source"] = verified_date["source"]
        item["confidence"] = verified_date["confidence"]
        item["priority"] = priority(item)
        item["official_source"] = is_official_source(item["url"])
        item["editorial_type"] = classify_editorial_type(item)
        item["editorial_fit_score"] = editorial_fit_score(item, item["editorial_type"])
        verified.append(item)
        if item["editorial_type"] in ACCEPTED_EDITORIAL_TYPES and item["editorial_fit_score"] > 0:
            accepted.append(item)
        else:
            rejected.append({**item, "reject_reason": "editorial_fit_failed"})
    accepted.sort(key=lambda item: (item["priority"], -item["editorial_fit_score"], item["verified_date"]))
    report = {
        "generated_at": utc_now().isoformat(),
        "window": {"days": 7, "start": cutoff.isoformat(), "end": utc_now().isoformat()},
        "accepted_editorial_types": sorted(ACCEPTED_EDITORIAL_TYPES),
        "summary": {
            "raw_results": len(raw),
            "after_dedupe": len(unique),
            "saudi_ai_candidates": len(prelim),
            "verified": len(verified),
            "accepted": len(accepted),
            "rejected": len(rejected),
        },
        "accepted_items": accepted[:20],
        "rejected_items": rejected[:50],
    }
    safe_write_json(OUTPUT_PATH, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"JSON report: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
