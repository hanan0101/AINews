# This file is part of the AI newsletter system.
"""Tool-aware discovery, validation, registry, and official-site helpers.

This module was split from fetchers.py so tool discovery can be maintained
separately from news/course/movie fetching.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

import requests

from backend.config.settings import (
    AI_UPDATES_EXA_TIMEOUT,
    AI_UPDATES_LOOKBACK_DAYS,
    AI_UPDATES_SEARXNG_CATEGORIES,
    AI_UPDATES_SEARXNG_TIME_RANGE,
    AI_UPDATES_SEARXNG_TIMEOUT,
    AI_UPDATES_TOOL_CACHE_MAX_RECORDS,
    AI_UPDATES_TOOL_CACHE_REFRESH_DAYS,
    AI_UPDATES_TOOL_DISCOVERY_ENABLED,
    AI_UPDATES_TOOL_DISCOVERY_RESULTS,
    EXA_API_KEY,
    MONTHLY_TOOLS_FILE,
    SEARXNG_URL,
    clean_text,
    env_int,
    load_json,
    memory_url_key,
    normalized_text,
    parse_result_datetime,
    safe_write_json,
    source_domain,
    utc_now,
)
from backend.logging.pipeline_logging import file_status, log_event, timed_stage
from backend.pipeline.modeling.gemini_client import GEMINI_FLASH_MODEL, generate_json, gemini_available
from backend.pipeline.tool_discovery.official_sites import (
    apply_default_official_sites,
    auto_detect_official_site,
    canonical_official_site,
    enrich_tools_with_official_sites,
    normalize_official_site_status,
    official_tool_site,
)
from backend.pipeline.tool_discovery.queries import (
    AUTO_EXPAND_AGGREGATOR_EXA_QUERIES,
    AUTO_EXPAND_GROWTH_EXA_QUERIES,
    AUTO_EXPAND_SEARXNG_QUERIES,
    BUSINESS_ONLY_TERMS,
    LIVE_TOOL_DISCOVERY_ROWS,
    SUCCESSFUL_TOOL_EXA_QUERIES,
    SUCCESSFUL_TOOL_SEARXNG_QUERIES,
    ensure_ai_scope,
    search_url,
    strict_searxng_ai_product_query,
    text_has_any,
    tool_release_query,
)


_tool_model_available = gemini_available()
AI_UPDATES_TOOL_SITE_DISCOVERY_LIMIT = env_int("AI_UPDATES_TOOL_SITE_DISCOVERY_LIMIT", "24")
_tool_record_allowed_model_cache: dict[str, tuple[bool, str]] = {}
_TOOL_CACHE_MAINTAINED_FOR = ""


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

# ============================================
# SECTION 1: TOOL DISCOVERY FROM WEB


# WHAT: Fetches market pages for monthly AI tool discovery.
# HOW: Uses Exa search API.
# INPUT: No parameters.
# OUTPUT: List of compact page dictionaries.
def fetch_exa_tool_discovery_pages() -> list[dict]:
    if not EXA_API_KEY:
        return []
    headers = {"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY}
    pages = []
    per_query = max(1, AI_UPDATES_TOOL_DISCOVERY_RESULTS)
    for row in LIVE_TOOL_DISCOVERY_ROWS:
        payload = {
            "query": ensure_ai_scope(row["query"]),
            "numResults": per_query,
            "type": "neural",
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


# WHAT: Fetches supplemental market pages for monthly AI tool discovery.
# HOW: Uses SearXNG JSON search.
# INPUT: No parameters.
# OUTPUT: List of compact page dictionaries.
def fetch_searxng_tool_discovery_pages() -> list[dict]:
    endpoint = search_url()
    pages = []
    per_query = max(1, min(4, AI_UPDATES_TOOL_DISCOVERY_RESULTS))
    for row in LIVE_TOOL_DISCOVERY_ROWS:
        params = {
            "q": strict_searxng_ai_product_query(row["query"]),
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


# WHAT: Extracts AI tool records from discovered market pages.
# HOW: Uses the Gemini tool discovery model over Exa/SearXNG page snippets.
# INPUT: pages list of dictionaries.
# OUTPUT: Deduplicated list of tool records.
def extract_live_tool_records(pages: list[dict]) -> list[dict]:
    if not pages or not _tool_model_available:
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
{{"tools":[{{"tool":str,"company":str,"group":str,"sector":str,"sector_hint":str,"tool_type":str,"official_site":str,"official_site_reason":str,"cultural_applications":[str],"reason":str}}]}}

Rules:
- Keep only actual AI products or tools, not article titles, reports, categories, or websites.
- Prefer tools with broad user adoption, visible community interest, or clear creative/culture/daily/work use.
- Balance roughly half general_market and half culture_creative when evidence allows.
- group must be "general_market" or "culture_creative".
- tool_type must be "general" when it clearly serves 3+ use cases; otherwise "specialized".
- sector must be one of: {", ".join(TOOL_DISCOVERY_SECTORS)}.
- sector_hint must be one of: {", ".join(TOOL_DISCOVERY_HINTS)}.
- Reject CRM, customer support, sales, ads, marketing automation, finance, legal, cybersecurity, HR, developer-only infrastructure, listicles, and local/narrow apps.
- official_site should be the product/company official blog, news, newsroom, changelog, release notes, research, or docs update path when confidently known; otherwise "".
- official_site must be a domain/path only, without https://.
- Limit to 24 tools. Use English product/company names.
""".strip()
    try:
        data = generate_json(prompt, compact, model=GEMINI_FLASH_MODEL)
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


