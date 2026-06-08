"""Live fetchers for news, courses, and AI-themed movies.

This file owns discovery only. It builds Exa/SearXNG queries, normalizes raw
results into one candidate shape, and leaves final editorial judgment to
`model.py`.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, urlparse

import requests

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

from .config import (
    AI_UPDATES_EXA_QUERY_LIMIT,
    AI_UPDATES_EXA_RESULTS_PER_QUERY,
    AI_UPDATES_EXA_TIMEOUT,
    AI_UPDATES_COURSE_EXA_QUERY_LIMIT,
    AI_UPDATES_COURSE_EXA_RESULTS_PER_QUERY,
    AI_UPDATES_LOOKBACK_DAYS,
    AI_UPDATES_SEARXNG_CATEGORIES,
    AI_UPDATES_SEARXNG_QUERY_LIMIT,
    AI_UPDATES_SEARXNG_RESULTS_PER_QUERY,
    AI_UPDATES_SEARXNG_TIME_RANGE,
    AI_UPDATES_SEARXNG_TIMEOUT,
    AI_UPDATES_SINGLE_EXA_QUERY_LIMIT,
    AI_UPDATES_SINGLE_EXA_RESULTS_PER_QUERY,
    AI_UPDATES_SINGLE_RESULTS_PER_QUERY,
    AI_UPDATES_SINGLE_SEARXNG_QUERY_LIMIT,
    AI_UPDATES_SINGLE_TIMEOUT,
    AI_UPDATES_TOOL_CACHE_MAX_RECORDS,
    AI_UPDATES_TOOL_CACHE_REFRESH_DAYS,
    AI_UPDATES_TOOL_DISCOVERY_ENABLED,
    AI_UPDATES_TOOL_DISCOVERY_MODEL,
    AI_UPDATES_TOOL_DISCOVERY_RESULTS,
    COURSE_INCLUDE_DOMAINS,
    COURSE_QUERY,
    COURSE_QUERY_VARIANTS,
    EXA_API_KEY,
    MONTHLY_TOOLS_FILE,
    NEWS_SECTORS,
    OPENAI_API_KEY,
    SECTOR_TERMS_HISTORY_FILE,
    SEARXNG_URL,
    TOOL_SECTOR_MAP_FILE,
    TMDB_API_KEY,
    TOOLS_SCORED_FILE,
    clean_text,
    load_json,
    memory_url_key,
    normalized_text,
    parse_result_datetime,
    recency_cutoff_query_token,
    result_is_recent_enough,
    safe_write_json,
    source_domain,
    utc_now,
)

_tool_discovery_client = OpenAI(api_key=OPENAI_API_KEY) if OpenAI and OPENAI_API_KEY else None

# A small always-on query bank keeps broad AI update coverage alive even when
# the tool cache is weak or stale.
MOTHER_QUERY_ROW = {"bucket": "impact", "query": "most impactful AI release this week"}

GENERAL_AI_UPDATE_ROWS = [
    {"bucket": "general_update", "query": "AI tools product updates"},
    {"bucket": "general_update", "query": "latest AI tool updates"},
    {"bucket": "general_update", "query": "new AI tools and features"},
    {"bucket": "general_update", "query": "AI product releases and updates"},
    {"bucket": "general_update", "query": "artificial intelligence tools new updates"},
    {"bucket": "general_update", "query": "AI apps new features now available"},
    {"bucket": "impact", "query": "important AI product updates this week"},
    {"bucket": "official_update", "query": "official AI feature rollout now available"},
]

# Specialized direct queries keep the newsletter close to culture, creative
# work, productivity, learning, and daily-life use cases.
DEFAULT_QUERY_ROWS = [
    {"bucket": "museums", "query": '"AI museum guide" "new feature" OR "product update"'},
    {"bucket": "heritage", "query": '"AI heritage archive" "release" OR "new feature"'},
    {"bucket": "libraries", "query": '"AI library research" "product update" OR "release notes"'},
    {"bucket": "music", "query": '"AI music tool" "new feature" OR "release notes"'},
    {"bucket": "films", "query": '"AI film video tool" "product update" OR "release notes"'},
    {"bucket": "literature", "query": '"AI writing storytelling tool" "new feature" OR "product update"'},
    {"bucket": "fashion", "query": '"AI fashion try-on" "new feature" OR "rollout"'},
    {"bucket": "architecture", "query": '"AI architecture design tool" "new feature" OR "release notes"'},
    {"bucket": "cooking", "query": '"AI cooking meal planning" "new feature" OR "product update"'},
    {"bucket": "work_productivity", "query": '"AI workflow" "release notes" "changelog"'},
    {"bucket": "daily_life", "query": '"AI mobile assistant" "feature rollout"'},
    {"bucket": "culture_knowledge", "query": '"AI knowledge assistant" "new feature" "now available"'},
    {"bucket": "learning", "query": '"AI learning assistant" "product update"'},
    {"bucket": "general_assistant", "query": '"AI assistant" "users can now" "rolling out"'},
    {"bucket": "work_productivity", "query": '"AI productivity platform" "new capability"'},
    {"bucket": "daily_life", "query": '"AI shopping assistant" "product update"'},
    {"bucket": "culture_knowledge", "query": '"AI archive tool" "product update" OR "release notes"'},
    {"bucket": "audio_voice", "query": '"AI voice" OR "AI narration" "product update"'},
    {"bucket": "video_motion", "query": '"AI video tool" "new feature" "now available"'},
    {"bucket": "content_creation", "query": '"AI content creation" "workflow" "new capability"'},
    {"bucket": "daily_life", "query": '"AI travel assistant" "now available" OR "new feature"'},
    {"bucket": "work_visual", "query": '"AI presentation tool" "new feature" OR "release notes"'},
    {"bucket": "health_wellness", "query": '"AI wellness assistant" "new feature" "available"'},
    {"bucket": "literature_writing", "query": '"AI writing tool" "new feature" "now available"'},
    {"bucket": "food_cooking", "query": '"AI meal planner" "new feature" OR "product update"'},
    {"bucket": "agent_updates", "query": '"AI agent" "launch" "now available"'},
    {"bucket": "design_visual", "query": '"AI design tool" "product update" "new feature"'},
    {"bucket": "fashion_style", "query": '"virtual try-on" "AI" "new feature" OR "rollout"'},
]

BROAD_EXA_ROWS = [
    {"bucket": "impact", "query": "most impactful AI product releases this week"},
    {"bucket": "general_update", "query": "new AI feature release available to users"},
    {"bucket": "official_update", "query": "official AI product update new capability"},
    {"bucket": "daily_life", "query": "AI app rollout new feature for users"},
    {"bucket": "general_assistant", "query": "AI assistant product launch now available"},
    {"bucket": "work_productivity", "query": "AI productivity workflow update release"},
    {"bucket": "daily_life", "query": "AI daily life assistant shopping travel update"},
    {"bucket": "learning", "query": "AI education learning tool release"},
    {"bucket": "audio_voice", "query": "AI voice music narration tool release"},
    {"bucket": "culture_knowledge", "query": "AI archive museum translation tool release"},
    {"bucket": "health_wellness", "query": "AI health wellness assistant app update"},
    {"bucket": "design_visual", "query": "AI creative tool release image video design"},
    {"bucket": "culture_cross_sector", "query": "AI culture music film literature tool release"},
]

BROAD_SEARXNG_ROWS = [
    {"bucket": "general_update", "query": "AI product update new feature now available"},
    {"bucket": "official_update", "query": "official AI announcement release rollout"},
    {"bucket": "impact", "query": "most important AI tool launch this week"},
    {"bucket": "impact", "query": "best new AI product release this week"},
    {"bucket": "market_tools", "query": "new AI app feature available to users"},
    {"bucket": "market_tools", "query": "AI tool launch users can now"},
    {"bucket": "market_tools", "query": "popular AI tool new feature rollout"},
    {"bucket": "audio_voice", "query": "AI voice tool product update release"},
    {"bucket": "audio_voice", "query": "AI music generation tool new feature"},
    {"bucket": "culture_knowledge", "query": "AI archive museum heritage tool update"},
    {"bucket": "culture_knowledge", "query": "AI translation tool new feature available"},
    {"bucket": "culture_knowledge", "query": "AI library archive research tool product update"},
    {"bucket": "daily_life", "query": "AI shopping assistant new feature available"},
    {"bucket": "daily_life", "query": "AI travel planning assistant update"},
    {"bucket": "daily_life", "query": "AI personal assistant app new capability"},
    {"bucket": "daily_life", "query": "AI calendar email browser assistant update"},
    {"bucket": "general_assistant", "query": "AI assistant app users can now"},
    {"bucket": "general_assistant", "query": "AI browser assistant feature rollout"},
    {"bucket": "learning", "query": "AI learning assistant product update"},
    {"bucket": "learning", "query": "AI education training app new feature"},
    {"bucket": "work_productivity", "query": "AI productivity creative workflow update"},
    {"bucket": "work_productivity", "query": "AI workplace assistant product update"},
    {"bucket": "work_productivity", "query": "AI document assistant new feature release"},
    {"bucket": "work_productivity", "query": "AI meeting assistant feature rollout"},
    {"bucket": "health_wellness", "query": "AI mental health wellness assistant product update"},
    {"bucket": "food_cooking", "query": "AI cooking meal planning app new feature"},
    {"bucket": "literature_writing", "query": "AI writing literature storytelling tool update"},
    {"bucket": "design_visual", "query": "AI design image video tool new feature"},
    {"bucket": "design_visual", "query": "AI image editing product update now available"},
    {"bucket": "fashion_style", "query": "virtual try on AI product update users"},
    {"bucket": "culture_cross_sector", "query": "AI music film culture tool release"},
]

SINGLE_ROWS = [
    {"bucket": "general_update", "query": '"AI product update" "new feature" "now available"'},
    {"bucket": "general_assistant", "query": '"AI assistant" "users can now" "rolling out"'},
    {"bucket": "work_productivity", "query": '"AI workflow" "release notes" "changelog"'},
    {"bucket": "daily_life", "query": '"AI shopping assistant" "product update"'},
    {"bucket": "daily_life", "query": '"AI travel assistant" "now available" OR "new feature"'},
    {"bucket": "culture_knowledge", "query": '"AI archive tool" "product update" OR "release notes"'},
    {"bucket": "learning", "query": '"AI learning assistant" "product update"'},
    {"bucket": "audio_voice", "query": '"AI voice" OR "AI narration" "product update"'},
    {"bucket": "work_visual", "query": '"AI presentation tool" "new feature" OR "release notes"'},
    {"bucket": "design_visual", "query": '"AI design tool" "product update" "new feature"'},
    {"bucket": "video_motion", "query": '"AI video generator" "release notes" OR "product update"'},
]

# Domains below are not treated as news/update evidence. They can point to an
# app, repo, PR wire, or social post, but not to a clear product-update article.
DISALLOWED_SOURCE_DOMAINS = (
    "apps.apple.com",
    "play.google.com",
    "instagram.com",
    "facebook.com",
    "linkedin.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "threads.net",
    "reddit.com",
    "youtube.com",
    "youtu.be",
    "pinterest.com",
    "github.com",
    "github.io",
    "gist.github.com",
    "prnewswire.com",
    "globenewswire.com",
    "businesswire.com",
    "accesswire.com",
    "prweb.com",
)

LOCAL_OR_UNKNOWN_APP_TERMS = (
    "australia-only",
    "australia only",
    "australia pilot",
    "in australia",
    "australian government",
    "australian city",
    "local app",
    "city app",
    "city of",
    "local government",
    "local authority",
    "local council",
    "city council",
    "state government",
    "statewide pilot",
    "municipal",
    "municipality",
    "council",
    "regional",
    "regional rollout",
    "single region",
    "one region",
    "province",
    "provincial",
    "pilot",
    "government pilot",
    "public sector pilot",
    "single customer",
    "one hospital",
    "one school",
    "one museum",
    "one city",
    "school district",
    "county",
    "town",
    "startup launches",
    "stealth startup",
    "booking demo",
    "request a demo",
    "enterprise-only",
    "enterprise only",
)

UPDATE_TERMS = (
    "new feature",
    "new capability",
    "product update",
    "release notes",
    "changelog",
    "now available",
    "public beta",
    "rolling out",
    "rollout",
    "released",
    "launches",
    "launched",
    "introduces",
    "adds",
    "users can now",
)

NOISE_TERMS = (
    "best ai",
    "best tools",
    "top ai",
    "top tools",
    "alternatives",
    "roundup",
    "guide",
    "tutorial",
    "how to",
    "review",
    "hands-on",
    "i tried",
    "conference",
    "expo",
    "summit",
    "event",
)

TECHNICAL_ONLY_TERMS = (
    "enterprise infrastructure",
    "ai enterprise",
    "sdk",
    "driver",
    "kernel",
    "benchmark",
    "gpu",
    "inference server",
)

BUSINESS_ONLY_TERMS = (
    "crm",
    "customer relationship management",
    "customer support",
    "support ticket",
    "help desk",
    "sales automation",
    "sales outreach",
    "lead generation",
    "marketing automation",
    "ad platform",
    "advertising platform",
    "finance automation",
    "financial services",
    "accounting",
    "bookkeeping",
    "payroll",
    "legal tech",
    "contract management",
    "admin tool",
    "administrative workflow",
    "back office",
    "hr software",
    "recruiting",
    "cybersecurity",
    "security operations",
)

COMPANY_SUFFIX_WORDS = {
    "ai",
    "app",
    "apps",
    "blog",
    "cloud",
    "co",
    "com",
    "company",
    "corp",
    "developer",
    "developers",
    "docs",
    "global",
    "inc",
    "io",
    "labs",
    "llc",
    "ltd",
    "news",
    "product",
    "products",
    "research",
    "studio",
    "technology",
    "tools",
    "www",
}


def search_url() -> str:
    base = SEARXNG_URL.rstrip("/")
    return base if base.endswith("/search") else f"{base}/search"


def has_arabic_text(value: str = "") -> bool:
    return bool(re.search(r"[\u0600-\u06ff]", str(value or "")))


def query_has_ai_scope(query: str = "") -> bool:
    clean = f" {str(query or '').lower()} "
    return bool(re.search(r"\bai\b", clean)) or "artificial intelligence" in clean


def ensure_ai_scope(query: str = "") -> str:
    clean = re.sub(r"\s+", " ", str(query or "").strip())
    if not clean:
        return ""
    if query_has_ai_scope(clean):
        return clean
    return f"{clean} AI artificial intelligence"


def unique_full_query_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for row in rows:
        query = ensure_ai_scope(row.get("query") or "")
        if not query or has_arabic_text(query):
            continue
        key = re.sub(r"\s+", " ", query.lower())
        if row.get("tool_query_required") and row.get("sector"):
            key = f"{key}|sector:{row.get('sector')}"
        if key in seen:
            continue
        seen.add(key)
        new_row = dict(row)
        new_row["bucket"] = new_row.get("bucket") or "general"
        new_row["query"] = query
        unique.append(new_row)
    return unique


def tool_group(item: dict) -> str:
    group = str((item or {}).get("group") or "").strip()
    if group in {"general_market", "culture_creative"}:
        return group
    hint = str((item or {}).get("sector_hint") or "").lower()
    return "general_market" if hint == "general_market" else "culture_creative"


_TOOL_CACHE_MAINTAINED_FOR = ""


def tool_record_key(item: dict | str) -> str:
    """Return the stable identity used to dedupe cached tool records."""
    if isinstance(item, str):
        return normalized_text(item)
    if not isinstance(item, dict):
        return ""
    return normalized_text(item.get("tool") or item.get("company") or "")


def tool_cache_is_stale(payload: dict) -> bool:
    """Return True when a tool cache should be refreshed this month."""
    updated = parse_result_datetime((payload or {}).get("updated") or (payload or {}).get("last_updated"))
    if updated is None:
        return True
    age_days = (utc_now() - updated).days
    return age_days >= max(1, AI_UPDATES_TOOL_CACHE_REFRESH_DAYS)


LIVE_TOOL_DISCOVERY_ROWS = [
    {"group": "general_market", "query": "most popular AI tools used by consumers knowledge workers this month"},
    {"group": "general_market", "query": "most used AI assistants productivity research writing tools 2026"},
    {"group": "general_market", "query": "AI products with highest user adoption traffic report 2026"},
    {"group": "culture_creative", "query": "popular AI tools for designers creators image video audio writing 2026"},
    {"group": "culture_creative", "query": "AI tools for culture creative work design video music storytelling learning 2026"},
    {"group": "culture_creative", "query": "popular AI tools for Arabic language translation learning content creation 2026"},
]

TOOL_DISCOVERY_SECTORS = [
    "museums",
    "films",
    "heritage",
    "fashion",
    "libraries",
    "music",
    "visual_arts",
    "literature",
    "cooking",
    "architecture",
    "theater",
    "mental_health",
    "physical_health",
    "work_productivity",
    "ai_education_training_daily_tasks",
]

TOOL_DISCOVERY_HINTS = [
    "general_market",
    "image_design",
    "video_creation",
    "audio_voice",
    "fashion_try_on",
    "writing_storytelling",
    "translation",
    "archives_research",
    "learning",
    "daily_assistant",
    "architecture",
]


def fetch_exa_tool_discovery_pages() -> list[dict]:
    """Fetch current market pages used only to refresh the monthly tools cache."""
    if not EXA_API_KEY:
        return []
    headers = {"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY}
    pages = []
    per_query = max(1, AI_UPDATES_TOOL_DISCOVERY_RESULTS)
    for row in LIVE_TOOL_DISCOVERY_ROWS:
        payload = {
            "query": ensure_ai_scope(row["query"]),
            "numResults": per_query,
            "type": "auto",
            "contents": {"text": True, "highlights": True},
        }
        try:
            response = requests.post("https://api.exa.ai/search", headers=headers, json=payload, timeout=AI_UPDATES_EXA_TIMEOUT)
            if response.status_code >= 400:
                continue
            data = response.json()
        except Exception:
            continue
        for result in data.get("results") or []:
            highlights = result.get("highlights") or []
            pages.append({
                "title": clean_text(result.get("title") or "")[:220],
                "content": clean_text(result.get("text") or " ".join(str(part or "") for part in highlights[:3]))[:900],
                "url": result.get("url") or "",
                "source_domain": source_domain(result.get("url") or ""),
                "query_group": row.get("group") or "",
                "query": row.get("query") or "",
                "source": "exa",
            })
    return pages


def fetch_searxng_tool_discovery_pages() -> list[dict]:
    """Fetch supplemental market pages from SearXNG when available."""
    endpoint = search_url()
    pages = []
    per_query = max(1, min(4, AI_UPDATES_TOOL_DISCOVERY_RESULTS))
    for row in LIVE_TOOL_DISCOVERY_ROWS:
        params = {
            "q": ensure_ai_scope(row["query"]),
            "format": "json",
            "language": "en",
            "time_range": AI_UPDATES_SEARXNG_TIME_RANGE,
            "categories": AI_UPDATES_SEARXNG_CATEGORIES,
            "pageno": 1,
        }
        try:
            response = requests.get(endpoint, params=params, timeout=AI_UPDATES_SEARXNG_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except Exception:
            continue
        for result in list(data.get("results") or [])[:per_query]:
            pages.append({
                "title": clean_text(result.get("title") or "")[:220],
                "content": clean_text(result.get("content") or result.get("snippet") or "")[:900],
                "url": result.get("url") or "",
                "source_domain": source_domain(result.get("url") or ""),
                "query_group": row.get("group") or "",
                "query": row.get("query") or "",
                "source": "searxng",
            })
    return pages


def extract_live_tool_records(pages: list[dict]) -> list[dict]:
    """Use a small monthly GPT call to extract actual AI product names."""
    if not pages or _tool_discovery_client is None:
        return []
    compact = [
        {
            "title": page.get("title") or "",
            "content": page.get("content") or "",
            "url": page.get("url") or "",
            "source_domain": page.get("source_domain") or "",
            "query_group": page.get("query_group") or "",
        }
        for page in pages[:36]
        if page.get("title") or page.get("content")
    ]
    if not compact:
        return []
    prompt = f"""
