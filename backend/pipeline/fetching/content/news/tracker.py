"""News discovery: tracker discovery layers."""

from .common import *
from .queries import *
from .normalization import *
from .searxng import *
from .exa import *
from .merge import *

def tracker_dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    output = []
    for item in items:
        key = canonical_news_url(item.get("url") or "")
        if key and key not in seen:
            seen.add(key)
            output.append(item)
    return output


def tracker_has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(term.lower() in lowered for term in terms)


def tracker_search_exa(query: str, *, layer: str, results: int = TRACKER_RESULTS_PER_QUERY) -> tuple[list[dict], dict]:
    if not EXA_API_KEY:
        return [], {"query": query, "source": "exa", "raw_count": 0, "error": "missing_exa_api_key", "layer": layer, "source_lane": "tracker"}
    start_date = (utc_now() - timedelta(days=AI_UPDATES_LOOKBACK_DAYS)).date().isoformat()
    payload = {
        "query": query,
        "numResults": results,
        "type": "auto",
        "startPublishedDate": start_date,
        "contents": {"text": True},
    }
    try:
        response = requests.post(
            "https://api.exa.ai/search",
            headers={"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY},
            json=payload,
            timeout=AI_UPDATES_EXA_TIMEOUT,
        )
        if response.status_code >= 400:
            return [], {"query": query, "source": "exa", "raw_count": 0, "error": exa_http_error(response), "layer": layer, "source_lane": "tracker"}
        rows = [
            {
                "title": clean_text(item.get("title") or ""),
                "url": str(item.get("url") or "").strip(),
                "content": clean_text(item.get("text") or "")[:900],
                "source_engine": "exa",
                "query_used": query,
            }
            for item in (response.json() or {}).get("results") or []
            if item.get("url")
        ]
        return rows, {"query": query, "source": "exa", "raw_count": len(rows), "error": "", "layer": layer, "source_lane": "tracker"}
    except Exception as exc:
        return [], {"query": query, "source": "exa", "raw_count": 0, "error": f"exa_failed:{type(exc).__name__}", "layer": layer, "source_lane": "tracker"}


def tracker_search_searxng(query: str, *, layer: str, language: str, results: int = TRACKER_RESULTS_PER_QUERY) -> tuple[list[dict], dict]:
    try:
        response = requests.get(
            search_url(),
            params={
                "q": query,
                "format": "json",
                "language": language,
                "categories": "general,news",
                "time_range": "week",
                "pageno": 1,
            },
            timeout=AI_UPDATES_SEARXNG_TIMEOUT,
        )
        response.raise_for_status()
        rows = [
            {
                "title": clean_text(item.get("title") or ""),
                "url": str(item.get("url") or "").strip(),
                "content": clean_text(item.get("content") or item.get("snippet") or "")[:900],
                "source_engine": "searxng",
                "query_used": query,
            }
            for item in ((response.json() or {}).get("results") or [])[:results]
            if item.get("url")
        ]
        return rows, {"query": query, "source": "searxng", "raw_count": len(rows), "error": "", "layer": layer, "source_lane": "tracker"}
    except Exception as exc:
        return [], {"query": query, "source": "searxng", "raw_count": 0, "error": f"searxng_failed:{type(exc).__name__}", "layer": layer, "source_lane": "tracker"}


def tracker_verify_page_date(url: str) -> dict | None:
    html, final_url, error = searxng_discovery_fetch_html(url, timeout=TRACKER_PAGE_TIMEOUT)
    if error:
        return None
    verified = searxng_discovery_extract_date_confident(html, final_url)
    if not verified:
        return None
    verified["final_url"] = final_url
    return verified


def tracker_known_terms() -> list[str]:
    data = load_json(MONTHLY_TOOLS_FILE, {"tool_records": [], "tools": []})
    terms = []
    for item in data.get("tools") or []:
        if isinstance(item, str) and clean_text(item):
            terms.append(clean_text(item).lower())
    for item in data.get("tool_records") or []:
        if isinstance(item, dict):
            for key in ("tool", "company"):
                value = clean_text(item.get(key) or "")
                if value:
                    terms.append(value.lower())
    return list(dict.fromkeys(terms + ["openai", "anthropic", "google ai", "xai", "llama", "microsoft copilot"]))


def tracker_is_known_tool(item: dict, known_terms: list[str]) -> bool:
    text = f"{item.get('title', '')} {item.get('content', '')}".lower()
    return any(term and term in text for term in known_terms)


def tracker_general_user_fit_score(item: dict) -> tuple[int, list[str]]:
    text = f"{item.get('title', '')} {item.get('content', '')} {item.get('url', '')}".lower()
    score = 0
    reasons = []
    developer_hits = [term for term in TRACKER_DEVELOPER_TERMS if term in text]
    if developer_hits:
        score -= 8
        reasons.append(f"developer_tool:{','.join(developer_hits[:3])}")
    domain_hits = [term for term in TRACKER_GENERAL_USER_DOMAINS if term in text]
    if domain_hits:
        score += min(6, len(domain_hits) * 2)
        reasons.append(f"general_user_domain:{','.join(domain_hits[:4])}")
    value_hits = [term for term in TRACKER_USER_VALUE_TERMS if term in text]
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


def tracker_extract_potential_tool_name(title: str) -> str:
    for pattern in (
        r"Introducing\s+([A-Z][a-zA-Z0-9\-]+)",
        r"Announcing\s+([A-Z][a-zA-Z0-9\-]+)",
        r"([A-Z][a-zA-Z0-9\-]+)\s+(?:launches|announces|unveils|releases)",
        r"Meet\s+([A-Z][a-zA-Z0-9\-]+)",
    ):
        match = re.search(pattern, title or "", re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if len(value) >= 3 and value.lower() not in {"the", "new", "our", "this"}:
                return value
    return ""


def tracker_is_saudi_official(url: str = "") -> bool:
    domain = source_domain(url)
    return any(domain == item or domain.endswith(f".{item}") for item in SAUDI_OFFICIAL_DOMAINS)


def tracker_saudi_priority(item: dict) -> int:
    domain = source_domain(item.get("url") or "")
    if tracker_is_saudi_official(item.get("url") or ""):
        return 1
    if any(domain == item_domain or domain.endswith(f".{item_domain}") for item_domain in SAUDI_TRUSTED_MEDIA_DOMAINS):
        return 2
    return 4


def tracker_saudi_editorial_type(item: dict) -> str:
    text = f"{item.get('title', '')} {item.get('content', '')}".lower()
    official = tracker_is_saudi_official(item.get("url") or "")
    if tracker_has_any(text, SAUDI_TRAINING_TERMS):
        return "training_or_bootcamp"
    if tracker_has_any(text, SAUDI_MARKET_REPORT_TERMS):
        return "market_report"
    if not tracker_has_any(text, SAUDI_TERMS_TRACKER) or not tracker_has_any(text, SAUDI_AI_TERMS_TRACKER):
        return "reject"
    if tracker_has_any(text, SAUDI_POLICY_TERMS):
        return "official_ai_policy" if official or tracker_has_any(text, ("sdaia", "سدايا", "ndmo", "mcit")) else "reject"
    if tracker_has_any(text, SAUDI_PLATFORM_TERMS) and (official or tracker_has_any(text, ("humain", "sdaia", "هيومين", "سدايا"))):
        return "official_ai_platform"
    if tracker_has_any(text, SAUDI_GOV_SERVICE_TERMS) and official:
        return "official_ai_government_service"
    if tracker_has_any(text, SAUDI_SECTOR_TERMS) and (official or tracker_has_any(text, ("ministry", "وزارة", "authority", "هيئة"))):
        return "official_ai_sector_adoption"
    if tracker_has_any(text, SAUDI_PARTNERSHIP_TERMS):
        return "private_ai_partnership" if not official else "official_ai_sector_adoption"
    return "reject"


def tracker_saudi_fit_score(item: dict, editorial_type: str) -> int:
    text = f"{item.get('title', '')} {item.get('content', '')}".lower()
    score = 5 if tracker_is_saudi_official(item.get("url") or "") else 0
    if tracker_has_any(text, SAUDI_POLICY_TERMS):
        score += 4
    if tracker_has_any(text, SAUDI_PLATFORM_TERMS):
        score += 4
    if tracker_has_any(text, SAUDI_SECTOR_TERMS):
        score += 3
    if tracker_has_any(text, SAUDI_TRAINING_TERMS):
        score -= 5
    if tracker_has_any(text, SAUDI_MARKET_REPORT_TERMS):
        score -= 4
    if editorial_type == "private_ai_partnership":
        score -= 3
    if editorial_type == "reject" or editorial_type not in {"official_ai_policy", "official_ai_platform", "official_ai_government_service", "official_ai_sector_adoption"}:
        score -= 3
    return score


def tracker_candidate_from_raw(raw: dict, *, layer: str, bucket: str, query: str, verified: dict, extra: dict | None = None) -> dict | None:
    candidate_raw = dict(raw)
    candidate_raw["url"] = verified.get("final_url") or candidate_raw.get("url")
    candidate_raw["publishedDate"] = verified["date"].isoformat()
    item = normalize_candidate(candidate_raw, query=query, bucket=bucket, source=raw.get("source_engine") or "tracker", single=False)
    if not item:
        return None
    item["layer"] = layer
    item["source_type"] = layer
    item["query_mix"] = "tracker_pipeline"
    item["source_lane"] = "tracker"
    item["acceptance_reason"] = f"{layer}_verified_page_date"
    item["date_confidence"] = "verified"
    item["fetch_method"] = f"{layer}_verified"
    item["verified_published_date"] = verified["date"].isoformat()
    item["verified_date_source"] = verified["source"]
    item["verified_date_confidence"] = verified.get("confidence", 0)
    item["tracker_query"] = query
    if extra:
        item.update(extra)
    return item


def fetch_tracker_discovery_layer(*, exclude_items: list[dict] | None = None) -> tuple[list[dict], dict]:
    """Run the script-matched AI discovery and Saudi AI tracker pipelines."""
    started = time.time()
    cutoff = utc_now() - timedelta(days=AI_UPDATES_LOOKBACK_DAYS)
    query_results = []
    rejected = []
    accepted: list[dict] = []
    raw_ai = []
    raw_saudi = []

    for query in AI_DISCOVERY_TRACKER_QUERIES:
        exa_items, exa_audit = tracker_search_exa(query, layer="ai_discovery_tracker")
        sx_items, sx_audit = tracker_search_searxng(query, layer="ai_discovery_tracker", language="en")
        query_results.extend([exa_audit, sx_audit])
        raw_ai.extend(exa_items)
        raw_ai.extend(sx_items)

    known_terms = tracker_known_terms()
    ai_unique = tracker_dedupe(raw_ai)
    ai_clean = [
        item for item in ai_unique
        if not tracker_has_any(f"{item.get('title', '')} {item.get('url', '')}", TRACKER_NOISE_INDICATORS)
        and tracker_has_any(f"{item.get('title', '')} {item.get('content', '')}", TRACKER_LAUNCH_SIGNALS)
    ]
    for item in ai_clean:
        verified = tracker_verify_page_date(item.get("url") or "")
        if not verified or verified["date"] < cutoff:
            rejected.append({**item, "layer": "ai_discovery_tracker", "reject_reason": "date_not_verified_or_old"})
            continue
        score, reasons = tracker_general_user_fit_score(item)
        if score < 1:
            rejected.append({
                **item,
                "layer": "ai_discovery_tracker",
                "reject_reason": "developer_or_unclear_general_user_value",
                "general_user_fit_score": score,
                "audience_fit_reasons": reasons,
            })
            continue
        candidate = tracker_candidate_from_raw(
            item,
            layer="ai_discovery_tracker",
            bucket="unlisted_ai_tool_updates",
            query=item.get("query_used") or "",
            verified=verified,
            extra={
                "potential_tool": tracker_extract_potential_tool_name(item.get("title") or ""),
                "general_user_fit_score": score,
                "audience_fit_reasons": reasons,
                "known_tool_update_hint": tracker_is_known_tool(item, known_terms),
            },
        )
        if candidate and not result_is_excluded(candidate, exclude_items):
            accepted.append(candidate)
        elif candidate:
            rejected.append({**item, "layer": "ai_discovery_tracker", "reject_reason": "excluded_existing_item"})

    for query in SAUDI_AI_TRACKER_QUERIES:
        exa_items, exa_audit = tracker_search_exa(query, layer="saudi_ai_tracker")
        sx_items, sx_audit = tracker_search_searxng(query, layer="saudi_ai_tracker", language="all")
        query_results.extend([exa_audit, sx_audit])
        raw_saudi.extend(exa_items)
        raw_saudi.extend(sx_items)

    saudi_unique = tracker_dedupe(raw_saudi)
    saudi_prelim = [
        item for item in saudi_unique
        if tracker_has_any(f"{item.get('title', '')} {item.get('content', '')}", SAUDI_TERMS_TRACKER)
        and tracker_has_any(f"{item.get('title', '')} {item.get('content', '')}", SAUDI_AI_TERMS_TRACKER)
    ]
    saudi_accepted = []
    for item in saudi_prelim:
        verified = tracker_verify_page_date(item.get("url") or "")
        if not verified or verified["date"] < cutoff:
            rejected.append({**item, "layer": "saudi_ai_tracker", "reject_reason": "date_not_verified_or_old"})
            continue
        editorial_type = tracker_saudi_editorial_type(item)
        fit_score = tracker_saudi_fit_score(item, editorial_type)
        if editorial_type not in {"official_ai_policy", "official_ai_platform", "official_ai_government_service", "official_ai_sector_adoption"} or fit_score <= 0:
            rejected.append({
                **item,
                "layer": "saudi_ai_tracker",
                "reject_reason": "editorial_fit_failed",
                "editorial_type": editorial_type,
                "editorial_fit_score": fit_score,
            })
            continue
        candidate = tracker_candidate_from_raw(
            item,
            layer="saudi_ai_tracker",
            bucket="saudi_ai_news",
            query=item.get("query_used") or "",
            verified=verified,
            extra={
                "editorial_type": editorial_type,
                "editorial_fit_score": fit_score,
                "official_source": tracker_is_saudi_official(item.get("url") or ""),
                "source_priority": tracker_saudi_priority(item),
            },
        )
        if candidate and not result_is_excluded(candidate, exclude_items):
            saudi_accepted.append(candidate)
        elif candidate:
            rejected.append({**item, "layer": "saudi_ai_tracker", "reject_reason": "excluded_existing_item"})
    saudi_accepted.sort(key=lambda row: (row.get("source_priority") or 9, -(row.get("editorial_fit_score") or 0), row.get("verified_published_date") or ""))
    accepted.extend(saudi_accepted)

    items, combined_diag = combine_source_results(
        [("tracker_discovery_pipeline", accepted, {"raw_results": len(raw_ai) + len(raw_saudi), "queries": len(query_results)})],
        mode="tracker_discovery_pipeline",
    )
    diagnostics = {
        **combined_diag,
        "source": "tracker_discovery_layer",
        "query_results": query_results,
        "raw_results": len(raw_ai) + len(raw_saudi),
        "queries": len(query_results),
        "unique_results": len(items),
        "layer_counts": dict(Counter(item.get("layer") or "unknown" for item in items)),
        "summary": {
            "ai_raw": len(raw_ai),
            "ai_after_dedupe": len(ai_unique),
            "ai_clean_launch_candidates": len(ai_clean),
            "saudi_raw": len(raw_saudi),
            "saudi_after_dedupe": len(saudi_unique),
            "saudi_ai_candidates": len(saudi_prelim),
            "accepted": len(items),
            "rejected": len(rejected),
        },
        "rejected_items": rejected[:80],
    }
    diagnostics["tracker_discovery_layer_seconds"] = round(time.time() - started, 2)
    log_event(
        "tracker_discovery_layer.finished",
        raw_results=diagnostics.get("raw_results", 0),
        unique_results=len(items),
        seconds=diagnostics["tracker_discovery_layer_seconds"],
        layer_counts=diagnostics.get("layer_counts", {}),
        source_failures=diagnostics.get("source_failures", {}),
    )
    return items, diagnostics


# Fetches fetch news candidates from the configured external source.

__all__ = [name for name in globals() if not name.startswith("__")]
