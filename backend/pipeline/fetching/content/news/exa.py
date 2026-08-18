"""News discovery: Exa page-date verification and fetching."""

from .common import *
from .queries import *
from .normalization import *
from .searxng import *

def exa_recent_date_from_json_ld(soup: BeautifulSoup):
    def iter_values(value):
        if isinstance(value, dict):
            yield value
            graph = value.get("@graph")
            if isinstance(graph, list):
                for graph_item in graph:
                    yield from iter_values(graph_item)
        elif isinstance(value, list):
            for list_item in value:
                yield from iter_values(list_item)

    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except Exception:
            continue
        for item in iter_values(data):
            for key in ("datePublished", "dateCreated", "uploadDate", "dateModified"):
                parsed = parse_candidate_datetime(item.get(key))
                if parsed:
                    return parsed
    return None


def exa_recent_date_from_meta(soup: BeautifulSoup):
    selectors = [
        {"property": "article:published_time"},
        {"name": "article:published_time"},
        {"property": "og:published_time"},
        {"name": "date"},
        {"name": "publishdate"},
        {"name": "pubdate"},
        {"name": "timestamp"},
    ]
    for attrs in selectors:
        tag = soup.find("meta", attrs=attrs)
        parsed = parse_candidate_datetime(tag.get("content") if tag else "")
        if parsed:
            return parsed
    return None


def exa_recent_date_from_time_tag(soup: BeautifulSoup):
    for tag in soup.find_all("time"):
        parsed = parse_candidate_datetime(tag.get("datetime") or tag.get_text(" ", strip=True))
        if parsed:
            return parsed
    return None


def exa_recent_date_from_text(soup: BeautifulSoup):
    text = soup.get_text(" ", strip=True)
    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            parsed = parse_candidate_datetime(match.group(0))
            if parsed:
                return parsed
    return None


EXA_RECENT_RELATIVE_TIME_PATTERNS = (
    (re.compile(r"\b(\d+)\s*(?:minute|min)s?\s+ago\b", re.I), "minutes"),
    (re.compile(r"\b(\d+)\s*hours?\s+ago\b", re.I), "hours"),
    (re.compile(r"\b(\d+)\s*days?\s+ago\b", re.I), "days"),
    (re.compile(r"\b(\d+)\s*weeks?\s+ago\b", re.I), "weeks"),
    (re.compile(r"منذ\s+(\d+)\s*(?:دقيقة|دقائق)"), "minutes"),
    (re.compile(r"منذ\s+(\d+)\s*(?:ساعة|ساعات)"), "hours"),
    (re.compile(r"منذ\s+(\d+)\s*(?:يوم|أيام)"), "days"),
    (re.compile(r"منذ\s+(\d+)\s*(?:أسبوع|أسابيع)"), "weeks"),
)

# Cheap, free signal: many changelog/blog servers send an accurate
# Last-Modified header even when the page body has no visible date.
def exa_recent_date_from_http_header(response) -> object | None:
    header = ""
    try:
        header = response.headers.get("Last-Modified") or ""
    except Exception:
        return None
    return parse_candidate_datetime(header) if header else None


# Handles "2 days ago" / "منذ يومين" style relative timestamps that the
# absolute-date regex in exa_recent_date_from_text cannot parse. Deliberately
# skips bare words like "today"/"yesterday" - those match unrelated page text
# (cookie banners, footers) too easily; only the specific numeric "N <unit>
# ago" phrasing is treated as reliable evidence.
def exa_recent_date_from_relative_text(soup: BeautifulSoup):
    text = soup.get_text(" ", strip=True)
    now = utc_now()
    for pattern, unit in EXA_RECENT_RELATIVE_TIME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        amount = int(match.group(1))
        delta = timedelta(**{unit: amount})
        return now - delta
    return None


# Best-effort sitemap.xml lookup: some update pages omit any on-page date but
# the site's own sitemap carries an accurate <lastmod> for that exact URL.
def exa_recent_date_from_sitemap(url: str, *, timeout: int = EXA_RECENT_PAGE_TIMEOUT):
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
    canonical_target = canonical_news_url(url, keep_query=True)
    for sitemap_path in ("/sitemap.xml", "/sitemap_index.xml", "/news-sitemap.xml"):
        sitemap_url = f"{parsed.scheme or 'https'}://{parsed.netloc}{sitemap_path}"
        try:
            response = requests.get(
                sitemap_url,
                headers={"User-Agent": PAGE_FETCH_USER_AGENT},
                timeout=timeout,
            )
            if response.status_code >= 400:
                continue
            soup = BeautifulSoup(response.text or "", "xml")
        except Exception:
            continue
        for entry in soup.find_all("url"):
            loc = entry.find("loc")
            if not loc:
                continue
            if canonical_news_url(loc.get_text(strip=True), keep_query=True) != canonical_target:
                continue
            lastmod = entry.find("lastmod")
            parsed_date = parse_candidate_datetime(lastmod.get_text(strip=True) if lastmod else "")
            if parsed_date:
                return parsed_date
    return None