# WHAT: Runs live monthly tool discovery from Exa and SearXNG pages.
# HOW: Uses Exa, SearXNG, and the Gemini extraction model.
# INPUT: No parameters.
# OUTPUT: List of deduplicated tool records.
def discover_tool_names_live() -> list[dict]:
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
    print(f"[AI Updates] monthly live tool discovery pages={len(unique_pages)} tools={len(records)}", flush=True)
    return records


# WHAT: Discovers globally successful AI tools from market-success pages.
# HOW: Uses Exa, SearXNG, and the Gemini extraction model.
# INPUT: No parameters.
# OUTPUT: Deduplicated list of successful tool records.
def fetch_successful_tools() -> list[dict]:
    if not AI_UPDATES_TOOL_DISCOVERY_ENABLED or not _tool_model_available:
        return []
    pages: list[dict] = []
    if EXA_API_KEY:
        headers = {"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY}
        for query in SUCCESSFUL_TOOL_EXA_QUERIES:
            payload = {
                "query": ensure_ai_scope(query),
                "numResults": max(1, AI_UPDATES_TOOL_DISCOVERY_RESULTS),
                "type": "neural",
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
                    "query_group": "successful_global_tools",
                    "query": query,
                    "source": "exa_successful_tools",
                })
    endpoint = search_url()
    for query in SUCCESSFUL_TOOL_SEARXNG_QUERIES:
        params = {
            "q": strict_searxng_ai_product_query(query),
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
        for result in list(data.get("results") or [])[: max(1, min(4, AI_UPDATES_TOOL_DISCOVERY_RESULTS))]:
            pages.append({
                "title": clean_text(result.get("title") or "")[:220],
                "content": clean_text(result.get("content") or result.get("snippet") or "")[:900],
                "url": result.get("url") or "",
                "source_domain": source_domain(result.get("url") or ""),
                "query_group": "successful_global_tools",
                "query": query,
                "source": "searxng_successful_tools",
            })
    return extract_live_tool_records(pages)


# ============================================
# SECTION 2: TOOL VALIDATION AND SCORING


# WHAT: Returns a normalized group for a tool record.
# HOW: Uses JSON record fields group and sector_hint.
# INPUT: item dictionary.
# OUTPUT: "general_market" or "culture_creative".
def tool_group(item: dict) -> str:
    group = str((item or {}).get("group") or "").strip()
    if group in {"general_market", "culture_creative"}:
        return group
    hint = str((item or {}).get("sector_hint") or "").lower()
    return "general_market" if hint == "general_market" else "culture_creative"


# WHAT: Builds the stable identity key for one tool record.
# HOW: Uses normalized JSON fields tool/company.
# INPUT: item dictionary or string.
# OUTPUT: Normalized key string.
def tool_record_key(item: dict | str) -> str:
    if isinstance(item, str):
        return normalized_text(item)
    if not isinstance(item, dict):
        return ""
    return normalized_text(item.get("tool") or item.get("company") or "")


# WHAT: Checks whether a text contains any blocked business-only terms.
# HOW: Uses local tuple of business-only terms.
# INPUT: text and term list.
# OUTPUT: Boolean.
def normalize_tool_record(raw: dict | str, *, source: str = "") -> dict:
    if isinstance(raw, str):
        item = {"tool": raw}
    elif isinstance(raw, dict):
        item = dict(raw)
    else:
        item = {}
    tool = clean_text(item.get("tool") or item.get("name") or item.get("product") or "")
    company = clean_text(item.get("company") or item.get("owner") or tool)
    group = item.get("group") if item.get("group") in {"general_market", "culture_creative"} else ""
    sector_hint = clean_text(item.get("sector_hint") or "")
    if not group:
        group = "general_market" if sector_hint == "general_market" else "culture_creative"
    return {
        "tool": tool,
        "company": company,
        "group": group,
        "sector": clean_text(item.get("sector") or item.get("primary_sector") or ""),
        "primary_sector": clean_text(item.get("primary_sector") or item.get("sector") or ""),
        "sector_hint": sector_hint,
        "tool_type": clean_text(item.get("tool_type") or ("general" if group == "general_market" else "specialized")),
        "cultural_applications": item.get("cultural_applications") if isinstance(item.get("cultural_applications"), list) else [],
        "secondary_sectors": item.get("secondary_sectors") if isinstance(item.get("secondary_sectors"), list) else [],
        "reason": clean_text(item.get("reason") or item.get("success_evidence") or item.get("acceptance_evidence") or ""),
        "mention_count": int(item.get("mention_count") or 1),
        "best_rank": item.get("best_rank"),
        "popularity_score": int(item.get("popularity_score") or 0),
        "sources": item.get("sources") if isinstance(item.get("sources"), list) else [],
        "official_site": canonical_official_site(item.get("official_site") or ""),
        "official_site_reason": clean_text(item.get("official_site_reason") or ""),
        "official_site_verified": bool(item.get("official_site_verified") or False),
        "official_site_status": normalize_official_site_status(
            item.get("official_site_status") or item.get("status") or "",
            site=item.get("official_site") or "",
            verified=bool(item.get("official_site_verified") or False),
        ),
        "sector_classification_source": item.get("sector_classification_source") or item.get("source") or source,
        "updated": item.get("updated") or "",
        "discovery_date": item.get("discovery_date") or "",
        "status": clean_text(item.get("status") or ""),
        "inactive_reason": clean_text(item.get("inactive_reason") or ""),
        "updates_last_60_days": item.get("updates_last_60_days"),
        "last_update_seen": item.get("last_update_seen") or item.get("last_news_seen") or "",
        "source": item.get("source") or source or item.get("sector_classification_source") or "",
    }


# WHAT: Asks the discovery model whether a tool belongs in the cache.
# HOW: Uses Gemini over one normalized JSON record.
# INPUT: item dictionary.
# OUTPUT: Tuple of allowed boolean and reason string.
def model_allows_tool_record(item: dict) -> tuple[bool, str]:
    if not _tool_model_available:
        return True, "model_unavailable"
    tool = clean_text(item.get("tool") or "")
    company = clean_text(item.get("company") or "")
    cache_key = normalized_text(f"{tool} {company}")
    if cache_key in _tool_record_allowed_model_cache:
        return _tool_record_allowed_model_cache[cache_key]
    prompt = """
You are validating whether an AI tool should be kept in a global AI newsletter tool cache.

Return JSON only:
{"allow":true|false,"reason":str}

Allow only if:
- It is a real, independent AI product/tool or a major AI product from a major company.
- It is globally relevant or broadly useful for creators, knowledge workers, culture, learning, daily life, or productivity.
- It is likely to have public product updates that can be tracked.

Reject if:
- Local/regional-only, unclear/undocumented, inactive, or no public product site.
- Not an AI tool, hardware, auto parts, medical-only, maritime-only, legal/finance/admin-only, or narrow enterprise infrastructure.
- Merely a feature inside another product unless it is a major named product with public updates.
- Only a GitHub repo, app-store page, subdomain app, directory listing, or press mention.
""".strip()
    payload = {
        "tool": tool,
        "company": company,
        "group": item.get("group") or "",
        "sector": item.get("sector") or "",
        "sector_hint": item.get("sector_hint") or "",
        "tool_type": item.get("tool_type") or "",
        "reason": item.get("reason") or "",
        "official_site": item.get("official_site") or "",
        "source": item.get("source") or item.get("sector_classification_source") or "",
        "popularity_score": item.get("popularity_score") or 0,
        "mention_count": item.get("mention_count") or 0,
    }
    try:
        data = generate_json(prompt, payload, model=GEMINI_FLASH_MODEL)
        allowed = bool(data.get("allow"))
        reason = clean_text(data.get("reason") or "")
    except Exception as exc:
        allowed = True
        reason = f"model_error:{type(exc).__name__}"
    result = (allowed, reason or "model_decision")
    _tool_record_allowed_model_cache[cache_key] = result
    return result


# WHAT: Applies rule and model gates to decide whether a tool record is allowed.
# HOW: Uses local rules and optionally Gemini validation.
# INPUT: item dictionary.
# OUTPUT: Boolean allowed decision.
def tool_record_allowed(item: dict) -> bool:
    tool = clean_text(item.get("tool") or "")
    if len(tool) < 3:
        item["tool_record_allowed_reason"] = "name_too_short"
        return False
    text = " ".join(
        str(item.get(key) or "")
        for key in ("tool", "company", "group", "sector", "sector_hint", "tool_type", "source")
    ).lower()
    if text_has_any(text, BUSINESS_ONLY_TERMS):
        item["tool_record_allowed_reason"] = "business_only_terms"
        return False
    allowed, reason = model_allows_tool_record(item)
    item["tool_record_allowed_reason"] = reason
    item["tool_record_allowed_source"] = "model" if _tool_model_available else "rules"
    return allowed


# WHAT: Normalizes and merges duplicate tool records.
# HOW: Uses JSON records and local normalized keys.
# INPUT: records list and optional source label.
# OUTPUT: Tuple of merged records and duplicate count.
def dedupe_tool_records(records: list[dict | str], *, source: str = "") -> tuple[list[dict], int]:
    merged: dict[str, dict] = {}
    duplicates = 0
    for raw in records or []:
        item = normalize_tool_record(raw, source=source)
        if not clean_text(item.get("tool") or ""):
            continue
        if item.get("official_site"):
            item["official_site_status"] = normalize_official_site_status(
                item.get("official_site_status") or item.get("status") or "",
                site=item.get("official_site") or "",
                verified=bool(item.get("official_site_verified")),
            )
        if source != "monthly_tools_site" and not tool_record_allowed(item):
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
            "official_site",
            "official_site_reason",
            "official_site_status",
            "sector_classification_source",
            "updated",
            "discovery_date",
            "status",
            "inactive_reason",
            "updates_last_60_days",
            "last_update_seen",
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
        existing["popularity_score"] = max(int(existing.get("popularity_score") or 0), int(item.get("popularity_score") or 0))
        existing["official_site_verified"] = bool(existing.get("official_site_verified") or item.get("official_site_verified"))
        if existing.get("official_site"):
            existing["official_site_status"] = normalize_official_site_status(
                existing.get("official_site_status") or "",
                site=existing.get("official_site") or "",
                verified=bool(existing.get("official_site_verified")),
            )
    output = sorted(
        merged.values(),
        key=lambda item: (int(item.get("popularity_score") or 0), 0 if tool_group(item) == "general_market" else -1),
        reverse=True,
    )
    return output[: max(1, AI_UPDATES_TOOL_CACHE_MAX_RECORDS)], duplicates


# WHAT: Keeps discovered tools balanced between general and cultural groups.
# HOW: Uses JSON field group and local scoring order.
# INPUT: tools list and limit integer.
# OUTPUT: Balanced list of tool records.
def cap_tool_groups(tools: list[dict], limit: int) -> list[dict]:
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


# ============================================
# SECTION 3: SAVE TOOLS TO JSON


# WHAT: Checks if the cached tool registry is stale.
# HOW: Uses JSON timestamp fields and configured refresh days.
# INPUT: payload dictionary.
# OUTPUT: Boolean staleness decision.
def tool_cache_is_stale(payload: dict) -> bool:
    updated = parse_result_datetime((payload or {}).get("updated") or (payload or {}).get("last_updated"))
    if updated is None:
        return True
    age_days = (utc_now() - updated).days
    return age_days >= max(1, AI_UPDATES_TOOL_CACHE_REFRESH_DAYS)


# WHAT: Maintains the monthly tool registry file.
# HOW: Uses Exa/SearXNG discovery, Gemini validation, and monthly tools JSON.
# INPUT: force_refresh boolean keyword argument.
# OUTPUT: None; writes JSON and logs maintenance.
def maintain_monthly_tool_files(*, force_refresh: bool = False) -> None:
    global _TOOL_CACHE_MAINTAINED_FOR
    today = utc_now().date().isoformat()
    if _TOOL_CACHE_MAINTAINED_FOR == today and not force_refresh:
        log_event("tool_files.maintenance_skipped", reason="already_maintained_today", registry=file_status(MONTHLY_TOOLS_FILE))
        return
    _TOOL_CACHE_MAINTAINED_FOR = today
    monthly = load_json(MONTHLY_TOOLS_FILE, {"tool_records": [], "tools": []})
    monthly_stale = force_refresh or tool_cache_is_stale(monthly)
    log_event("tool_files.maintenance_started", force_refresh=bool(force_refresh), monthly_stale=bool(monthly_stale), registry=file_status(MONTHLY_TOOLS_FILE))
    if not monthly_stale:
        log_event(
            "tool_files.maintenance_finished",
            registry_records=len(monthly.get("tool_records") or []),
            registry_written=False,
            reason="registry_fresh",
            registry=file_status(MONTHLY_TOOLS_FILE),
        )
        return
    with timed_stage("tool_files.live_discovery", enabled=bool(monthly_stale)):
        live_monthly_records = discover_tool_names_live() if monthly_stale else []
    with timed_stage("tool_files.successful_discovery", enabled=bool(monthly_stale)):
        successful_live_records = fetch_successful_tools() if monthly_stale else []
    existing_registry_records = monthly.get("tool_records") or monthly.get("tools") or []
    monthly_records, monthly_dupes = dedupe_tool_records([*live_monthly_records, *successful_live_records, *existing_registry_records], source="monthly_tools_site")
    auto_expansion_due = bool(monthly_stale) and tool_auto_expansion_is_due(monthly, force_refresh=force_refresh)
    with timed_stage("tool_files.auto_expansion", enabled=bool(auto_expansion_due)):
        auto_expanded_records, auto_expansion_meta = auto_expand_tool_list(monthly_records, force_refresh=force_refresh) if auto_expansion_due else ([], monthly.get("auto_expansion") or {"ran": False})
    if auto_expanded_records:
        monthly_records, monthly_dupes_after_auto = dedupe_tool_records([*auto_expanded_records, *monthly_records], source="monthly_tools_site")
        monthly_dupes += monthly_dupes_after_auto
    monthly_records = mark_inactive_auto_tools(monthly_records)
    monthly_records = apply_default_official_sites(monthly_records)
    monthly_needs_write = (
        monthly_stale
        or monthly_dupes > 0
        or len(live_monthly_records) > 0
        or len(successful_live_records) > 0
        or len(auto_expanded_records) > 0
        or auto_expansion_due
        or not MONTHLY_TOOLS_FILE.exists()
    )
    if monthly_records and monthly_needs_write:
        safe_write_json(
            MONTHLY_TOOLS_FILE,
            {
                "schema": "monthly_tools_site_v1",
                "updated": today,
                "live_discovery": {
                    "enabled": bool(AI_UPDATES_TOOL_DISCOVERY_ENABLED),
                    "ran": bool(live_monthly_records or successful_live_records),
                    "added_or_refreshed": len(live_monthly_records) + len(successful_live_records),
                    "refresh_days": AI_UPDATES_TOOL_CACHE_REFRESH_DAYS,
                    "registry": "monthly_tools-site.json",
                },
                "tools": [item.get("tool") for item in monthly_records if item.get("tool")],
                "auto_expansion": {
                    **(monthly.get("auto_expansion") or {}),
                    **(auto_expansion_meta or {}),
                    "updated": today if auto_expansion_due else ((monthly.get("auto_expansion") or {}).get("updated") or ""),
                    "added": len(auto_expanded_records or []),
                    "refresh_days": 7,
                    "inactive_after_days": 60,
                },
                "tool_records": monthly_records,
            },
        )
    log_event(
        "tool_files.maintenance_finished",
        registry_records=len(monthly_records or []),
        registry_dupes=monthly_dupes,
        registry_written=bool(monthly_records and monthly_needs_write),
        live_monthly_records=len(live_monthly_records or []),
        successful_live_records=len(successful_live_records or []),
        auto_expanded_records=len(auto_expanded_records or []),
        registry=file_status(MONTHLY_TOOLS_FILE),
    )


# ============================================
# SECTION 4: REFRESH AND MAINTENANCE


# AUTO-EXPANSION schedule helper: this keeps the new expansion layer weekly
# without changing the existing monthly popular-tools discovery cadence.
def tool_auto_expansion_is_due(payload: dict, *, force_refresh: bool = False) -> bool:
    """Return True when the automatic tool expansion should run this week."""
    if force_refresh:
        return True
    updated = parse_result_datetime(((payload or {}).get("auto_expansion") or {}).get("updated") or "")
    if updated is None:
        return True
    return (utc_now() - updated).days >= 7


# AUTO-EXPANSION: discover new active AI tools from aggregators, funding/growth
# signals, and SearXNG. This function only adds new accepted tools to
# monthly_tools-site.json data; it does not change the existing popular-tools logic.
def auto_expand_tool_list(existing_records: list[dict] | None = None, *, force_refresh: bool = False) -> tuple[list[dict], dict]:
    """Find new globally active AI tools and return records ready to merge."""
    if not AI_UPDATES_TOOL_DISCOVERY_ENABLED or not _tool_model_available:
        return [], {"ran": False, "reason": "disabled_or_model_unavailable"}

    existing_keys = {
        tool_record_key(item)
        for item in (existing_records or [])
        if tool_record_key(item)
    }
    cutoff_date = (utc_now() - timedelta(days=max(7, AI_UPDATES_LOOKBACK_DAYS))).date().isoformat()
    pages: list[dict] = []
    errors: list[str] = []

    # SOURCE 1 and 2 Exa fetch: aggregators and funding/growth queries share
    # the same Exa configuration requested for auto expansion.
    def fetch_auto_expand_exa(query: str, source_group: str) -> list[dict]:
        if not EXA_API_KEY:
            return []
        headers = {"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY}
        payload = {
            "query": ensure_ai_scope(query),
            "numResults": 10,
            "type": "neural",
            "category": "news",
            "startPublishedDate": cutoff_date,
            "contents": {"text": True, "highlights": True},
        }
        try:
            response = requests.post("https://api.exa.ai/search", headers=headers, json=payload, timeout=AI_UPDATES_EXA_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            errors.append(f"exa:{source_group}:{type(exc).__name__}")
            return []
        output = []
        for result in data.get("results") or []:
            highlights = result.get("highlights") or []
            output.append({
                "title": clean_text(result.get("title") or "")[:220],
                "content": clean_text(result.get("text") or " ".join(str(part or "") for part in highlights[:3]))[:900],
                "url": result.get("url") or "",
                "source_domain": source_domain(result.get("url") or ""),
                "query": query,
                "source": "exa_auto_expand",
                "source_group": source_group,
            })
        return output

    # SOURCE 3 SearXNG fetch: strict AND queries run with a month window to
    # catch active new tools while avoiding loose keyword noise.
    def fetch_auto_expand_searxng(query: str) -> list[dict]:
        params = {
            # Automatic expansion uses the same guard so weekly discovery
            # cannot admit non-product news through a loose source query.
            "q": strict_searxng_ai_product_query(query),
            "format": "json",
            "language": "en",
            "engines": "google,bing,brave",
            "time_range": "month",
            "categories": AI_UPDATES_SEARXNG_CATEGORIES,
            "pageno": 1,
        }
        try:
            response = requests.get(search_url(), params=params, timeout=AI_UPDATES_SEARXNG_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            errors.append(f"searxng:auto_expand:{type(exc).__name__}")
            return []
        output = []
        for result in list(data.get("results") or [])[:10]:
            output.append({
                "title": clean_text(result.get("title") or "")[:220],
                "content": clean_text(result.get("content") or result.get("snippet") or "")[:900],
                "url": result.get("url") or "",
                "source_domain": source_domain(result.get("url") or ""),
                "query": query,
                "source": "searxng_auto_expand",
                "source_group": "searxng_parallel_discovery",
            })
        return output

    # Parallel collection: each source can fail independently without blocking
    # the other sources, keeping the weekly expansion resilient.
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = []
        for query in AUTO_EXPAND_AGGREGATOR_EXA_QUERIES:
            futures.append(executor.submit(fetch_auto_expand_exa, query, "aggregators"))
        for query in AUTO_EXPAND_GROWTH_EXA_QUERIES:
            futures.append(executor.submit(fetch_auto_expand_exa, query, "funding_growth"))
        for query in AUTO_EXPAND_SEARXNG_QUERIES:
            futures.append(executor.submit(fetch_auto_expand_searxng, query))
        for future in as_completed(futures):
            try:
                pages.extend(future.result() or [])
            except Exception as exc:
                errors.append(f"auto_expand_future:{type(exc).__name__}")

    seen = set()
    unique_pages = []
    for page in pages:
        key = memory_url_key(page.get("url") or "") or normalized_text(page.get("title") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique_pages.append(page)

    compact = [
        {
            "title": page.get("title") or "",
            "content": page.get("content") or "",
            "url": page.get("url") or "",
            "source_domain": page.get("source_domain") or "",
            "source_group": page.get("source_group") or "",
            "query": page.get("query") or "",
        }
        for page in unique_pages[:60]
        if page.get("title") or page.get("content")
    ]
    if not compact:
        return [], {"ran": True, "pages": 0, "accepted": 0, "errors": errors}

    # Acceptance model: only tools with funding, large global user base, major
    # AI/tech coverage, or viral global growth can enter the active tool list.
    prompt = f"""
Extract NEW active AI tools from these discovery results.

Return JSON only:
{{"tools":[{{"tool":str,"company":str,"group":str,"sector":str,"sector_hint":str,"tool_type":str,"official_site":str,"reason":str,"acceptance_evidence":str}}]}}

Acceptance criteria:
- Accept a tool if it meets at least one: documented Series A or higher funding, documented 1M+ global users, mentioned in a major AI newsletter or tech report this week, or showing viral/fast global growth.

Rejection criteria:
- Reject local/regional-only tools, one-country or one-language-market tools, beta/invite-only tools, tools under 6 months in market, tools without company/documentation, and tools already listed here: {", ".join(sorted(existing_keys)[:120])}.

Output rules:
- Keep only actual AI products/tools, not articles, categories, websites, reports, services, or generic company initiatives.
- group must be "general_market" or "culture_creative".
- tool_type must be "general" when it serves 3+ use cases; otherwise "specialized".
- sector must be one of: {", ".join(TOOL_DISCOVERY_SECTORS)}.
- sector_hint must be one of: {", ".join(TOOL_DISCOVERY_HINTS)}.
- official_site should be an official blog/news/newsroom/changelog/releases/updates path when confidently known; otherwise "".
- official_site must be domain/path only, without https://.
- Limit to 20 high-confidence tools.
""".strip()
    try:
        data = generate_json(prompt, compact, model=GEMINI_FLASH_MODEL)
    except Exception as exc:
        errors.append(f"model:auto_expand:{type(exc).__name__}")
        return [], {"ran": True, "pages": len(compact), "accepted": 0, "errors": errors}

    today = utc_now().date().isoformat()
    accepted: list[dict] = []
    for raw in data.get("tools") or []:
        item = normalize_tool_record(raw, source="auto_discovered")
        key = tool_record_key(item)
        if not key or key in existing_keys or not tool_record_allowed(item):
            continue

        # Official-site detection: every new accepted tool gets a best-effort
        # verified update path before entering future news search.
        detection = auto_detect_official_site(item.get("tool") or "", item.get("company") or "")
        detected_site = canonical_official_site(detection.get("official_site") or "")
        item["source"] = "auto_discovered"
        item["sources"] = list(dict.fromkeys([*(item.get("sources") or []), "auto_discovered", "exa", "searxng"]))
        item["popularity_score"] = max(60, int(item.get("popularity_score") or 0))
        item["mention_count"] = max(1, int(item.get("mention_count") or 0))
        item["discovery_date"] = today
        item["updated"] = today
        item["status"] = "active"
        item["sector_classification_source"] = "gpt_auto_expand_tool_list"
        item["reason"] = clean_text(raw.get("acceptance_evidence") or raw.get("reason") or item.get("reason") or "")
        if detected_site:
            item["official_site"] = detected_site
            item["official_site_verified"] = bool(detection.get("official_site_verified"))
            item["official_site_status"] = detection.get("official_site_status") or "active"
            item["official_site_reason"] = detection.get("official_site_reason") or "auto_detected_active_update_path"
        accepted.append(item)
        existing_keys.add(key)

    records, _ = dedupe_tool_records(accepted, source="auto_discovered")
    print(
        f"[AI Updates] auto tool expansion pages={len(compact)} accepted={len(records)} errors={len(errors)}",
        flush=True,
    )
    return records, {
        "ran": True,
        "updated": today,
        "pages": len(compact),
        "accepted": len(records),
        "source_counts": dict(Counter(page.get("source_group") or "unknown" for page in unique_pages)),
        "errors": errors[:20],
        "refresh_days": 7,
        "inactive_after_days": 60,
    }



# WHAT: Marks auto-discovered tools inactive after a quiet 60-day window.
# HOW: Uses JSON metadata fields updates_last_60_days and last_update_seen.
# INPUT: records list.
# OUTPUT: Updated records list.
def mark_inactive_auto_tools(records: list[dict]) -> list[dict]:
    cutoff = utc_now() - timedelta(days=60)
    output = []
    for item in records or []:
        row = dict(item)
        updates_60 = row.get("updates_last_60_days")
        last_seen = parse_result_datetime(row.get("last_update_seen") or row.get("last_news_seen") or "")
        if row.get("source") == "auto_discovered" and updates_60 == 0 and last_seen and last_seen < cutoff:
            row["status"] = "inactive"
            row["inactive_reason"] = "0 updates for 60 consecutive days"
        output.append(row)
    return output


# WHAT: Builds Exa and SearXNG query rows for cached tools.
# HOW: Uses JSON monthly tool records and official-site cache.
# INPUT: tools list.
# OUTPUT: Dictionary with exa and searxng query rows.
def build_tool_queries(tools: list[dict]) -> dict:
    exa_rows = []
    searxng_rows = []
    for item in tools or []:
        tool = clean_text((item or {}).get("tool") or "")
        company = clean_text((item or {}).get("company") or "")
        name = tool or company
        if not name:
            continue
        group = tool_group(item)
        tool_type = (item or {}).get("tool_type") or ("general" if group == "general_market" else "specialized")
        site = canonical_official_site((item or {}).get("official_site") or "") or official_tool_site(tool, company)
        base_row = {
            "bucket": "tool_general_updates",
            "source_type": "trending_tool",
            "tool": tool,
            "company": company,
            "official_site": site,
            "official_site_missing": not bool(site),
            "tool_query_required": True,
            "tool_type": tool_type,
            "sector": "general_market" if tool_type == "general" else ((item or {}).get("sector") or ""),
            "sector_hint": "general_market" if tool_type == "general" else ((item or {}).get("sector_hint") or ""),
            "tool_sector_terms": "",
            "tool_score": int((item or {}).get("popularity_score") or 0),
            "tool_query_variant": "announcement_vocabulary",
            "use_news_category": False,
        }
        exa_rows.append({**base_row, "query": tool_release_query(name, site, company)})
        searxng_rows.append({**base_row, "query": tool_release_query(name, site, company)})
    return {"exa": exa_rows, "searxng": searxng_rows}


# WHAT: Loads monthly tool records for query building.
# HOW: Uses monthly tools JSON registry and optional official-site enrichment.
# INPUT: limit integer and force_refresh flag.
# OUTPUT: List of enriched tool records.
def load_monthly_tool_records(limit: int = 24, *, force_refresh: bool = False) -> list[dict]:
    maintain_monthly_tool_files(force_refresh=force_refresh)
    records: dict[str, dict] = {}

    # Performs the add helper step.
    def add(raw: dict | str, source: str) -> None:
        item = normalize_tool_record(raw, source=source)
        if source != "monthly_tools_site" and not tool_record_allowed(item):
            return
        key = normalized_text(item.get("tool") or item.get("company") or "")
        if not key:
            return
        existing = records.get(key)
        if existing is None:
            records[key] = item
            return
        for field in ("company", "group", "sector", "sector_hint", "tool_type", "cultural_applications", "secondary_sectors", "official_site", "official_site_reason", "official_site_status"):
            if item.get(field) and not existing.get(field):
                existing[field] = item[field]
        existing["official_site_verified"] = bool(existing.get("official_site_verified") or item.get("official_site_verified"))
        existing["popularity_score"] = max(int(existing.get("popularity_score") or 0), int(item.get("popularity_score") or 0))

    monthly = load_json(MONTHLY_TOOLS_FILE, {"tool_records": [], "tools": []})
    for raw in monthly.get("tool_records") or []:
        add(raw, "monthly_tools_site")
    for raw in monthly.get("tools") or []:
        add(raw, "monthly_tools_site")
    tools = sorted(
        records.values(),
        key=lambda item: (int(item.get("popularity_score") or 0), 0 if tool_group(item) == "general_market" else -1),
        reverse=True,
    )
    return enrich_tools_with_official_sites(cap_tool_groups(tools, limit), discover_missing=force_refresh)


