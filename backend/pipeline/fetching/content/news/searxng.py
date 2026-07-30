"""News discovery: SearXNG page parsing and fetching."""

from .common import *
from .queries import *
from .normalization import *

def searxng_discovery_fetch_html(url: str, timeout: int = SEARXNG_DISCOVERY_PAGE_TIMEOUT) -> tuple[str, str, str]:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": PAGE_FETCH_USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        return response.text or "", str(response.url), ""
    except requests.RequestException as exc:
        return "", url, f"fetch_failed:{type(exc).__name__}"


def searxng_discovery_is_hub_page(html: str, url: str) -> bool:
    soup = BeautifulSoup(html or "", "html.parser")
    time_count = len(soup.find_all("time"))
    container_count = len(soup.find_all("article"))
    container_count += len(soup.select('[class*="changelog-entry"], [class*="release-note"], [class*="update-item"], [class*="post-card"]'))
    url_has_hub_term = any(term in str(url or "").lower() for term in SEARXNG_DISCOVERY_HUB_PATH_TERMS)
    return sum(1 for value in (time_count >= 3, container_count >= 3, url_has_hub_term) if value) >= 2


def searxng_discovery_split_hub(html: str, url: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    containers = []
    for selector in ("article", '[class*="changelog-entry"]', '[class*="release-note"]', "section:has(time)"):
        containers = soup.select(selector)
        if containers:
            break
    entries = []
    for container in containers:
        time_tag = container.find("time")
        date_value = parse_candidate_datetime(time_tag.get("datetime") if time_tag else "")
        if not date_value and time_tag:
            date_value = parse_candidate_datetime(time_tag.get_text(" ", strip=True))
        title_tag = container.find(["h2", "h3"])
        link_tag = container.find("a", href=True)
        title = clean_text(title_tag.get_text(" ", strip=True) if title_tag else "")
        entry_url = requests.compat.urljoin(url, link_tag["href"]) if link_tag else url
        if date_value and title:
            entries.append({"date": date_value, "title": title, "url": entry_url})
    return entries


def searxng_discovery_has_modified_context(tag) -> bool:
    if not tag:
        return False
    attrs = " ".join(str(value) for value in tag.attrs.values()).lower()
    nearby = tag.parent.get_text(" ", strip=True).lower()[:160] if tag.parent else ""
    evidence = f"{attrs} {nearby}"
    return "modified" in evidence or "updated" in evidence


def searxng_discovery_extract_date_confident(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html or "", "html.parser")
    candidates = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except Exception:
            continue
        values = data if isinstance(data, list) else [data]
        for item in values:
            if not isinstance(item, dict):
                continue
            parsed = parse_candidate_datetime(item.get("datePublished"))
            if parsed:
                candidates.append({"date": parsed, "confidence": 10, "source": "json_ld_datePublished"})
    for attrs in ({"property": "article:published_time"}, {"name": "article:published_time"}):
        tag = soup.find("meta", attrs=attrs)
        parsed = parse_candidate_datetime(tag.get("content") if tag else "")
        if parsed:
            candidates.append({"date": parsed, "confidence": 9, "source": "meta_article_published_time"})
    for tag in soup.find_all("time"):
        if searxng_discovery_has_modified_context(tag):
            continue
        parsed = parse_candidate_datetime(tag.get("datetime") or "")
        if parsed:
            candidates.append({"date": parsed, "confidence": 7, "source": "time_datetime"})
    head_text = soup.get_text(" ", strip=True)[:2000]
    for match in re.finditer(r"\d{4}-\d{2}-\d{2}", head_text):
        context = head_text[max(0, match.start() - 40): match.end() + 40].lower()
        if "modified" in context or "updated" in context:
            continue
        parsed = parse_candidate_datetime(match.group(0))
        if parsed:
            candidates.append({"date": parsed, "confidence": 3, "source": "regex_first_2000"})
            break
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item["confidence"], reverse=True)[0]