def exa_recent_verify_date_details(url: str, timeout: int = EXA_RECENT_PAGE_TIMEOUT):
    try:
        response = requests.get(
            url,
            headers={"User-Agent": PAGE_FETCH_USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return None, "", f"fetch_failed:{type(exc).__name__}", url
    html = response.text or ""
    soup = BeautifulSoup(html, "html.parser")
    final_url = str(response.url)

    # Hub/index page check comes first: a changelog/blog index almost always
    # has a <time> tag on its top (newest) listed entry, which would
    # otherwise satisfy time_datetime below and get accepted as-is - pointing
    # readers at the index page instead of the specific article. Resolve to
    # the newest linked entry's own URL+date before trying page-level signals.
    if searxng_discovery_is_hub_page(html, final_url):
        entries = sorted(
            (entry for entry in searxng_discovery_split_hub(html, final_url) if entry.get("date")),
            key=lambda entry: entry["date"],
            reverse=True,
        )
        if entries:
            newest = entries[0]
            return newest["date"], "hub_page_newest_entry", "", str(newest.get("url") or final_url)

    sources = [
        ("json_ld_datePublished", exa_recent_date_from_json_ld(soup)),
        ("meta_article_published_time", exa_recent_date_from_meta(soup)),
        ("time_datetime", exa_recent_date_from_time_tag(soup)),
        ("http_last_modified", exa_recent_date_from_http_header(response)),
        ("relative_text", exa_recent_date_from_relative_text(soup)),
        ("text_date", exa_recent_date_from_text(soup)),
    ]
    for source_name, date_value in sources:
        if date_value:
            return date_value, source_name, "", final_url

    sitemap_date = exa_recent_date_from_sitemap(final_url, timeout=timeout)
    if sitemap_date:
        return sitemap_date, "sitemap_lastmod", "", final_url
    return None, "", "no_verified_date", final_url


def exa_recent_build_search_strategies(tool_name: str, official_site: str = "", official_domain: str = "") -> list[dict]:
    tool_update_query = f'site:{official_domain} "{tool_name}" update' if official_domain else f'"{tool_name}" update'
    new_phases = []
    if official_site:
        new_phases.extend([
            {"strategy": "new_three_phase", "phase": 1, "query": f'site:{official_site} "changelog" OR "release notes"'},
            {"strategy": "new_three_phase", "phase": 2, "query": f'"{tool_name}" changelog site:{official_site}'},
        ])
    new_phases.append({"strategy": "new_three_phase", "phase": 3, "query": f'"{tool_name}" release notes'})
    return [
        {"strategy": "tool_name_update", "phases": [{"strategy": "tool_name_update", "phase": 1, "query": tool_update_query}]},
        {"strategy": "new_three_phase", "phases": new_phases},
    ]


OFFICIAL_UPDATE_PATH_TERMS = (
    "changelog",
    "change-log",
    "release-notes",
    "release_notes",
    "releases",
    "updates",
    "whats-new",
    "what-s-new",
    "news",
    "blog",
    "product-updates",
)

OFFICIAL_UPDATE_TEXT_RE = re.compile(
    r"\b("
    r"update|updates|updated|changelog|release notes|release|released|"
    r"what'?s new|new feature|launch|launched|rollout|rolling out|"
    r"introduces|announces|now available|generally available"
    r")\b",
    re.I,
)


def official_domain_matches(url: str = "", official_domain: str = "") -> bool:
    domain = source_domain(url or "")
    official = root_site_token(official_domain or "")
    return bool(domain and official and (domain == official or domain.endswith(f".{official}")))


def official_update_like(raw: dict, url: str = "", title: str = "") -> bool:
    text = " ".join([
        str(title or raw.get("title") or ""),
        str(raw.get("text") or raw.get("summary") or ""),
        str(raw.get("url") or url or ""),
    ])
    lowered_url = str(url or raw.get("url") or "").lower()
    return bool(OFFICIAL_UPDATE_TEXT_RE.search(text)) or any(term in lowered_url for term in OFFICIAL_UPDATE_PATH_TERMS)


def exa_raw_date(raw: dict) -> object | None:
    return parse_result_datetime(raw.get("publishedDate") or raw.get("date") or raw.get("published") or "")


# Fetches fetch exa query rows from the configured external source.
def fetch_exa_query_rows(rows: list[dict], *, exclude_items: list[dict] | None = None, single: bool = False) -> tuple[list[dict], dict]:
    diagnostics = {
        "source": "exa",
        "queries": len(rows),
        "raw_results": 0,
        "max_workers": max(1, min(len(rows), AI_UPDATES_EXA_MAX_WORKERS)) if rows else 0,
        "retries": AI_UPDATES_EXA_RETRIES,
        "timeout": AI_UPDATES_EXA_TIMEOUT,
        "query_counts": {},
        "query_texts": [r.get("query") for r in rows],
        "query_results": [],
    }
    if not EXA_API_KEY:
        diagnostics["error"] = "missing_exa_api_key"
        return [], diagnostics
    # Exa news fetch: full generation uses at least 8 neural results per query
    # for better concept coverage; single-card refill keeps its smaller limit.
    per_query = AI_UPDATES_SINGLE_EXA_RESULTS_PER_QUERY if single else max(8, AI_UPDATES_EXA_RESULTS_PER_QUERY)
    headers = {"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY}

    # Fetches fetch row from the configured external source.
    def fetch_row(row: dict):
        # Exa per-source configuration: official tool sites are usually blog or
        # changelog pages, so category="news" is only enabled for aggregator
        # sources that publish actual news articles.
        use_news_category = bool(row.get("use_news_category"))
        script_style = bool(row.get("exa_script_style"))
        row_num_results = max(1, int(row.get("exa_num_results") or per_query))
        # Performs the exa request helper step.
        def exa_request_once(query: str, *, num_results: int, start_published_date: str = "") -> tuple[list[dict], str, str]:
            request_query = clean_text(query) if script_style else freshness_query(query)
            payload = {
                "query": request_query,
                "numResults": num_results,
                # Exa news fetch: neural search improves official announcement
                # matching when companies use varied launch/update wording.
                "type": row.get("exa_search_type") or "neural",
                # Exa highlights are enforced for every news query so downstream
                # LLM payloads receive the most relevant sentence-level evidence.
                # CHANGE (2026-07-12): script_style requests (the official
                # per-tool lane - ~65-90% of all shortlisted candidates) used
                # to request text=False/highlights=False, so those candidates
                # reached normalize_candidate() with an empty "content" field
                # (Exa returned no body text, and for items accepted via
                # "official_domain_exa_date" - no live-page fetch happens
                # either, since the date was already confirmed from Exa's own
                # metadata). That empty content then got truncated to
                # nothing for the rewrite step, which correctly refuses to
                # write a grounded card with no source material and drops
                # the item - traced as the main cause of raw_selected (~20-40
                # per stage) collapsing to a handful of final cards despite a
                # healthy 65-90 candidate shortlist. Always request text so
                # every accepted candidate carries real body text.
                "contents": {"text": True, "highlights": True},
            }
            if start_published_date:
                payload["startPublishedDate"] = start_published_date
            elif not script_style:
                payload["startPublishedDate"] = recency_cutoff_query_token()
            if use_news_category:
                payload["category"] = "news"
            last_error = ""
            attempts = max(1, AI_UPDATES_EXA_RETRIES + 1)
            for attempt in range(attempts):
                try:
                    response = requests.post(
                        "https://api.exa.ai/search",
                        headers=headers,
                        json=payload,
                        timeout=AI_UPDATES_EXA_TIMEOUT,
                    )
                    if response.status_code < 400:
                        data = response.json()
                        return list(data.get("results") or [])[:num_results], "", payload["query"]
                    last_error = exa_http_error(response)
                    retry_after = response.headers.get("Retry-After", "")
                    should_retry = response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
                except requests.exceptions.Timeout as exc:
                    last_error = f"exa_request_failed:{exc}"
                    retry_after = ""
                    should_retry = True
                except Exception as exc:
                    return [], f"exa_request_failed:{exc}", payload["query"]
                if attempt >= attempts - 1 or not should_retry:
                    return [], last_error, payload["query"]
                try:
                    delay = float(retry_after) if retry_after else AI_UPDATES_EXA_RETRY_BACKOFF_SECONDS * (attempt + 1)
                except Exception:
                    delay = AI_UPDATES_EXA_RETRY_BACKOFF_SECONDS * (attempt + 1)
                time.sleep(max(0.5, min(delay, 8)))
            return [], last_error or "exa_request_failed:unknown", payload["query"]

        # Official-tool-update (script_style) queries used to never ask Exa's
        # own index to filter by date at all, relying entirely on scraping the
        # landing page afterwards - which is exactly how stale evergreen pages
        # (2023 blog posts, generic index pages) kept outranking real recent
        # updates. Verified live: adding startPublishedDate to these queries
        # returns genuinely fresh, Exa-dated results (docs/release-notes
        # pages with real publishedDate values) instead. Some quiet tools
        # legitimately have nothing in the window, so fall back to the
        # unfiltered query (still gated by our own HTML/date verification
        # downstream) rather than returning nothing for that tool.
        def exa_request(query: str, *, num_results: int, start_published_date: str = "") -> tuple[list[dict], str, str]:
            if not script_style:
                return exa_request_once(query, num_results=num_results, start_published_date=start_published_date)
            dated_results, dated_error, dated_query = exa_request_once(
                query, num_results=num_results, start_published_date=start_published_date or recency_cutoff_query_token()
            )
            if dated_results or dated_error:
                return dated_results, dated_error, dated_query
            return exa_request_once(query, num_results=num_results)

        # Prepares normalize raw results so downstream stages receive consistent data.
        def normalize_raw_results(raw_results: list[dict], *, query: str, fetch_method: str) -> tuple[list[dict], int]:
            items = []
            rejected_count = 0
            for raw in raw_results:
                item = normalize_candidate(raw, query=query, bucket=row.get("bucket") or "general", source="exa", single=single)
                if item:
                    reject_reason = tool_query_reject_reason(row, item)
                    if reject_reason:
                        if fetch_method == "exa_recent_verified" and query_site_domains(query):
                            item.setdefault("candidate_flags", []).append(reject_reason)
                        else:
                            rejected_count += 1
                            continue
                        # FETCHER PERMISSIVE MODE: keep tool-mismatch results
                        # as candidates and let later filters/model decide.
                else:
                    rejected_count += 1
                if item:
                    # RESULT TAGGING: Track which official-site fallback produced
                    # the candidate so weak saved sites can be audited later.
                    if row.get("official_site"):
                        item["fetch_method"] = fetch_method
                    item["source_lane"] = row.get("source_lane") or (
                        "official_exa" if row.get("query_mix") == "verified_exa_recent_tool_update"
                        else "fallback_broad" if row.get("query_mix") == "exa_product_update_broad"
                        else "tracker" if row.get("layer") or row.get("aggregator_source")
                        else item.get("source_lane") or ""
                    )
                    if item.get("source_lane") == "trusted_media_exa":
                        item.setdefault("acceptance_reason", "trusted_media_exa_result")
                        item.setdefault("date_confidence", "exa" if item.get("published") or item.get("published_date") else "")
                    for key in (
                        "source_type",
                        "tool",
                        "company",
                        "query_mix",
                        "layer",
                        "aggregator_source",
                        "official_domain",
                        "trusted_media_name",
                        "trusted_media_domain",
                    ):
                        if row.get(key) is not None:
                            item[key] = row.get(key)
                if item and not result_is_excluded(item, exclude_items):
                    items.append(item)
                elif item:
                    rejected_count += 1
            return items, rejected_count

        if script_style and row.get("source_type") == "exa_recent_tool_updates_style":
            now = utc_now()
            cutoff = now - timedelta(days=AI_UPDATES_LOOKBACK_DAYS)
            tool_name = clean_text(row.get("tool") or row.get("company") or "")
            official_site = official_site_token(row.get("official_site") or "")
            official_domain = row.get("official_domain") or root_site_token(row.get("official_site") or "")
            raw_count_total = 0
            rejected_count = 0
            pages_checked = 0
            accepted_items: list[dict] = []
            strategy_reports: list[dict] = []
            phase_reports: list[dict] = []
            rejection_audit: list[dict] = []

            for strategy in exa_recent_build_search_strategies(tool_name, official_site, official_domain):
                strategy_items: list[dict] = []
                successful_phase = None
                for phase in strategy["phases"]:
                    phase_query = phase["query"]
                    raw_results, error, executed_query = exa_request(phase_query, num_results=row_num_results)
                    raw_count_total += len(raw_results)
                    phase_audit = {
                        "strategy": phase["strategy"],
                        "phase": phase["phase"],
                        "query": phase_query,
                        "executed_query": executed_query,
                        "raw_count": len(raw_results),
                        "accepted_count": 0,
                        "error": error,
                    }
                    phase_reports.append(phase_audit)
                    if error:
                        rejected_count += 1
                        rejection_audit.append({
                            "strategy": phase["strategy"],
                            "phase": phase["phase"],
                            "query": phase_query,
                            "reason": error,
                        })
                        continue

                    phase_items: list[dict] = []
                    for raw in raw_results:
                        url = str(raw.get("url") or "").strip()
                        title = clean_text(raw.get("title") or "")
                        pages_checked += 1
                        if not url:
                            rejected_count += 1
                            rejection_audit.append({
                                "title": title,
                                "url": "",
                                "strategy": phase["strategy"],
                                "phase": phase["phase"],
                                "reason": "missing_url",
                            })
                            continue

                        is_official_url = official_domain_matches(url, official_domain)
                        raw_date_value = exa_raw_date(raw)
                        update_like = official_update_like(raw, url=url, title=title)
                        date_value = None
                        date_source = ""
                        final_url = url
                        acceptance_reason = ""
                        date_confidence = ""

                        if is_official_url and raw_date_value:
                            if raw_date_value < cutoff:
                                rejected_count += 1
                                rejection_audit.append({
                                    "title": title,
                                    "url": url,
                                    "date": raw_date_value.isoformat(),
                                    "date_source": "exa_publishedDate",
                                    "strategy": phase["strategy"],
                                    "phase": phase["phase"],
                                    "reason": "outside_last_7_days",
                                })
                                continue
                            date_value = raw_date_value
                            date_source = "exa_publishedDate"
                            acceptance_reason = "official_domain_exa_date"
                            date_confidence = "exa"
                        elif is_official_url and update_like:
                            if not (EXA_RECENT_MAX_PAGES_PER_TOOL and pages_checked > EXA_RECENT_MAX_PAGES_PER_TOOL):
                                page_date, page_date_source, reason, page_final_url = exa_recent_verify_date_details(url)
                                final_url = page_final_url or url
                                if page_date and page_date >= cutoff:
                                    date_value = page_date
                                    date_source = page_date_source
                                    acceptance_reason = "official_domain_page_date"
                                    date_confidence = "verified"
                                elif page_date and page_date < cutoff:
                                    rejected_count += 1
                                    rejection_audit.append({
                                        "title": title,
                                        "url": url,
                                        "final_url": final_url,
                                        "date": page_date.isoformat(),
                                        "date_source": page_date_source,
                                        "strategy": phase["strategy"],
                                        "phase": phase["phase"],
                                        "reason": "outside_last_7_days",
                                    })
                                    continue
                                else:
                                    # exa_recent_verify_date_details already tried JSON-LD,
                                    # meta tags, <time>, Last-Modified header, relative-time
                                    # text, hub-page newest-entry resolution, and sitemap
                                    # lastmod. No signal surviving all of that is a real
                                    # "can't verify recency" case, not a page-parsing gap -
                                    # reject instead of soft-accepting an unverified page.
                                    rejected_count += 1
                                    rejection_audit.append({
                                        "title": title,
                                        "url": url,
                                        "final_url": final_url,
                                        "strategy": phase["strategy"],
                                        "phase": phase["phase"],
                                        "reason": reason or "no_verified_date",
                                    })
                                    continue
                            else:
                                rejection_audit.append({
                                    "title": title,
                                    "url": url,
                                    "strategy": phase["strategy"],
                                    "phase": phase["phase"],
                                    "reason": "max_pages_per_tool_reached",
                                    "accepted_by_soft_official_rule": True,
                                })
                                acceptance_reason = "official_domain_update_like_page_budget"
                                date_confidence = "low"
                        else:
                            if EXA_RECENT_MAX_PAGES_PER_TOOL and pages_checked > EXA_RECENT_MAX_PAGES_PER_TOOL:
                                rejected_count += 1
                                rejection_audit.append({
                                    "title": title,
                                    "url": url,
                                    "strategy": phase["strategy"],
                                    "phase": phase["phase"],
                                    "reason": "max_pages_per_tool_reached",
                                })
                                break
                            date_value, date_source, reason, final_url = exa_recent_verify_date_details(url)
                            if reason:
                                rejected_count += 1
                                rejection_audit.append({
                                    "title": title,
                                    "url": url,
                                    "final_url": final_url,
                                    "strategy": phase["strategy"],
                                    "phase": phase["phase"],
                                    "reason": reason,
                                })
                                continue
                            if not date_value:
                                rejected_count += 1
                                rejection_audit.append({
                                    "title": title,
                                    "url": url,
                                    "final_url": final_url,
                                    "strategy": phase["strategy"],
                                    "phase": phase["phase"],
                                    "reason": "no_verified_date",
                                })
                                continue
                            if date_value < cutoff:
                                rejected_count += 1
                                rejection_audit.append({
                                    "title": title,
                                    "url": url,
                                    "final_url": final_url,
                                    "date": date_value.isoformat(),
                                    "date_source": date_source,
                                    "strategy": phase["strategy"],
                                    "phase": phase["phase"],
                                    "reason": "outside_last_7_days",
                                })
                                continue
                            acceptance_reason = "strict_page_date"
                            date_confidence = "verified"

                        if not is_official_url and not date_value:
                            rejected_count += 1
                            rejection_audit.append({
                                "title": title,
                                "url": url,
                                "final_url": final_url,
                                "strategy": phase["strategy"],
                                "phase": phase["phase"],
                                "reason": "no_verified_date",
                            })
                            continue

                        verified_raw = dict(raw)
                        verified_raw["url"] = final_url or url
                        if date_value:
                            verified_raw["publishedDate"] = date_value.isoformat()
                        verified_items, verified_rejected = normalize_raw_results(
                            [verified_raw],
                            query=phase_query,
                            fetch_method="exa_recent_verified",
                        )
                        rejected_count += verified_rejected
                        for item in verified_items:
                            item["fetch_method"] = "exa_recent_verified"
                            item["source_lane"] = "official_exa" if is_official_url else item.get("source_lane") or ""
                            item["date_confidence"] = date_confidence
                            item["acceptance_reason"] = acceptance_reason
                            item["is_official_company_source"] = bool(is_official_url)
                            if date_value:
                                item["verified_published_date"] = date_value.isoformat()
                            item["verified_date_source"] = date_source
                            item["exa_recent_strategy"] = phase["strategy"]
                            item["exa_recent_phase"] = phase["phase"]
                            item["official_site"] = official_site
                            item["official_domain"] = official_domain
                            phase_items.append(item)
                    if phase_items:
                        successful_phase = phase["phase"]
                        strategy_items.extend(phase_items)
                        phase_audit["accepted_count"] = len(phase_items)
                        break
                strategy_reports.append({
                    "strategy": strategy["strategy"],
                    "successful_phase": successful_phase,
                    "accepted_count": len(strategy_items),
                })
                accepted_items.extend(strategy_items)

            unique_items = []
            seen_urls = set()
            for item in accepted_items:
                key = canonical_news_url(item.get("url") or "", keep_query=True)
                if not key or key in seen_urls:
                    continue
                seen_urls.add(key)
                unique_items.append(item)

            query_audit = {
                "source": "exa",
                "query": row.get("query") or "",
                "executed_query": "verified_exa_recent_tool_updates",
                "raw_count": raw_count_total,
                "accepted_count": len(unique_items),
                "rejected_count": rejected_count,
                "query_mix": row.get("query_mix") or "",
                "source_lane": row.get("source_lane") or "official_exa",
                "official_accepted_count": len([item for item in unique_items if item.get("source_lane") == "official_exa"]),
                "official_rejected_count": len([item for item in rejection_audit if not item.get("accepted_by_soft_official_rule")]),
                "tool": tool_name,
                "company": row.get("company") or "",
                "official_site": official_site,
                "official_domain": official_domain,
                "official_site_missing": bool(row.get("official_site_missing")),
                "layer": row.get("layer") or "",
                "use_news_category": use_news_category,
                "aggregator_source": row.get("aggregator_source") or "",
                "bucket": row.get("bucket") or "",
                "exa_script_style": script_style,
                "fetch_method": "exa_recent_verified",
                "pages_checked": pages_checked,
                "window": {"days": AI_UPDATES_LOOKBACK_DAYS, "start": cutoff.isoformat(), "end": now.isoformat()},
                "phases": phase_reports,
                "strategy_reports": strategy_reports,
                "rejections": rejection_audit[:80],
                "results": summarize_items(unique_items, limit=row_num_results),
            }
            return row, unique_items, raw_count_total, "", query_audit

        raw_results, error, executed_query = exa_request(row["query"], num_results=row_num_results)
        if error:
            return row, [], 0, error, []
        if script_style:
            keep_results = max(1, int(row.get("exa_keep_results") or row_num_results))

            def result_timestamp(raw: dict) -> float:
                parsed = parse_result_datetime(raw.get("publishedDate") or raw.get("date") or "")
                if not parsed:
                    return 0.0
                try:
                    return float(parsed.timestamp())
                except Exception:
                    return 0.0

            raw_results = sorted(raw_results, key=result_timestamp, reverse=True)[:keep_results]
        items, rejected_count = normalize_raw_results(raw_results, query=row["query"], fetch_method="official_direct")
        raw_count_total = len(raw_results)
        fallback_audit: list[dict] = []
        accepted_items = [item for item in items if not item.get("tool_query_reject_reason")]

        # This fallback chain (simplified Exa query -> root-domain Exa query ->
        # open SearXNG search) used to be skipped entirely for script_style
        # rows (the primary official-tool-update lane), so a tool that found
        # nothing on its first Exa query had no rescue path at all. Now runs
        # for every row type; exa_request() already handles its own
        # startPublishedDate/no-date fallback internally per call.
        if row.get("official_site") and not accepted_items:
            tool_name = clean_text(row.get("tool") or "")
            official_site = canonical_official_site(row.get("official_site") or "")
            official_root = official_site.split("/", 1)[0] if official_site else ""

            # FALLBACK 1: Remove keyword restrictions from Exa query.
            # Reason: Some official pages say "shipped", "improved", or use
            # product-specific wording that the announcement keyword bank misses.
            if tool_name and official_site:
                simplified_query = (
                    f'site:{official_site} "{tool_name}" '
                    '(update OR updates OR changelog OR "release notes" OR "what\'s new" OR "new feature" OR release OR launch OR rollout)'
                )
                fallback_raw, fallback_error, fallback_executed = exa_request(simplified_query, num_results=3)
                fallback_items, fallback_rejected = normalize_raw_results(
                    fallback_raw,
                    query=simplified_query,
                    fetch_method="official_simplified",
                )
                raw_count_total += len(fallback_raw)
                rejected_count += fallback_rejected
                fallback_audit.append({
                    "fetch_method": "official_simplified",
                    "query": simplified_query,
                    "executed_query": fallback_executed,
                    "raw_count": len(fallback_raw),
                    "accepted_count": len(fallback_items),
                    "error": fallback_error,
                })
                accepted_fallback_items = [item for item in fallback_items if not item.get("tool_query_reject_reason")]
                if accepted_fallback_items:
                    items = fallback_items
                    accepted_items = accepted_fallback_items

            # FALLBACK 2: Try root domain when specific path fails.
            # Reason: Some official pages are indexed under the root domain even
            # when the saved changelog/newsroom subpath has no direct matches.
            if tool_name and official_root and not accepted_items:
                root_query = (
                    f'site:{official_root} "{tool_name}" '
                    '(update OR updates OR changelog OR "release notes" OR "what\'s new" OR "new feature" OR release OR launch OR rollout)'
                )
                fallback_raw, fallback_error, fallback_executed = exa_request(root_query, num_results=3)
                fallback_items, fallback_rejected = normalize_raw_results(
                    fallback_raw,
                    query=root_query,
                    fetch_method="root_domain",
                )
                raw_count_total += len(fallback_raw)
                rejected_count += fallback_rejected
                fallback_audit.append({
                    "fetch_method": "root_domain",
                    "query": root_query,
                    "executed_query": fallback_executed,
                    "raw_count": len(fallback_raw),
                    "accepted_count": len(fallback_items),
                    "error": fallback_error,
                })
                accepted_fallback_items = [item for item in fallback_items if not item.get("tool_query_reject_reason")]
                if accepted_fallback_items:
                    items = fallback_items
                    accepted_items = accepted_fallback_items

            # FALLBACK 3: Remove site: restriction from SearXNG.
            # Reason: If official pages are not indexed by Exa, open web search
            # can still find fresh tool updates that mention the product.
            if tool_name and not accepted_items:
                web_query = f'"{tool_name}" update OR changelog OR "new feature" OR release OR launch OR rollout'
                try:
                    sx_response = requests.get(
                        search_url(),
                        params={
                            "q": web_query,
                            "format": "json",
                            "language": "en",
                            "engines": SEARXNG_RELIABLE_ENGINES,
                            "time_range": "month",
                            "categories": AI_UPDATES_SEARXNG_CATEGORIES,
                            "pageno": 1,
                        },
                        timeout=AI_UPDATES_SEARXNG_TIMEOUT,
                    )
                    sx_response.raise_for_status()
                    sx_raw_results = list((sx_response.json() or {}).get("results") or [])[:3]
                    sx_error = ""
                except Exception as exc:
                    sx_raw_results = []
                    sx_error = f"searxng_fallback_failed:{exc}"
                sx_items = []
                sx_rejected = 0
                update_signal = re.compile(r"\b(update|updates|updated|changelog|release|released|new feature|launch|launched|announces|announced)\b", re.I)
                tool_signal = normalized_text(tool_name)
                for raw in sx_raw_results:
                    text = normalized_text(f"{raw.get('title') or ''} {raw.get('content') or raw.get('snippet') or ''}")
                    item = normalize_candidate(
                        raw,
                        query=web_query,
                        bucket=row.get("bucket") or "general",
                        source="searxng",
                        single=single,
                        recency_days=30,
                    )
                    if item:
                        # FETCHER PERMISSIVE MODE: web fallback signals are
                        # advisory flags, not hard rejects before GPT.
                        if tool_signal and tool_signal not in text:
                            item.setdefault("candidate_flags", []).append("web_search_missing_tool_signal")
                        if not update_signal.search(text):
                            item.setdefault("candidate_flags", []).append("web_search_missing_update_signal")
                        reject_reason = tool_query_reject_reason(row, item)
                        if reject_reason:
                            item["tool_query_reject_reason"] = reject_reason
                            item.setdefault("candidate_flags", []).append(reject_reason)
                    else:
                        sx_rejected += 1
                    if item:
                        # RESULT TAGGING: Web-search fallbacks are deliberately
                        # tagged so they do not masquerade as official-site hits.
                        item["fetch_method"] = "web_search"
                        for key in ("source_type", "tool", "company", "query_mix", "layer", "aggregator_source"):
                            if row.get(key) is not None:
                                item[key] = row.get(key)
                    if item and not result_is_excluded(item, exclude_items):
                        sx_items.append(item)
                    elif item:
                        sx_rejected += 1
                raw_count_total += len(sx_raw_results)
                rejected_count += sx_rejected
                fallback_audit.append({
                    "fetch_method": "web_search",
                    "query": web_query,
                    "executed_query": web_query,
                    "raw_count": len(sx_raw_results),
                    "accepted_count": len(sx_items),
                    "error": sx_error,
                })
                if sx_items:
                    items = sx_items

        if row.get("official_site") and not items:
            fallback_audit.append({
                "fetch_method": "unreachable",
                "query": row.get("query") or "",
                "executed_query": executed_query,
                "raw_count": 0,
                "accepted_count": 0,
                "error": "",
            })
        query_audit = {
            "source": "exa",
            "query": row.get("query") or "",
            "executed_query": executed_query,
            "raw_count": raw_count_total,
            "accepted_count": len(items),
            "rejected_count": rejected_count,
            "fallbacks": fallback_audit,
            "query_mix": row.get("query_mix") or "",
            "source_lane": row.get("source_lane") or "",
            "official_accepted_count": len([item for item in items if item.get("source_lane") == "official_exa"]),
            "trusted_media_accepted_count": len([item for item in items if item.get("source_lane") == "trusted_media_exa"]),
            "fallback_accepted_count": len([item for item in items if item.get("source_lane") in {"fallback_broad", "tracker"}]),
            "tool": row.get("tool") or "",
            "company": row.get("company") or "",
            "official_site": row.get("official_site") or "",
            "trusted_media_name": row.get("trusted_media_name") or "",
            "trusted_media_domain": row.get("trusted_media_domain") or "",
            "official_site_missing": bool(row.get("official_site_missing")),
            "layer": row.get("layer") or "",
            "use_news_category": use_news_category,
            "aggregator_source": row.get("aggregator_source") or "",
            "bucket": row.get("bucket") or "",
            "exa_script_style": script_style,
            "results": summarize_items(items, limit=row_num_results),
        }
        return row, items, raw_count_total, "", query_audit

    started = time.time()
    output = []
    seen = set()
    max_workers = max(1, min(len(rows), AI_UPDATES_EXA_MAX_WORKERS))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_row, row) for row in rows]
        for future in as_completed(futures):
            row, items, raw_count, error, query_audit = future.result()
            diagnostics["raw_results"] += raw_count
            diagnostics["query_counts"][row.get("query") or ""] = raw_count
            if error:
                diagnostics.setdefault("errors", []).append(error[:220])
                diagnostics["query_results"].append({
                    "source": "exa",
                    "query": row.get("query") or "",
                    "raw_count": raw_count,
                    "accepted_count": 0,
                    "rejected_count": 0,
                    "error": error[:500],
                    "query_mix": row.get("query_mix") or "",
                    "source_lane": row.get("source_lane") or "",
                    "tool": row.get("tool") or "",
                    "company": row.get("company") or "",
                    "official_site": row.get("official_site") or "",
                    "trusted_media_name": row.get("trusted_media_name") or "",
                    "trusted_media_domain": row.get("trusted_media_domain") or "",
                    "official_site_missing": bool(row.get("official_site_missing")),
                    "layer": row.get("layer") or "",
                    "use_news_category": bool(row.get("use_news_category")),
                    "aggregator_source": row.get("aggregator_source") or "",
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
    if not output and diagnostics.get("errors"):
        diagnostics["error"] = diagnostics.get("errors", ["exa_request_failed"])[0].split(":", 1)[0]
    # Tool activity signal: which tools this batch actually queried via the
    # official-tool-update rows, and which of those produced an accepted
    # official-domain result. The orchestrator feeds this into
    # tools_aware.apply_tool_activity_signal so a tool's score reflects real
    # weekly evidence instead of a one-shot 60-day silence check.
    diagnostics["tool_activity_queried"] = sorted({
        str(row.get("tool") or "").strip()
        for row in rows
        if row.get("tool") and row.get("query_mix") == "verified_exa_recent_tool_update"
    })
    diagnostics["tool_activity_seen"] = sorted({
        str(item.get("tool") or "").strip()
        for item in output
        if item.get("tool") and item.get("source_lane") == "official_exa"
    })
    log_event(
        "source.exa.finished",
        queries=len(rows),
        raw_results=diagnostics["raw_results"],
        unique_results=len(output),
        seconds=diagnostics["seconds"],
        max_workers=diagnostics.get("max_workers"),
        retries=diagnostics.get("retries"),
        timeout=diagnostics.get("timeout"),
        errors=diagnostics.get("errors", [])[:8],
        query_counts=diagnostics.get("query_counts", {}),
        sample=summarize_items(output, limit=6),
    )
    return output, diagnostics

# Performs the combine source results helper step.

__all__ = [name for name in globals() if not name.startswith("__")]