Extract current AI product/tool names from the provided market search results.

Return JSON only:
{{"tools":[{{"tool":str,"company":str,"group":str,"sector":str,"sector_hint":str,"tool_type":str,"cultural_applications":[str],"reason":str}}]}}

Rules:
- Keep only actual AI products or tools, not article titles, reports, categories, or websites.
- Prefer tools with broad user adoption, visible community interest, or clear creative/culture/daily/work use.
- Balance roughly half general_market and half culture_creative when evidence allows.
- group must be "general_market" or "culture_creative".
- tool_type must be "general" when it clearly serves 3+ use cases; otherwise "specialized".
- sector must be one of: {", ".join(TOOL_DISCOVERY_SECTORS)}.
- sector_hint must be one of: {", ".join(TOOL_DISCOVERY_HINTS)}.
- Reject CRM, customer support, sales, ads, marketing automation, finance, legal, cybersecurity, HR, developer-only infrastructure, listicles, and local/narrow apps.
- Limit to 24 tools. Use English product/company names.
""".strip()
    try:
        completion = _tool_discovery_client.chat.completions.create(
            model=AI_UPDATES_TOOL_DISCOVERY_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(compact, ensure_ascii=False, separators=(",", ":"))},
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(completion.choices[0].message.content or "{}")
    except Exception as exc:
        print(f"[AI Updates] live tool discovery extraction skipped: {exc}", flush=True)
        return []
    output = []
    for raw in data.get("tools") or []:
        item = normalize_tool_record(raw, source="live_monthly_discovery")
        if not tool_record_allowed(item):
            continue
        item["source"] = "live_monthly_discovery"
        item["sector_classification_source"] = item.get("sector_classification_source") or "gpt_live_monthly"
        item["updated"] = utc_now().date().isoformat()
        item["sources"] = list(dict.fromkeys([*(item.get("sources") or []), "exa", "searxng"]))
        item["mention_count"] = max(1, int(item.get("mention_count") or 0))
        item["popularity_score"] = max(60, int(item.get("popularity_score") or 0))
        output.append(item)
    records, _ = dedupe_tool_records(output, source="live_monthly_discovery")
    return records


def discover_tool_names_live() -> list[dict]:
    """Refresh monthly tool names from live market search, then cache the result."""
    if not AI_UPDATES_TOOL_DISCOVERY_ENABLED:
        return []
    pages = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(fetch_exa_tool_discovery_pages),
            executor.submit(fetch_searxng_tool_discovery_pages),
        ]
        for future in as_completed(futures):
            try:
                pages.extend(future.result() or [])
            except Exception:
                continue
    seen_urls = set()
    unique_pages = []
    for page in pages:
        url = memory_url_key(page.get("url") or "")
        title = normalized_text(page.get("title") or "")
        key = url or title
        if not key or key in seen_urls:
            continue
        seen_urls.add(key)
        unique_pages.append(page)
    records = extract_live_tool_records(unique_pages)
    print(
        f"[AI Updates] monthly live tool discovery pages={len(unique_pages)} tools={len(records)}",
        flush=True,
    )
    return records


def dedupe_tool_records(records: list[dict | str], *, source: str = "") -> tuple[list[dict], int]:
    """Normalize and merge tool records so cache files do not grow forever."""
    merged: dict[str, dict] = {}
    duplicates = 0
    for raw in records or []:
        item = normalize_tool_record(raw, source=source)
        if not tool_record_allowed(item):
            continue
        key = tool_record_key(item)
        if not key:
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = item
            continue
        duplicates += 1
        for field in (
            "company",
            "group",
            "sector",
            "primary_sector",
            "sector_hint",
            "tool_type",
            "cultural_applications",
            "secondary_sectors",
            "sources",
            "reason",
            "sector_classification_source",
            "updated",
            "source",
        ):
            if item.get(field) and not existing.get(field):
                existing[field] = item[field]
        existing["mention_count"] = max(int(existing.get("mention_count") or 0), int(item.get("mention_count") or 0))
        if existing.get("best_rank") is None or (
            item.get("best_rank") is not None
            and int(item.get("best_rank") or 9999) < int(existing.get("best_rank") or 9999)
        ):
            existing["best_rank"] = item.get("best_rank")
        existing["popularity_score"] = max(
            int(existing.get("popularity_score") or 0),
            int(item.get("popularity_score") or 0),
        )
    output = sorted(
        merged.values(),
        key=lambda item: (int(item.get("popularity_score") or 0), 0 if tool_group(item) == "general_market" else -1),
        reverse=True,
    )
    return output[: max(1, AI_UPDATES_TOOL_CACHE_MAX_RECORDS)], duplicates


def maintain_monthly_tool_files(*, force_refresh: bool = False) -> None:
    """Monthly cache hygiene: dedupe tool JSON files and cap their size."""
    global _TOOL_CACHE_MAINTAINED_FOR
    today = utc_now().date().isoformat()
    if _TOOL_CACHE_MAINTAINED_FOR == today and not force_refresh:
        return
    _TOOL_CACHE_MAINTAINED_FOR = today

    monthly = load_json(MONTHLY_TOOLS_FILE, {"tool_records": [], "tools": []})
    monthly_stale = force_refresh or tool_cache_is_stale(monthly)
    live_monthly_records = discover_tool_names_live() if monthly_stale else []
    monthly_records, monthly_dupes = dedupe_tool_records(
        [*live_monthly_records, *(monthly.get("tool_records") or []), *(monthly.get("tools") or [])],
        source="monthly_tools",
    )
    monthly_needs_write = monthly_stale or monthly_dupes > 0 or len(live_monthly_records) > 0 or len(monthly_records) != len(monthly.get("tool_records") or [])
    if monthly_records and monthly_needs_write:
        safe_write_json(
            MONTHLY_TOOLS_FILE,
            {
                "schema": monthly.get("schema") or "sector_tool_lists_v8",
                "updated": today,
                "live_discovery": {
                    "enabled": bool(AI_UPDATES_TOOL_DISCOVERY_ENABLED),
                    "ran": bool(live_monthly_records),
                    "added_or_refreshed": len(live_monthly_records),
                    "refresh_days": AI_UPDATES_TOOL_CACHE_REFRESH_DAYS,
                },
                "tools": [item.get("tool") for item in monthly_records if item.get("tool")],
                "tool_records": monthly_records,
            },
        )

    scored = load_json(TOOLS_SCORED_FILE, {"tools": []})
    scored_records, scored_dupes = dedupe_tool_records(scored.get("tools") or [], source="tools_scored")
    scored_needs_write = tool_cache_is_stale(scored) or scored_dupes > 0 or len(scored_records) != len(scored.get("tools") or [])
    if scored_records and scored_needs_write:
        safe_write_json(
            TOOLS_SCORED_FILE,
            {
                "schema": scored.get("schema") or "tools_scored_v1",
                "updated": today,
                "tools": scored_records,
            },
        )

    sector_map = load_json(TOOL_SECTOR_MAP_FILE, {"tools": {}})
    raw_tools = sector_map.get("tools") if isinstance(sector_map.get("tools"), dict) else {}
    sector_records, sector_dupes = dedupe_tool_records(list(raw_tools.values()), source="tool_sector_map")
    sector_needs_write = tool_cache_is_stale(sector_map) or sector_dupes > 0 or len(sector_records) != len(raw_tools)
    if sector_records and sector_needs_write:
        safe_write_json(
            TOOL_SECTOR_MAP_FILE,
            {
                "schema": sector_map.get("schema") or "tool_sector_map_v1",
                "updated": today,
                "tools": {tool_record_key(item): item for item in sector_records if tool_record_key(item)},
            },
        )


def cap_tool_groups(tools: list[dict], limit: int) -> list[dict]:
    """Keep discovered tools balanced: 50% general and 50% cultural when possible."""
    limit = max(1, int(limit or 1))
    general = [tool for tool in tools or [] if tool_group(tool) == "general_market"]
    culture = [tool for tool in tools or [] if tool_group(tool) != "general_market"]
    culture_target = limit // 2
    general_target = limit - culture_target
    selected = []
    for index in range(max(culture_target, general_target)):
        if index < general_target and index < len(general):
            selected.append(general[index])
        if index < culture_target and index < len(culture):
            selected.append(culture[index])
    seen = {normalized_text(item.get("tool") or item.get("company") or "") for item in selected}
    for item in [*culture[culture_target:], *general[general_target:]]:
        key = normalized_text(item.get("tool") or item.get("company") or "")
        if key and key in seen:
            continue
        selected.append(item)
        if key:
            seen.add(key)
        if len(selected) >= limit:
            break
    return selected[:limit]


def normalize_tool_record(item: dict | str, *, source: str = "") -> dict:
    """Normalize cached monthly/tool-sector records into one simple shape."""
    if isinstance(item, str):
        tool = clean_text(item)
        return {
            "tool": tool,
            "company": "",
            "group": "general_market",
            "sector": "ai_education_training_daily_tasks",
            "sector_hint": "general_market",
            "tool_type": "general",
            "source": source,
        }
    if not isinstance(item, dict):
        return {}
    sector = item.get("sector") or item.get("primary_sector") or ""
    sector_hint = item.get("sector_hint") or ("general_market" if item.get("group") == "general_market" else sector)
    group = item.get("group") or ("general_market" if sector_hint == "general_market" else "culture_creative")
    tool_type = item.get("tool_type") or ("general" if group == "general_market" else "specialized")
    return {
        "tool": clean_text(item.get("tool") or item.get("name") or ""),
        "company": clean_text(item.get("company") or ""),
        "group": group,
        "sector": sector,
        "primary_sector": item.get("primary_sector") or sector,
        "sector_hint": sector_hint,
        "tool_type": tool_type,
        "cultural_applications": list(item.get("cultural_applications") or []),
        "secondary_sectors": list(item.get("secondary_sectors") or []),
        "popularity_score": int(item.get("popularity_score") or 0),
        "sources": list(item.get("sources") or []),
        "mention_count": int(item.get("mention_count") or 0),
        "best_rank": item.get("best_rank"),
        "reason": clean_text(item.get("reason") or ""),
        "sector_classification_source": item.get("sector_classification_source") or item.get("source") or source,
        "updated": item.get("updated") or "",
        "source": source or item.get("source") or item.get("sector_classification_source") or "",
    }


def tool_record_allowed(item: dict) -> bool:
    """Keep the tool layer focused on AI/culture/daily-use tools, not B2B admin categories."""
    tool = clean_text(item.get("tool") or "")
    if len(tool) < 3:
        return False
    text = " ".join(
        str(item.get(key) or "")
        for key in ("tool", "company", "group", "sector", "sector_hint", "tool_type", "source")
    ).lower()
    if text_has_any(text, BUSINESS_ONLY_TERMS):
        return False
    return True


def load_monthly_tool_records(limit: int = 24, *, force_refresh: bool = False) -> list[dict]:
    """Load cached market tools and balance general vs culture/creative tools."""
    maintain_monthly_tool_files(force_refresh=force_refresh)
    records: dict[str, dict] = {}

    def add(raw: dict | str, source: str) -> None:
        item = normalize_tool_record(raw, source=source)
        if not tool_record_allowed(item):
            return
        key = normalized_text(item.get("tool") or item.get("company") or "")
        if not key:
            return
        existing = records.get(key)
        if existing is None:
            records[key] = item
            return
        for field in ("company", "group", "sector", "sector_hint", "tool_type", "cultural_applications", "secondary_sectors"):
            if item.get(field) and not existing.get(field):
                existing[field] = item[field]
        existing["popularity_score"] = max(int(existing.get("popularity_score") or 0), int(item.get("popularity_score") or 0))

    sector_map = load_json(TOOL_SECTOR_MAP_FILE, {"tools": {}}).get("tools") or {}
    if isinstance(sector_map, dict):
        for raw in sector_map.values():
            add(raw, "tool_sector_map")

    monthly = load_json(MONTHLY_TOOLS_FILE, {"tool_records": [], "tools": []})
    for raw in monthly.get("tool_records") or []:
        add(raw, "monthly_tools")
    for raw in monthly.get("tools") or []:
        add(raw, "monthly_tools")

    scored = load_json(TOOLS_SCORED_FILE, {"tools": {}})
    for raw in scored.get("tools") or []:
        add(raw, "tools_scored")

    tools = sorted(
        records.values(),
        key=lambda item: (int(item.get("popularity_score") or 0), 0 if tool_group(item) == "general_market" else -1),
        reverse=True,
    )
    return cap_tool_groups(tools, limit)


def compose_query_mix_rows(
    tool_rows: list[dict],
    specialized_rows: list[dict],
    broad_rows: list[dict],
    limit: int,
) -> tuple[list[dict], dict]:
    """Apply the intended 50/30/20 query mix without making it a result quota."""
    limit = max(1, int(limit or 1))
    budgets = {
        "tool_driven": round(limit * 0.45),
        "specialized": round(limit * 0.4),
        "broad": 0,
    }
    budgets["broad"] = max(0, limit - budgets["tool_driven"] - budgets["specialized"])
    if limit >= 3 and budgets["broad"] < 1:
        budgets["broad"] = 1
        if budgets["specialized"] > 0:
            budgets["specialized"] -= 1
        else:
            budgets["tool_driven"] = max(1, budgets["tool_driven"] - 1)
    parts = [
        ("tool_driven", tool_rows, budgets["tool_driven"]),
        ("specialized", specialized_rows, budgets["specialized"]),
        ("broad", broad_rows, budgets["broad"]),
    ]
    rows = []
    for mix, source_rows, count in parts:
        for row in unique_full_query_rows(source_rows)[:count]:
            rows.append({**row, "query_mix": mix})
    if len(rows) < limit:
        seen = {re.sub(r"\s+", " ", row.get("query", "").lower()) for row in rows}
        for row in unique_full_query_rows([*(tool_rows or []), *(specialized_rows or []), *(broad_rows or [])]):
            key = re.sub(r"\s+", " ", row.get("query", "").lower())
            if key in seen:
                continue
            rows.append({**row, "query_mix": row.get("query_mix") or "fill"})
            seen.add(key)
            if len(rows) >= limit:
                break
    return rows[:limit], {"budgets": budgets}


SECTOR_HINT_TO_SECTOR = {
    "image_design": "visual_arts",
    "design": "visual_arts",
    "video_creation": "films",
    "audio_voice": "music",
    "music_voice": "music",
    "fashion_try_on": "fashion",
    "writing_storytelling": "literature",
    "translation": "literature",
    "archives_research": "libraries",
    "learning": "ai_education_training_daily_tasks",
    "daily_assistant": "ai_education_training_daily_tasks",
    "architecture": "architecture",
}

SECTOR_QUERY_TERMS = {
    "films": "film video editing creative work",
    "visual_arts": "design image visual creative work",
    "music": "audio voice music narration",
    "fashion": "fashion style try on",
    "literature": "writing translation storytelling",
    "libraries": "research archives knowledge",
    "ai_education_training_daily_tasks": "learning productivity daily tasks assistant",
    "work_productivity": "productivity documents meetings workflow",
}


def build_tool_queries(tools: list[dict]) -> dict:
    """Build recent AI update queries for discovered tools.

    The tool name narrows the search, while "AI artificial intelligence" keeps
    ordinary app-update stories out of the candidate pool. Every tool receives
    a broad "latest AI updates" query and, when classification exists, an
    additional use-case query. This keeps large general tools visible while
    still giving cultural/specialized tools a precise search angle.
    """
    exa_rows = []
    searxng_rows = []

    def classified_sectors(item: dict, tool_type: str, group: str) -> list[str]:
        sectors = []
        for value in list((item or {}).get("cultural_applications") or [])[:3]:
            if value:
                sectors.append(str(value))
        for value in ((item or {}).get("sector"), (item or {}).get("primary_sector")):
            if value:
                sectors.append(str(value))
        hint_sector = SECTOR_HINT_TO_SECTOR.get(str((item or {}).get("sector_hint") or ""), "")
        if hint_sector:
            sectors.append(hint_sector)
        if not sectors and (tool_type == "general" or group == "general_market"):
            sectors.append("ai_education_training_daily_tasks")
        if not sectors:
            sectors.append("visual_arts")
        clean = []
        seen = set()
        for sector in sectors:
            key = normalized_text(sector)
            if not key or key in {"general-market", "general_market", "multiple", "multi"} or key in seen:
                continue
            seen.add(key)
            clean.append(sector)
        return clean[:3] or ["ai_education_training_daily_tasks"]

    def add_rows(row: dict, *, searxng_suffix: str) -> None:
        exa_rows.append(row)
        searxng_rows.append({**row, "query": f'{row["query"]} {searxng_suffix}'.strip()})

    for item in tools or []:
        tool = clean_text((item or {}).get("tool") or "")
        company = clean_text((item or {}).get("company") or "")
        name = tool or company
        if not name:
            continue
        group = tool_group(item)
        raw_type = (item or {}).get("tool_type")
        tool_type = raw_type or ("general" if group == "general_market" else "specialized")

        general_base = f'"{name}" AI artificial intelligence latest updates new feature official announcement'
        add_rows(
            {
                "bucket": "tool_general_updates",
                "query": general_base,
                "source_type": "trending_tool",
                "tool": tool,
                "company": company,
                "tool_query_required": True,
                "tool_type": tool_type,
                "sector": "general_market" if tool_type == "general" else ((item or {}).get("sector") or ""),
                "sector_hint": "general_market" if tool_type == "general" else ((item or {}).get("sector_hint") or ""),
                "tool_sector_terms": "",
                "tool_score": int((item or {}).get("popularity_score") or 0),
                "tool_query_variant": "general_latest_updates",
            },
            searxng_suffix="product update release notes changelog",
        )

        sectors = classified_sectors(item, tool_type, group)
        for sector in sectors:
            terms = SECTOR_QUERY_TERMS.get(sector, "productivity learning creative work")
            base = f'"{name}" AI artificial intelligence latest updates new feature official announcement {terms}'
            row = {
                "bucket": f"tool_{sector}",
                "query": base,
                "source_type": "trending_tool",
                "tool": tool,
                "company": company,
                "tool_query_required": True,
                "tool_type": tool_type,
                "sector": sector,
                "sector_hint": (item or {}).get("sector_hint") or sector,
                "tool_sector_terms": terms,
                "tool_score": int((item or {}).get("popularity_score") or 0),
                "tool_query_variant": "classified_use_case",
            }
            add_rows(row, searxng_suffix="product update release notes changelog")
    return {"exa": unique_full_query_rows(exa_rows), "searxng": unique_full_query_rows(searxng_rows)}


LAST_DISCOVERY_META: dict[str, dict] = {}


def discovery_rows(source: str, *, single: bool = False, target_hint: str = "") -> list[dict]:
    """Return the final query rows for one provider.

    Full generation uses a larger query budget. Single refill uses the same
    discovery strategy with smaller limits and a target hint from the card.
    """
    if single:
        base_rows = list(SINGLE_ROWS)
        hint = target_hint.lower()
        if any(term in hint for term in ("design", "image", "visual", "fashion", "culture", "audio", "video")):
            priority = ("culture", "audio", "daily", "learning", "video", "design", "fashion")
        elif any(term in hint for term in ("daily", "shopping", "travel", "mobile", "personal")):
            priority = ("daily", "shopping", "travel", "mobile", "personal", "assistant", "audio", "culture")
        else:
            priority = ("impact", "market", "general", "daily", "work", "assistant", "learning", "culture", "audio", "design", "video")
        broad = BROAD_EXA_ROWS if source == "exa" else BROAD_SEARXNG_ROWS
        source_rows = [*broad, *base_rows] if source == "searxng" else [*base_rows, *broad]
        base_rows = sorted(source_rows, key=lambda row: 0 if any(p in str(row.get("bucket") or "") for p in priority) else 1)
        limit = AI_UPDATES_SINGLE_EXA_QUERY_LIMIT if source == "exa" else AI_UPDATES_SINGLE_SEARXNG_QUERY_LIMIT
        tools = load_monthly_tool_records(limit=6)
        tool_queries = build_tool_queries(tools).get(source, [])
        rows, mix_meta = compose_query_mix_rows(
            tool_queries,
            base_rows,
            [MOTHER_QUERY_ROW, *GENERAL_AI_UPDATE_ROWS, *broad],
            limit,
        )
        LAST_DISCOVERY_META[source] = {
            "tool_count": len(tools),
            "tool_names": [tool.get("tool") for tool in tools],
            "query_mix": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
            "tool_query_variant_rows": dict(Counter(row.get("tool_query_variant") or "none" for row in rows)),
            "query_mix_budgets": mix_meta.get("budgets", {}),
            "single": True,
        }
        return rows
    broad = BROAD_EXA_ROWS if source == "exa" else BROAD_SEARXNG_ROWS
    limit = AI_UPDATES_EXA_QUERY_LIMIT if source == "exa" else AI_UPDATES_SEARXNG_QUERY_LIMIT
    tools = load_monthly_tool_records(limit=24)
    tool_queries = build_tool_queries(tools).get(source, [])
    rows, mix_meta = compose_query_mix_rows(
        tool_queries,
        DEFAULT_QUERY_ROWS,
        [MOTHER_QUERY_ROW, *GENERAL_AI_UPDATE_ROWS, *broad],
        limit,
    )
    LAST_DISCOVERY_META[source] = {
        "tool_count": len(tools),
        "tool_names": [tool.get("tool") for tool in tools],
        "tool_group_counts": dict(Counter(tool_group(tool) for tool in tools)),
        "query_mix": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
        "tool_query_variant_rows": dict(Counter(row.get("tool_query_variant") or "none" for row in rows)),
        "query_mix_budgets": mix_meta.get("budgets", {}),
        "single": False,
    }
    return rows


def freshness_query(query: str) -> str:
    query = query.strip()
    cutoff = recency_cutoff_query_token()
    year = str(utc_now().year)
    if "after:" not in query.lower():
        query = f"{query} after:{cutoff}"
    if year not in query:
        query = f"{query} {year}"
    return query


def domain_blocked(domain: str) -> bool:
    return any(domain == blocked or domain.endswith(f".{blocked}") for blocked in DISALLOWED_SOURCE_DOMAINS)


def source_candidate_hard_reject_reason(item: dict) -> str:
    domain = source_domain((item or {}).get("url") or (item or {}).get("source_url") or "")
    if any(domain == blocked or domain.endswith(f".{blocked}") for blocked in APP_STORE_DOMAINS):
        return "app_store_listing_not_news_source"
    return ""


def tool_query_reject_reason(row: dict, item: dict) -> str:
    if not (row or {}).get("tool_query_required"):
        return ""
    tool = normalized_text((row or {}).get("tool") or "")
    company = normalized_text((row or {}).get("company") or "")
    names = [name for name in (tool, company) if name]
    if not names:
        return ""
    haystack = normalized_text(
        " ".join(
            str((item or {}).get(key) or "")
            for key in ("title", "content", "summary", "url", "source_domain")
        )
    )
    return "" if any(name in haystack for name in names) else "tool_query_mismatch"


def text_has_any(text: str, terms: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(term in lower for term in terms)


def text_has_whole_term(text: str, terms: tuple[str, ...]) -> bool:
    lower = text.lower()
    for term in terms:
        pattern = r"\b" + re.escape(term.lower()).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pattern, lower):
            return True
    return False


def has_known_company_signal(text: str = "", domain: str = "") -> bool:
    """Return true for clear public product evidence, not for hard-coded brands."""
    blob = str(text or "").lower()
    clean_domain = (domain or "").lower().replace("www.", "")
    if not clean_domain or domain_blocked(clean_domain):
        return False
    if text_has_whole_term(blob, LOCAL_OR_UNKNOWN_APP_TERMS):
        return False
    
    
    product_terms = (
        "app",
        "application",
        "assistant",
        "tool",
        "platform",
        "product",
        "feature",
        "workspace",
        "plugin",
        "extension",
        "browser",
        "mobile",
        "web app",
        "creative suite",
        "editor",
        "generator",
        "users",
        "customers",
        "creators",
        "teams",
    )
    availability_terms = (
        "now available",
        "available to users",
        "users can now",
        "rolling out",
        "rollout",
        "public beta",
        "generally available",
        "launched",
        "launches",
        "released",
        "introduces",
        "new feature",
        "new capability",
        "product update",
    )
    return text_has_any(blob, product_terms) and text_has_any(blob, availability_terms)


def infer_sector(title: str = "", content: str = "", bucket: str = "") -> str:
    text = f"{title} {content} {bucket}".lower()
    checks = [
        ("المتاحف", ("museum", "museums", "gallery", "arts and culture")),
        ("الأفلام", ("film", "movie", "cinema", "video", "runway", "pika", "luma")),
        ("التراث", ("heritage", "archive", "archives", "manuscript", "restoration")),
        ("الأزياء", ("fashion", "style", "try-on", "outfit", "apparel")),
        ("المكتبات", ("library", "book", "knowledge", "research")),
        ("الموسيقى", ("music", "song", "audio", "voice", "narration", "elevenlabs")),
        ("الفنون البصرية", ("design", "image", "visual", "photo", "photoshop", "firefly", "figma", "canva", "midjourney", "krea", "ideogram")),
        ("الأدب", ("writing", "literature", "author", "storytelling", "translation")),
        ("الطهي", ("food", "recipe", "cooking", "kitchen")),
        ("العمارة", ("architecture", "interior", "building", "urban")),
        ("المسرح", ("theater", "theatre", "stage", "performance")),
        ("الصحة النفسية", ("mental health", "wellbeing", "therapy", "meditation")),
        ("الصحة الجسدية", ("fitness", "health", "workout", "sleep")),
        ("إنتاجية العمل", ("workflow", "productivity", "workspace", "presentation", "meeting", "document", "automation", "zapier", "n8n", "copilot")),
    ]
    for sector, terms in checks:
        if any(term in text for term in terms):
            return sector
    return "الذكاء الاصطناعي والتعليم والتدريب والمهام اليومية"


def candidate_owner_key(item: dict | None = None, *, url: str = "", title: str = "", content: str = "") -> str:
    item = item or {}
    explicit = item.get("company_name") or item.get("company") or item.get("tool_name") or item.get("product_name")
    if explicit:
        key = normalized_text(explicit)
        words = [word for word in key.split() if word not in COMPANY_SUFFIX_WORDS]
        return "-".join(words[:3]) or key

    domain = source_domain(url or item.get("url") or item.get("official_url") or "")
    host_parts = [part for part in domain.split(".") if part and part not in COMPANY_SUFFIX_WORDS]
    if host_parts:
        return host_parts[0]

    fallback = normalized_text(f"{title or item.get('title') or ''} {content or item.get('content') or ''}")
    words = [word for word in fallback.split() if word not in COMPANY_SUFFIX_WORDS and len(word) > 2]
    return "-".join(words[:2])


def flag_weak_sectors(items: list[dict], minimum: int = 3) -> dict:
    """Report sectors that produced too few clean candidates in this run."""
    counts = Counter((item or {}).get("sector") or "unknown" for item in items or [])
    weak = {
        sector: int(counts.get(sector, 0))
        for sector in NEWS_SECTORS
        if int(counts.get(sector, 0)) < minimum
    }
    return {
        "minimum": minimum,
        "counts": dict(counts),
        "weak": weak,
    }


def update_sector_terms(winning_articles: list[dict], diagnostics: dict | None = None) -> None:
    """Persist a tiny learning trace from selected articles without extra model calls."""
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    history = load_json(SECTOR_TERMS_HISTORY_FILE, {"sectors": {}, "updated": ""})
    sectors = history.get("sectors") if isinstance(history.get("sectors"), dict) else {}
    changed = False
    for item in winning_articles or []:
        if not isinstance(item, dict):
            continue
        sector = item.get("sector") or "unknown"
        text = normalized_text(" ".join(str(item.get(key) or "") for key in ("title", "tool_name", "company_name", "source_query")))
        terms = [word for word in text.split() if len(word) >= 4][:12]
        record = sectors.get(sector) if isinstance(sectors.get(sector), dict) else {}
        learned = list(record.get("learned_terms") or [])
        for term in terms:
            if term not in learned:
                learned.append(term)
        record["learned_terms"] = learned[-10:]
        record["last_updated"] = utc_now().date().isoformat()
        sectors[sector] = record
        changed = True
    if changed:
        history["sectors"] = sectors
        history["updated"] = utc_now().isoformat()
        safe_write_json(SECTOR_TERMS_HISTORY_FILE, history)
    diagnostics["sector_terms_learning_saved"] = bool(changed)


def normalize_candidate(raw: dict, *, query: str, bucket: str, source: str, single: bool = False) -> dict | None:
    title = clean_text(raw.get("title") or "")
    url = str(raw.get("url") or "").strip()
    highlights = raw.get("highlights") or []
    content = clean_text(
        raw.get("content")
        or raw.get("snippet")
        or raw.get("text")
        or raw.get("summary")
        or " ".join(str(part or "") for part in highlights[:3])
    )[:2200]
    if not title or not url:
        return None
    domain = source_domain(url)
    if source_candidate_hard_reject_reason({"url": url}):
        return None
    if domain_blocked(domain):
        return None
    text = f"{title} {content}"
    if text_has_any(text, NOISE_TERMS):
        return None
    if text_has_any(text, TECHNICAL_ONLY_TERMS):
        return None
    if text_has_any(text, BUSINESS_ONLY_TERMS):
        return None
    known_signal = has_known_company_signal(text, domain)
    if text_has_whole_term(text, LOCAL_OR_UNKNOWN_APP_TERMS):
        return None
    published_raw = raw.get("publishedDate") or raw.get("published_date") or raw.get("pubdate") or raw.get("date") or ""
    if not result_is_recent_enough(published_raw):
        return None
    published_dt = parse_result_datetime(published_raw)
    item = {
        "title": title,
        "content": content,
        "url": url,
        "source": raw.get("engine") or domain or source,
        "source_domain": domain,
        "query": query,
        "bucket": bucket,
        "sector": infer_sector(title, content, bucket),
        "fetch_source": source,
        "source_group": source,
        "published_date": published_dt.isoformat() if published_dt else "",
        "published_raw": str(published_raw or ""),
        "recency_window_days": AI_UPDATES_LOOKBACK_DAYS,
        "known_company_signal": bool(known_signal),
    }
    item["owner_key"] = candidate_owner_key(item, url=url, title=title, content=content)
    item["story_key"] = hashlib.sha1(f"{domain}|{normalized_text(title)[:120]}".encode("utf-8")).hexdigest()[:24]
    return item


def result_is_excluded(item: dict, exclude_items: list[dict] | None = None) -> bool:
    if not exclude_items:
        return False
    url = memory_url_key(item.get("url") or "")
    title = normalized_text(item.get("title") or "")
    text = normalized_text(f"{item.get('title') or ''} {item.get('content') or item.get('summary') or ''}")

    def topic_tokens(value: str = "") -> set[str]:
        stop = {
            "the", "and", "for", "with", "from", "that", "this", "into", "about",
            "new", "update", "updates", "feature", "features", "launch", "launches",
            "ai", "artificial", "intelligence", "tool", "tools", "app", "platform",
        }
        return {
            token for token in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", normalized_text(value))
            if token not in stop and len(token) > 3
        }

    item_tokens = topic_tokens(text)
    for existing in exclude_items:
        if not isinstance(existing, dict):
            continue
        existing_url = memory_url_key(existing.get("url") or existing.get("original_url") or existing.get("source_url") or "")
        if url and existing_url and url == existing_url:
            return True
        existing_title = normalized_text(existing.get("title") or existing.get("original_title") or "")
        if title and existing_title and (title == existing_title or title in existing_title or existing_title in title):
            return True
        existing_text = normalized_text(
            f"{existing.get('title') or existing.get('original_title') or ''} "
            f"{existing.get('text') or existing.get('summary') or existing.get('content') or ''}"
        )
        existing_tokens = topic_tokens(existing_text)
        if item_tokens and existing_tokens:
            overlap = len(item_tokens & existing_tokens)
            smaller = max(1, min(len(item_tokens), len(existing_tokens)))
            if overlap >= 4 and (overlap / smaller) >= 0.58:
                return True
    return False


def fetch_searxng_query_rows(rows: list[dict], *, exclude_items: list[dict] | None = None, single: bool = False) -> tuple[list[dict], dict]:
    endpoint = search_url()
    timeout = AI_UPDATES_SINGLE_TIMEOUT if single else AI_UPDATES_SEARXNG_TIMEOUT
    per_query = AI_UPDATES_SINGLE_RESULTS_PER_QUERY if single else AI_UPDATES_SEARXNG_RESULTS_PER_QUERY
    diagnostics = {"source": "searxng", "queries": len(rows), "raw_results": 0, "query_counts": {}, "query_texts": [r.get("query") for r in rows]}

    def fetch_row(row: dict):
        base_query = row["query"]
        query = freshness_query(base_query)
        params = {
            "q": query,
            "format": "json",
            "language": "en",
            "time_range": AI_UPDATES_SEARXNG_TIME_RANGE,
            "categories": AI_UPDATES_SEARXNG_CATEGORIES,
            "pageno": 1,
        }
        try:
            response = requests.get(endpoint, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            return row, [], 0, f"searxng_request_failed:{exc}"
        raw_results = list(data.get("results") or [])[:per_query]
        items = []
        for raw in raw_results:
            item = normalize_candidate(raw, query=query, bucket=row.get("bucket") or "general", source="searxng", single=single)
            if item:
                reject_reason = tool_query_reject_reason(row, item)
                if reject_reason:
                    item = None
            if item:
                for key in ("source_type", "tool", "company", "tool_type", "sector_hint", "query_mix", "tool_score", "tool_query_variant"):
                    if row.get(key) is not None:
                        item[key] = row.get(key)
            if item and not result_is_excluded(item, exclude_items):
                items.append(item)
        return row, items, len(raw_results), ""

    started = time.time()
    output = []
    seen = set()
    with ThreadPoolExecutor(max_workers=max(1, len(rows))) as executor:
        futures = [executor.submit(fetch_row, row) for row in rows]
        for future in as_completed(futures):
            row, items, raw_count, error = future.result()
            diagnostics["raw_results"] += raw_count
            diagnostics["query_counts"][row.get("query") or ""] = raw_count
            if error:
                diagnostics.setdefault("errors", []).append(error[:220])
                diagnostics["error"] = diagnostics.get("error") or error.split(":", 1)[0]
                continue
            for item in items:
                key = item["url"]
                if key in seen:
                    continue
                seen.add(key)
                output.append(item)
    diagnostics["seconds"] = round(time.time() - started, 2)
    diagnostics["unique_results"] = len(output)
    return output, diagnostics


def fetch_exa_query_rows(rows: list[dict], *, exclude_items: list[dict] | None = None, single: bool = False) -> tuple[list[dict], dict]:
    diagnostics = {"source": "exa", "queries": len(rows), "raw_results": 0, "query_counts": {}, "query_texts": [r.get("query") for r in rows]}
    if not EXA_API_KEY:
        diagnostics["error"] = "missing_exa_api_key"
        return [], diagnostics
    per_query = AI_UPDATES_SINGLE_EXA_RESULTS_PER_QUERY if single else AI_UPDATES_EXA_RESULTS_PER_QUERY
    headers = {"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY}

    def fetch_row(row: dict):
        payload = {
            "query": freshness_query(row["query"]),
            "numResults": max(1, per_query),
            "type": "auto",
            "startPublishedDate": recency_cutoff_query_token(),
            "contents": {"text": True, "highlights": True},
        }
        try:
            response = requests.post("https://api.exa.ai/search", headers=headers, json=payload, timeout=AI_UPDATES_EXA_TIMEOUT)
            if response.status_code >= 400:
                return row, [], 0, f"exa_request_failed:{response.status_code}"
            data = response.json()
        except Exception as exc:
            return row, [], 0, f"exa_request_failed:{exc}"
        raw_results = list(data.get("results") or [])[:per_query]
        items = []
        for raw in raw_results:
            item = normalize_candidate(raw, query=row["query"], bucket=row.get("bucket") or "general", source="exa", single=single)
            if item:
                reject_reason = tool_query_reject_reason(row, item)
                if reject_reason:
                    item = None
            if item:
                for key in ("source_type", "tool", "company", "tool_type", "sector_hint", "query_mix", "tool_score", "tool_query_variant"):
                    if row.get(key) is not None:
                        item[key] = row.get(key)
            if item and not result_is_excluded(item, exclude_items):
                items.append(item)
        return row, items, len(raw_results), ""

    started = time.time()
    output = []
    seen = set()
    with ThreadPoolExecutor(max_workers=max(1, len(rows))) as executor:
        futures = [executor.submit(fetch_row, row) for row in rows]
        for future in as_completed(futures):
            row, items, raw_count, error = future.result()
            diagnostics["raw_results"] += raw_count
            diagnostics["query_counts"][row.get("query") or ""] = raw_count
            if error:
                diagnostics.setdefault("errors", []).append(error[:220])
                diagnostics["error"] = diagnostics.get("error") or error.split(":", 1)[0]
                continue
            for item in items:
                key = item["url"]
                if key in seen:
                    continue
                seen.add(key)
                output.append(item)
    diagnostics["seconds"] = round(time.time() - started, 2)
    diagnostics["unique_results"] = len(output)
    return output, diagnostics

def combine_source_results(source_results: list[tuple[str, list[dict], dict]], *, mode: str) -> tuple[list[dict], dict]:
    seen = set()
    output = []
    raw_results = 0
    total_queries = 0
    source_diagnostics = {}
    failures = {}
    for source, items, diagnostics in source_results:
        source_diagnostics[source] = diagnostics
        raw_results += int(diagnostics.get("raw_results") or 0)
        total_queries += int(diagnostics.get("queries") or 0)
        if diagnostics.get("error"):
            failures[source] = diagnostics.get("error")
        for item in items:
            key = item.get("url") or ""
            if key in seen:
                continue
            seen.add(key)
            output.append(item)
    diagnostics = {
        "mode": mode,
        "sources": list(source_diagnostics.keys()),
        "source_diagnostics": source_diagnostics,
        "source_failures": failures,
        "queries": total_queries,
        "raw_results": raw_results,
        "unique_results": len(output),
        "source_candidate_counts": dict(Counter(item.get("fetch_source") or "unknown" for item in output)),
        "tool_query_variant_counts": dict(Counter(item.get("tool_query_variant") or "none" for item in output)),
        "exa_queries": source_diagnostics.get("exa", {}).get("queries", 0),
        "searxng_queries": source_diagnostics.get("searxng", {}).get("queries", 0),
        "exa_raw": source_diagnostics.get("exa", {}).get("raw_results", 0),
        "searxng_raw": source_diagnostics.get("searxng", {}).get("raw_results", 0),
        "exa_seconds": source_diagnostics.get("exa", {}).get("seconds", 0),
        "searxng_seconds": source_diagnostics.get("searxng", {}).get("seconds", 0),
        "lookback_days": AI_UPDATES_LOOKBACK_DAYS,
        "cutoff_date": recency_cutoff_query_token(),
    }
    if not output:
        diagnostics["error"] = "all_live_sources_failed" if failures else "live_sources_returned_no_results"
    return output, diagnostics


def fetch_news_candidates(*, exclude_items: list[dict] | None = None, target_hint: str = "", single: bool = False) -> tuple[list[dict], dict]:
    """Fetch news candidates from Exa and SearXNG in parallel."""
    started = time.time()
    exa_rows = discovery_rows("exa", single=single, target_hint=target_hint)
    searxng_rows = discovery_rows("searxng", single=single, target_hint=target_hint)
    mode = "single_parallel" if single else "full_parallel"
    print(f"[AI Updates] Parallel fetch: exa={len(exa_rows)} searxng={len(searxng_rows)} mode={mode}", flush=True)
    source_results = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(fetch_exa_query_rows, exa_rows, exclude_items=exclude_items, single=single): "exa",
            executor.submit(fetch_searxng_query_rows, searxng_rows, exclude_items=exclude_items, single=single): "searxng",
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                items, diagnostics = future.result()
            except Exception as exc:
                items, diagnostics = [], {"source": source, "error": f"{source}_fetch_exception", "exception": str(exc), "queries": 0, "raw_results": 0}
            source_results.append((source, items, diagnostics))
    items, diagnostics = combine_source_results(source_results, mode=mode)
    diagnostics["tool_discovery"] = dict(LAST_DISCOVERY_META)
    diagnostics["tool_group_counts"] = {
        source: meta.get("tool_group_counts", {})
        for source, meta in LAST_DISCOVERY_META.items()
    }
    diagnostics["query_mix_counts"] = {
        source: meta.get("query_mix", {})
        for source, meta in LAST_DISCOVERY_META.items()
    }
    diagnostics["parallel_fetch_seconds"] = round(time.time() - started, 2)
    print(f"[AI Updates] Parallel fetch collected unique={len(items)} raw={diagnostics.get('raw_results')} seconds={diagnostics['parallel_fetch_seconds']}", flush=True)
    return items, diagnostics

COURSE_BAD_URL_TERMS = (
    "/blog/", "/blogs/", "/news/", "/article/", "/articles/", "/review/", "/reviews/",
    "/best-", "/top-", "/tag/", "/category/", "/search", "?q=", "/press", "/events/",
    "/rankings/", "/lists/", "/list/", "/collections/", "/topic/", "/topics/",
)

COURSE_PAGE_TEXT_TERMS = (
    "course",
    "courses",
    "class",
    "classes",
    "learn",
    "learning",
    "training",
    "certificate",
    "certification",
    "short course",
    "specialization",
    "professional certificate",
    "nanodegree",
    "microcredential",
    "academy",
)

APP_STORE_DOMAINS = ("apps.apple.com", "play.google.com")

COURSE_DIRECT_PATHS = {
    "coursera.org": ("/learn/", "/specializations/", "/professional-certificates/", "/projects/"),
    "udemy.com": ("/course/",),
    "edx.org": ("/learn/", "/course/", "/certificates/professional-certificate/", "/certificates/xseries/", "/programs/"),
    "linkedin.com": ("/learning/",),
    "skillshare.com": ("/classes/", "/en/classes/"),
    "masterclass.com": ("/classes/", "/sessions/"),
    "domestika.org": ("/courses/",),
    "pluralsight.com": ("/courses/", "/paths/"),
    "futurelearn.com": ("/courses/", "/microcredentials/"),
    "udacity.com": ("/course/", "/nanodegree/"),
    "deeplearning.ai": ("/courses/", "/short-courses/"),
    "fast.ai": ("/courses/", "/course"),
    "huggingface.co": ("/learn/",),
    "learnprompting.org": ("/docs/",),
    "promptingguide.ai": ("/docs/",),
    "anthropic.com": ("/learn/", "/courses/"),
    "openai.com": ("/academy/", "/learn/", "/chatgpt/", "/research/"),
    "microsoft.com": ("/learn/", "/training/"),
    "google.com": ("/learn/",),
    "nvidia.com": ("/training/", "/courses/", "/dli/"),
    "adobe.com": ("/learn/", "/creativecloud/learn/"),
    "canva.com": ("/learn/", "/designschool/"),
    "figma.com": ("/resources/", "/academy/"),
    "superhi.com": ("/courses/",),
    "awwwards.com": ("/academy/", "/courses/"),
    "edraak.org": ("/course/", "/courses/", "/programs/"),
    "rwaq.org": ("/courses/", "/course/"),
    "doroob.com.sa": ("/individuals/", "/programs/", "/courses/"),
    "ncle.gov.sa": ("/courses/", "/training/", "/programs/"),
    "almentor.net": ("/courses/", "/course/"),
    "khamsat.com": ("/learning/",),
}

COURSE_PLATFORM_NAMES = {
    "coursera.org": "Coursera",
    "udemy.com": "Udemy",
    "edx.org": "edX",
    "linkedin.com": "LinkedIn Learning",
    "skillshare.com": "Skillshare",
    "masterclass.com": "MasterClass",
    "domestika.org": "Domestika",
    "pluralsight.com": "Pluralsight",
    "futurelearn.com": "FutureLearn",
    "udacity.com": "Udacity",
    "deeplearning.ai": "DeepLearning.AI",
    "fast.ai": "fast.ai",
    "huggingface.co": "Hugging Face",
    "learnprompting.org": "Learn Prompting",
    "promptingguide.ai": "Prompting Guide",
    "anthropic.com": "Anthropic Learn",
    "openai.com": "OpenAI",
    "microsoft.com": "Microsoft Learn",
    "google.com": "Google Learn",
    "nvidia.com": "NVIDIA Deep Learning Institute",
    "adobe.com": "Adobe Learn",
    "canva.com": "Canva Learn",
    "figma.com": "Figma Resources",
    "superhi.com": "SuperHi",
    "awwwards.com": "Awwwards Academy",
    "edraak.org": "Edraak",
    "rwaq.org": "Rwaq",
    "doroob.com.sa": "Doroob",
    "ncle.gov.sa": "National Center for e-Learning",
    "almentor.net": "Almentor",
    "khamsat.com": "Khamsat Learning",
}

ADVANCED_COURSE_TERMS = (
    "advanced",
    "advanced-level",
    "advanced level",
    "graduate-level",
    "graduate level",
    "postgraduate",
    "intermediate to advanced",
)

ENDED_COURSE_TERMS = (
    "course ended",
    "enrollment closed",
    "registration closed",
    "closed for enrollment",
    "no longer available",
    "expired",
    "archived course",
)


def domain_matches(domain: str, allowed: tuple[str, ...] | list[str] | set[str]) -> bool:
    domain = (domain or "").lower().replace("www.", "")
    return any(domain == root or domain.endswith(f".{root}") for root in allowed)


def clean_course_url(url: str = "") -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = re.sub(r"/+$", "", parsed.path or "")
    return f"{parsed.scheme}://{parsed.netloc.lower()}{path}"


def course_platform_from_url(url: str = "") -> str:
    domain = source_domain(url)
    for host, name in COURSE_PLATFORM_NAMES.items():
        if domain == host or domain.endswith(f".{host}"):
            return name
    return domain.split(".")[0].replace("-", " ").title() if domain else "Course"


def course_url_is_direct(url: str = "", title: str = "", content: str = "") -> bool:
    clean = str(url or "").lower()
    if not clean or any(term in clean for term in COURSE_BAD_URL_TERMS):
        return False
    domain = source_domain(clean)
    path = urlparse(clean).path.lower()
    for host, patterns in COURSE_DIRECT_PATHS.items():
        if domain == host or domain.endswith(f".{host}"):
            if any(pattern in path for pattern in patterns):
                return True
            evidence = f"{path} {title} {content}".lower()
            return any(term in evidence for term in COURSE_PAGE_TEXT_TERMS)
    return domain_matches(domain, COURSE_INCLUDE_DOMAINS)


def infer_course_level(text: str = "") -> str:
    """Classify only the two levels the UI is allowed to display."""
    normalized = normalized_text(text)
    beginner_terms = (
        "beginner", "beginners", "fundamental", "fundamentals", "foundation", "foundations",
        "intro", "introduction", "basics", "basic", "essentials", "getting started",
        "for everyone", "non technical", "non-technical", "no code", "no-code",
        "first course", "starter", "start learning",
    )
    intermediate_terms = (
        "intermediate", "applied", "hands-on", "hands on", "practical", "project",
        "projects", "workflow", "workflows", "automation", "productivity", "build",
        "building", "create", "creating", "professional", "workplace", "business users",
        "prompt engineering", "advanced prompt", "use cases",
    )
    if any(term in normalized for term in beginner_terms):
        return "Beginner"
    if any(term in normalized for term in intermediate_terms):
        return "Intermediate"
    return ""


def course_candidate_topic_key(item: dict) -> str:
    text = normalized_text(
        " ".join(str(item.get(key) or "") for key in ("title", "text", "summary", "content", "source_query"))
    )
    topics = [
        ("prompting", ("prompt", "prompting")),
        ("generative_ai", ("generative", "chatgpt", "llm", "model")),
        ("productivity", ("productivity", "work", "office", "copilot")),
        ("creative", ("creative", "design", "image", "video", "canva", "adobe")),
        ("responsible_ai", ("responsible", "ethics", "safety")),
        ("basics", ("beginner", "basics", "fundamentals", "introduction", "intro")),
    ]
    for topic, terms in topics:
        if any(term in text for term in terms):
            return topic
    words = [word for word in text.split() if len(word) > 3]
    return words[0] if words else "general"


def normalize_course_candidate(raw: dict, *, fetch_source: str, query: str = "") -> dict | None:
    title = clean_text(raw.get("title") or "")
    url = clean_course_url(raw.get("url") or "")
    content = clean_text(raw.get("content") or raw.get("summary") or raw.get("text") or "")
    if not title or not url:
        return None
    domain = source_domain(url)
    if not domain_matches(domain, COURSE_INCLUDE_DOMAINS):
        return None
    if not course_url_is_direct(url, title=title, content=content):
        return None
    text = f"{title} {content} {query}".lower()
    if any(term in text for term in ADVANCED_COURSE_TERMS):
        return None
    if any(term in text for term in ENDED_COURSE_TERMS):
        return None
    platform = course_platform_from_url(url)
    key = memory_url_key(url)
    published_date = clean_text(raw.get("published_date") or raw.get("published") or raw.get("date") or "")
    item = {
        "id": f"course-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}",
        "title": title,
        "text": content or f"Course from {platform} focused on practical AI skills.",
        "summary": content,
        "content": content,
        "url": url,
        "source_url": url,
        "date": published_date,
        "published": published_date,
        "published_date": published_date,
        "source": platform,
        "source_name": platform,
        "provider": platform,
        "platform": platform,
        "company": platform,
        "level": infer_course_level(text),
        "certificate": "Certificate available" if "certificate" in text or "certification" in text else "",
        "logo": f"https://www.google.com/s2/favicons?sz=128&domain={domain}",
        "provider_logo": f"https://www.google.com/s2/favicons?sz=128&domain={domain}",
        "source_logo": f"https://www.google.com/s2/favicons?sz=128&domain={domain}",
        "type": "course",
        "fetch_source": fetch_source,
        "fetch_source_label": "API: Exa",
        "source_group": fetch_source,
        "discovery_source": fetch_source,
        "source_query": query,
    }
    return item


def diversify_course_candidates(items: list[dict], limit: int) -> list[dict]:
    ranked = list(items or [])
    selected = []
    seen_ids = set()
    seen_platforms = set()
    seen_topics = set()

    def item_key(item: dict) -> str:
        key = memory_url_key(item.get("url") or "")
        return key or str(id(item))

    def platform_key(item: dict) -> str:
        return normalized_text(item.get("platform") or item.get("provider") or source_domain(item.get("url") or ""))

    def add(item: dict | None) -> bool:
        if item is None:
            return False
        key = item_key(item)
        if key in seen_ids:
            return False
        selected.append(item)
        seen_ids.add(key)
        platform = platform_key(item)
        if platform:
            seen_platforms.add(platform)
        topic = course_candidate_topic_key(item)
        if topic:
            seen_topics.add(topic)
        return True

    def first_for_level(level: str, *, prefer_new_platform: bool = True, prefer_new_topic: bool = True) -> dict | None:
        for item in ranked:
            if item_key(item) in seen_ids or item.get("level") != level:
                continue
            platform = platform_key(item)
            if prefer_new_platform and platform in seen_platforms:
                continue
            topic = course_candidate_topic_key(item)
            if prefer_new_topic and topic in seen_topics:
                continue
            return item
        return None

    # Put both visible levels into the candidate pool early so GPT can actually pick them.
    add(
        first_for_level("Beginner", prefer_new_platform=True, prefer_new_topic=True)
        or first_for_level("Beginner", prefer_new_platform=True, prefer_new_topic=False)
        or first_for_level("Beginner", prefer_new_platform=False, prefer_new_topic=False)
    )
    add(
        first_for_level("Intermediate", prefer_new_platform=True, prefer_new_topic=True)
        or first_for_level("Intermediate", prefer_new_platform=True, prefer_new_topic=False)
        or first_for_level("Intermediate", prefer_new_platform=False, prefer_new_topic=False)
    )

    for item in ranked:
        if len(selected) >= limit:
            break
        platform = platform_key(item)
        topic = course_candidate_topic_key(item)
        if platform and platform not in seen_platforms and topic and topic not in seen_topics:
            add(item)

    for item in ranked:
        if len(selected) >= limit:
            break
        platform = platform_key(item)
        if platform and platform not in seen_platforms:
            add(item)

    for item in ranked:
        if len(selected) >= limit:
            break
        add(item)

    for index, item in enumerate(selected[:limit], start=1):
        item["position"] = index
    return selected[:limit]


def fetch_exa_course_query(query: str, max_results: int = 10) -> list[dict]:
    if not EXA_API_KEY:
        print("[AI Updates] Exa course skipped: missing EXA_API_KEY", flush=True)
        return []
    payload = {
        "query": query,
        "includeDomains": list(COURSE_QUERY.get("includeDomains") or COURSE_INCLUDE_DOMAINS),
        "startPublishedDate": COURSE_QUERY.get("startPublishedDate") or "2026-01-01",
        "numResults": max(1, max_results),
        "type": COURSE_QUERY.get("type") or "neural",
        "contents": {"text": True, "highlights": True},
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY}
    try:
        response = requests.post("https://api.exa.ai/search", headers=headers, json=payload, timeout=AI_UPDATES_EXA_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f"[AI Updates] Exa course failed: {exc}", flush=True)
        return []

    output = []
    for result in data.get("results") or []:
        highlights = result.get("highlights") or []
        snippet = " ".join(str(part or "") for part in highlights[:3]).strip()
        item = normalize_course_candidate(
            {
                "title": result.get("title") or "",
                "url": result.get("url") or "",
                "content": result.get("text") or snippet,
                "published_date": result.get("publishedDate") or "",
            },
            fetch_source="exa_course_search",
            query=query,
        )
        if item:
            output.append(item)
    print(f"[AI Updates] Exa course query collected {len(output)}/{len(data.get('results') or [])}: {query[:72]}", flush=True)
    return output


def fetch_course_candidates(max_results: int = 10) -> list[dict]:
    """Fetch AI course candidates only from configured trusted course domains."""
    """Fetch course cards from Exa only using the configured includeDomains query."""
    query_bank = list(COURSE_QUERY_VARIANTS or ([COURSE_QUERY.get("query")] if COURSE_QUERY.get("query") else []))
    if not query_bank:
        print("[AI Updates] Exa course skipped: no course queries configured", flush=True)
        return []
    query_limit = max(1, min(len(query_bank), AI_UPDATES_COURSE_EXA_QUERY_LIMIT))
    per_query = max(3, min(max_results, AI_UPDATES_COURSE_EXA_RESULTS_PER_QUERY))
    output = []
    seen_urls = set()
    with ThreadPoolExecutor(max_workers=min(query_limit, 4)) as executor:
        futures = {
            executor.submit(fetch_exa_course_query, query, per_query): query
            for query in query_bank[:query_limit]
        }
        for future in as_completed(futures):
            for item in future.result() or []:
                key = memory_url_key(item.get("url") or "")
                if not key or key in seen_urls:
                    continue
                seen_urls.add(key)
                output.append(item)
    print(f"[AI Updates] Exa course collected unique={len(output)} queries={query_limit}", flush=True)
    return diversify_course_candidates(output, max_results)


TMDB_AI_KEYWORD_IDS = (310,)


def fetch_movie_candidates(target_count: int = 8) -> list[dict]:
    """Fetch AI-themed movie candidates with posters directly from TMDb."""
    if not TMDB_API_KEY:
        print("[AI Updates] TMDb movie skipped: missing TMDB_API_KEY", flush=True)
        return []
    output = []
    seen = set()
    pages = max(1, min(3, (target_count // 20) + 1))
    for keyword_id in TMDB_AI_KEYWORD_IDS:
        for page in range(1, pages + 1):
            if len(output) >= target_count:
                break
            try:
                response = requests.get(
                    "https://api.themoviedb.org/3/discover/movie",
                    params={
                        "api_key": TMDB_API_KEY,
                        "with_keywords": keyword_id,
                        "sort_by": "popularity.desc",
                        "include_adult": "false",
                        "page": page,
                    },
                    timeout=12,
                )
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                print(f"[AI Updates] TMDb movie failed: {exc}", flush=True)
                continue
            for result in data.get("results") or []:
                movie_id = result.get("id")
                if not movie_id or movie_id in seen:
                    continue
                seen.add(movie_id)
                poster_path = result.get("poster_path") or ""
                poster = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
                url = f"https://www.themoviedb.org/movie/{movie_id}"
                overview = clean_text(result.get("overview") or "")
                output.append({
                    "id": f"movie-{movie_id}",
                    "title": clean_text(result.get("title") or result.get("original_title") or ""),
                    "text": overview,
                    "summary": overview,
                    "content": overview,
                    "overview": overview,
                    "url": url,
                    "source_url": url,
                    "source": "TMDb",
                    "poster": poster,
                    "rating": result.get("vote_average"),
                    "vote_count": result.get("vote_count"),
                    "popularity": result.get("popularity"),
                    "published": result.get("release_date") or "",
                    "date": result.get("release_date") or "",
                    "type": "movie",
                    "fetch_source": "tmdb_movie_search",
                    "discovery_source": "tmdb_movie_search",
                    "position": len(output) + 1,
                })
                if len(output) >= target_count:
                    break
    print(f"[AI Updates] TMDb movie collected {len(output)}", flush=True)
    return output[:target_count]