# 2026-07-18: short/generic tool names collide with unrelated real-world
# terms in plain SearXNG keyword search - e.g. the "Poe" chatbot query pulls
# in the video game Path of Exile (often abbreviated "PoE"), and "Runway"
# pulls in fashion runway coverage. These pages can never carry a real
# product-update signal for the tool being queried, so fetching+parsing them
# below is pure wasted latency, not a quality risk (they were already being
# rejected downstream once fetched) - skip the page fetch entirely instead.
SEARXNG_UNRELATED_TOPIC_DOMAINS = {
    "pathofexile.com",
    "poewiki.net",
    "poe-vault.com",
    "maxroll.gg",
    "vogue.com",
    "runwaylive.com",
}


# Fetches fetch searxng query rows from the configured external source.
def fetch_searxng_query_rows(rows: list[dict], *, exclude_items: list[dict] | None = None, single: bool = False) -> tuple[list[dict], dict]:
    endpoint = search_url()
    timeout = AI_UPDATES_SINGLE_TIMEOUT if single else AI_UPDATES_SEARXNG_TIMEOUT
    per_query = AI_UPDATES_SINGLE_RESULTS_PER_QUERY if single else AI_UPDATES_SEARXNG_RESULTS_PER_QUERY
    diagnostics = {
        "source": "searxng",
        "queries": len(rows),
        "raw_results": 0,
        "max_workers": max(1, min(len(rows), AI_UPDATES_SEARXNG_MAX_WORKERS)) if rows else 0,
        "timeout": timeout,
        "query_counts": {},
        "query_texts": [r.get("query") for r in rows],
        "query_results": [],
    }

    # Fetches fetch row from the configured external source.
    def fetch_row(row: dict):
        base_query = row["query"]
        # All Layer 1/2/3, tool-driven, broad, specialized, and refill queries
        # pass through this guard before SearXNG receives its weekly date filter.
        url_discovery_only = bool(row.get("searxng_url_discovery_only"))
        query = clean_text(base_query) if url_discovery_only else searxng_fetch_query(base_query)
        params = {
            "q": query,
            "format": "json",
            "language": row.get("searxng_language") or "en",
            # SearXNG news fetch: Brave/Startpage/DuckDuckGo are currently
            # CAPTCHA/rate-limited on this self-hosted instance (confirmed
            # live: "Suspended: too many requests" / "CAPTCHA"), so every
            # request that includes them burns most of its time waiting on
            # engines that will not answer. Google+Bing are the ones that
            # actually return results right now; they stay engine-config'd
            # in searxng/settings.yml so they can rejoin automatically once
            # unblocked, but our own requests no longer wait on them.
            "engines": SEARXNG_RELIABLE_ENGINES,
            "categories": "general" if url_discovery_only else row.get("searxng_categories") or AI_UPDATES_SEARXNG_CATEGORIES,
            "pageno": 1,
        }
        if not url_discovery_only and AI_UPDATES_SEARXNG_TIME_RANGE:
            params["time_range"] = AI_UPDATES_SEARXNG_TIME_RANGE
        try:
            response = requests.get(endpoint, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            return row, [], 0, f"searxng_request_failed:{exc}", []
        fetch_limit = max(per_query, SEARXNG_DISCOVERY_FETCH_RESULTS) if url_discovery_only else per_query
        raw_results = list(data.get("results") or [])[:fetch_limit]
        if url_discovery_only:
            raw_results = sorted(
                raw_results,
                key=lambda item: parse_candidate_datetime(str(item.get("publishedDate") or item.get("date") or "")) or utc_now() - timedelta(days=3650),
                reverse=True,
            )
        if url_discovery_only and row.get("source_type") == "searxng_url_discovery":
            now = utc_now()
            cutoff = now - timedelta(days=AI_UPDATES_LOOKBACK_DAYS)
            items = []
            rejected_count = 0
            pages_checked = 0
            rejected_audit = []
            seen_candidates = set()

            def add_verified_candidate(
                raw_candidate: dict,
                *,
                verified_date,
                date_source: str,
                source_result_url: str = "",
                acceptance_reason: str = "searxng_verified_page_date",
                date_confidence: str = "verified",
            ) -> None:
                nonlocal rejected_count
                candidate = dict(raw_candidate)
                candidate["publishedDate"] = verified_date.isoformat()
                item = normalize_candidate(
                    candidate,
                    query=query,
                    bucket=row.get("bucket") or "general",
                    source="searxng",
                    single=single,
                )
                if not item:
                    rejected_count += 1
                    rejected_audit.append({
                        "title": clean_text(candidate.get("title") or ""),
                        "url": candidate.get("url") or "",
                        "reason": "normalize_rejected",
                    })
                    return
                item["fetch_method"] = "searxng_url_verified"
                item["source_lane"] = row.get("source_lane") or "tool_searxng"
                item["acceptance_reason"] = acceptance_reason
                item["date_confidence"] = date_confidence
                item["verified_published_date"] = verified_date.isoformat()
                item["verified_date_source"] = date_source
                if source_result_url:
                    item["source_result_url"] = source_result_url
                for key in ("source_type", "tool", "company", "query_mix", "layer", "aggregator_source", "source_lane"):
                    if row.get(key) is not None:
                        item[key] = row.get(key)
                # 2026-07-18: this url_discovery_only path (the main
                # "tool_name_update" lane) never checked whether the result
                # actually mentions the tool it was queried for - confirmed
                # live: an "Ideogram" query accepted unrelated robotics/model
                # news from i-scoop.eu, and "LTX Studio" accepted unrelated
                # Ukrainian politics articles, both with a verified page date
                # and tagged as if they were real Ideogram/LTX Studio updates.
                # tool_query_reject_reason() already exists and is used by
                # the other two fetch branches (Exa, non-url-discovery
                # SearXNG) for exactly this - just never wired in here.
                tool_mismatch_reason = tool_query_reject_reason(row, item)
                if tool_mismatch_reason:
                    rejected_count += 1
                    rejected_audit.append({
                        "title": item.get("title") or "",
                        "url": item.get("url") or "",
                        "reason": tool_mismatch_reason,
                    })
                    return
                hard_flags = set(item.get("candidate_flags") or []) & SEARXNG_HARD_REJECT_FLAGS
                if hard_flags:
                    rejected_count += 1
                    rejected_audit.append({
                        "title": item.get("title") or "",
                        "url": item.get("url") or "",
                        "reason": f"hard_flags:{','.join(sorted(hard_flags))}",
                    })
                    return
                if result_is_excluded(item, exclude_items):
                    rejected_count += 1
                    rejected_audit.append({
                        "title": item.get("title") or "",
                        "url": item.get("url") or "",
                        "reason": "excluded_existing_item",
                    })
                    return
                items.append(item)

            for raw in raw_results:
                if SEARXNG_DISCOVERY_MAX_PAGES_PER_TOOL and pages_checked >= SEARXNG_DISCOVERY_MAX_PAGES_PER_TOOL:
                    rejected_count += 1
                    rejected_audit.append({"reason": "max_pages_per_tool_reached"})
                    break
                url = str(raw.get("url") or "").strip()
                title = clean_text(raw.get("title") or "")
                key = canonical_news_url(url)
                if not key or key in seen_candidates:
                    rejected_count += 1
                    rejected_audit.append({"title": title, "url": url, "reason": "duplicate_or_missing_url"})
                    continue
                seen_candidates.add(key)
                if source_domain(url) in SEARXNG_UNRELATED_TOPIC_DOMAINS:
                    rejected_count += 1
                    rejected_audit.append({"title": title, "url": url, "reason": "known_unrelated_topic_domain"})
                    continue
                pages_checked += 1
                html, final_url, error = searxng_discovery_fetch_html(url)
                if error:
                    rejected_count += 1
                    rejected_audit.append({"title": title, "url": url, "final_url": final_url, "reason": error})
                    continue
                if searxng_discovery_is_hub_page(html, final_url):
                    hub_entries = searxng_discovery_split_hub(html, final_url)
                    if not hub_entries:
                        rejected_count += 1
                        rejected_audit.append({"title": title, "url": url, "final_url": final_url, "reason": "hub_without_entries"})
                        continue
                    for entry in hub_entries:
                        entry_key = canonical_news_url(entry["url"])
                        if not entry_key or entry_key in seen_candidates:
                            continue
                        seen_candidates.add(entry_key)
                        if entry["date"] < cutoff:
                            rejected_count += 1
                            rejected_audit.append({
                                "title": entry["title"],
                                "url": entry["url"],
                                "date": entry["date"].isoformat(),
                                "reason": "outside_last_7_days",
                            })
                            continue
                        add_verified_candidate(
                            {
                                "title": entry["title"],
                                "url": entry["url"],
                                "content": clean_text(raw.get("content") or raw.get("snippet") or title),
                                "engine": raw.get("engine") or "",
                            },
                            verified_date=entry["date"],
                            date_source="hub_time",
                            source_result_url=final_url,
                        )
                        if len(items) >= per_query:
                            break
                    if len(items) >= per_query:
                        break
                    continue
                verified = searxng_discovery_extract_date_confident(html, final_url)
                if not verified:
                    official_domain = official_site_domain(row.get("official_site") or "")
                    result_domain = source_domain(final_url or url)
                    content = clean_text(raw.get("content") or raw.get("snippet") or "")
                    if (
                        official_domain
                        and domain_matches(result_domain, (official_domain,))
                        and result_looks_like_update(title, final_url or url, content)
                    ):
                        verified_raw = dict(raw)
                        verified_raw["url"] = final_url or url
                        add_verified_candidate(
                            verified_raw,
                            verified_date=now,
                            date_source="official_update_like_no_verified_date",
                            acceptance_reason="official_searxng_update_like_no_verified_date",
                            date_confidence="low",
                        )
                        if len(items) >= per_query:
                            break
                        continue
                    rejected_count += 1
                    rejected_audit.append({"title": title, "url": url, "final_url": final_url, "reason": "no_confident_published_date"})
                    continue
                if verified["date"] < cutoff:
                    rejected_count += 1
                    rejected_audit.append({
                        "title": title,
                        "url": url,
                        "final_url": final_url,
                        "date": verified["date"].isoformat(),
                        "date_source": verified["source"],
                        "reason": "outside_last_7_days",
                    })
                    continue
                verified_raw = dict(raw)
                verified_raw["url"] = final_url
                add_verified_candidate(
                    verified_raw,
                    verified_date=verified["date"],
                    date_source=verified["source"],
                )
                if len(items) >= per_query:
                    break
            query_audit = {
                "source": "searxng",
                "query": base_query,
                "executed_query": query,
                "raw_count": len(raw_results),
                "accepted_count": len(items),
                "rejected_count": rejected_count,
                "query_mix": row.get("query_mix") or "",
                "source_lane": row.get("source_lane") or "tool_searxng",
                "tool": row.get("tool") or "",
                "company": row.get("company") or "",
                "official_site": row.get("official_site") or "",
                "official_site_missing": bool(row.get("official_site_missing")),
                "url_discovery_only": url_discovery_only,
                "layer": row.get("layer") or "",
                "bucket": row.get("bucket") or "",
                "fetch_method": "searxng_url_verified",
                "pages_checked": pages_checked,
                "window": {"days": AI_UPDATES_LOOKBACK_DAYS, "start": cutoff.isoformat(), "end": now.isoformat()},
                "rejections": rejected_audit[:80],
                "results": summarize_items(items, limit=per_query),
            }
            return row, items, len(raw_results), "", query_audit
        items = []
        rejected_count = 0
        for raw in raw_results:
            item = normalize_candidate(raw, query=query, bucket=row.get("bucket") or "general", source="searxng", single=single)
            if item:
                reject_reason = tool_query_reject_reason(row, item)
                if reject_reason:
                    # FETCHER PERMISSIVE MODE: keep query-mismatch results for
                    # downstream filters/model review instead of dropping them
                    # during source fetch.
                    item["tool_query_reject_reason"] = reject_reason
                    item.setdefault("candidate_flags", []).append(reject_reason)
                    rejected_count += 1
                    continue
                hard_flags = set(item.get("candidate_flags") or []) & SEARXNG_HARD_REJECT_FLAGS
                if hard_flags:
                    rejected_count += 1
                    continue
            else:
                rejected_count += 1
            if item:
                # RESULT TAGGING: Official SearXNG rows that succeed without
                # fallback are direct official-site hits.
                if row.get("official_site"):
                    item["fetch_method"] = "official_direct"
                item["source_lane"] = row.get("source_lane") or (
                    "tool_searxng" if row.get("query_mix") == "tool_name_update" else item.get("source_lane") or ""
                )
                item["acceptance_reason"] = item.get("acceptance_reason") or "searxng_normalized_result"
                for key in ("source_type", "tool", "company", "query_mix", "layer", "aggregator_source", "source_lane"):
                    if row.get(key) is not None:
                        item[key] = row.get(key)
            if item and not result_is_excluded(item, exclude_items):
                items.append(item)
            elif item:
                rejected_count += 1
        query_audit = {
            "source": "searxng",
            "query": base_query,
            "executed_query": query,
            "raw_count": len(raw_results),
            "accepted_count": len(items),
            "rejected_count": rejected_count,
            "query_mix": row.get("query_mix") or "",
            "source_lane": row.get("source_lane") or "",
            "tool": row.get("tool") or "",
            "company": row.get("company") or "",
            "official_site": row.get("official_site") or "",
            "official_site_missing": bool(row.get("official_site_missing")),
            "url_discovery_only": url_discovery_only,
            "layer": row.get("layer") or "",
            "bucket": row.get("bucket") or "",
            "results": summarize_items(items, limit=per_query),
        }
        return row, items, len(raw_results), "", query_audit

    started = time.time()
    output = []
    seen = set()
    max_workers = max(1, min(len(rows), AI_UPDATES_SEARXNG_MAX_WORKERS))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_row, row) for row in rows]
        for future in as_completed(futures):
            try:
                row, items, raw_count, error, query_audit = future.result()
            except Exception as exc:
                row, items, raw_count, error, query_audit = {}, [], 0, f"searxng_request_failed:{exc}", []
            diagnostics["raw_results"] += raw_count
            diagnostics["query_counts"][row.get("query") or ""] = raw_count
            if error:
                diagnostics.setdefault("errors", []).append(error[:220])
                diagnostics["error"] = diagnostics.get("error") or error.split(":", 1)[0]
                diagnostics["query_results"].append({
                    "source": "searxng",
                    "query": row.get("query") or "",
                    "raw_count": raw_count,
                    "accepted_count": 0,
                    "rejected_count": 0,
                    "error": error[:500],
                    "query_mix": row.get("query_mix") or "",
                    "tool": row.get("tool") or "",
                    "company": row.get("company") or "",
                    "official_site": row.get("official_site") or "",
                    "official_site_missing": bool(row.get("official_site_missing")),
                    "bucket": row.get("bucket") or "",
                    "results": [],
                })
                continue
            diagnostics["query_results"].append(query_audit)
            for item in items:
                key = item["url"]
                if key in seen:
                    continue
                seen.add(key)
                output.append(item)
    diagnostics["seconds"] = round(time.time() - started, 2)
    diagnostics["unique_results"] = len(output)
    log_event(
        "source.searxng.finished",
        queries=len(rows),
        raw_results=diagnostics["raw_results"],
        unique_results=len(output),
        seconds=diagnostics["seconds"],
        max_workers=diagnostics.get("max_workers"),
        timeout=diagnostics.get("timeout"),
        errors=diagnostics.get("errors", [])[:8],
        query_counts=diagnostics.get("query_counts", {}),
        sample=summarize_items(output, limit=6),
    )
    return output, diagnostics


EXA_RECENT_PAGE_TIMEOUT = env_int("AI_UPDATES_EXA_RECENT_PAGE_TIMEOUT", "8")
EXA_RECENT_MAX_PAGES_PER_TOOL = env_int("AI_UPDATES_EXA_RECENT_MAX_PAGES_PER_TOOL", "6")

__all__ = [name for name in globals() if not name.startswith("__")]
