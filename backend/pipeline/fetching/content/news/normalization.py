"""News discovery: candidate normalization and source rejection."""

from .common import *
from .queries import *

def freshness_query(query: str) -> str:
    query = query.strip()
    cutoff = recency_cutoff_query_token()
    year = str(utc_now().year)
    if "after:" not in query.lower():
        query = f"{query} after:{cutoff}"
    if year not in query:
        query = f"{query} {year}"
    return query


# Performs the domain blocked helper step.
# Adds negative search terms that keep SearXNG away from tutorial/download pages.
def searxng_fetch_query(query: str) -> str:
    query = freshness_query(strict_searxng_ai_product_query(query))
    lower = f" {query.lower()} "
    negatives = [f"-{term}" for term in SEARXNG_NEGATIVE_QUERY_TERMS if f"-{term}" not in lower]
    return " ".join([query, *negatives]).strip()


def domain_blocked(domain: str) -> bool:
    return any(domain == blocked or domain.endswith(f".{blocked}") for blocked in DISALLOWED_SOURCE_DOMAINS)


# Performs the official page type reject reason helper step.
def official_page_type_reject_reason(item: dict) -> str:
    """Reject bad page types that sneak in through official site: queries.

    Official domains can still return forums, docs, cookbook examples, support
    pages, jobs, or GitHub release mirrors. Those are not newsletter-quality
    product-update articles unless the page is explicitly a changelog/release
    note/update page.
    """
    raw_url = str((item or {}).get("url") or (item or {}).get("source_url") or "").strip()
    if not raw_url:
        return ""
    parsed = urlparse(raw_url if re.match(r"^https?://", raw_url, flags=re.I) else f"https://{raw_url}")
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").lower()
    domain = source_domain(raw_url)
    text = " ".join(
        str((item or {}).get(key) or "")
        for key in ("title", "content", "summary", "text", "snippet")
    ).lower()
    has_release_path = any(term in path for term in REAL_RELEASE_PATH_TERMS)

    if any(domain == bad or domain.endswith(f".{bad}") for bad in BAD_NEWS_DOMAINS):
        return "bad_page_type_github_or_release_mirror"
    if any(host.startswith(prefix) for prefix in BAD_NEWS_HOST_PREFIXES):
        return "bad_page_type_forum_or_support_subdomain"
    if (host.startswith(DOCS_NEWS_HOST_PREFIXES) or "/docs/" in path) and not has_release_path:
        return "bad_page_type_docs_not_release_notes"
    if any(term in path for term in BAD_NEWS_PATH_TERMS) and not has_release_path:
        return "bad_page_type_path_not_news"
    if text_has_any(text, BAD_NEWS_TEXT_TERMS) and not has_release_path:
        return "bad_page_type_text_not_news"
    return ""


# Performs the source candidate hard reject reason helper step.
def source_candidate_hard_reject_reason(item: dict) -> str:
    domain = source_domain((item or {}).get("url") or (item or {}).get("source_url") or "")
    if any(domain == blocked or domain.endswith(f".{blocked}") for blocked in APP_STORE_DOMAINS):
        return "app_store_listing_not_news_source"
    page_type_reason = official_page_type_reject_reason(item)
    if page_type_reason:
        return page_type_reason
    text = " ".join(
        str((item or {}).get(key) or "")
        for key in ("title", "content", "summary", "text", "snippet", "url", "source_domain")
    )
    # Editorial policy: block country-limited/local app stories and low-value
    # consumer-platform notices before they reach GPT.
    if text_has_whole_term(text, LOCAL_OR_UNKNOWN_APP_TERMS):
        return "local_or_narrow_availability"
    if text_has_any(text, GEOGRAPHICALLY_LIMITED_TERMS):
        return "country_limited_availability"
    if text_has_any(text, LOW_VALUE_CONSUMER_PLATFORM_TERMS):
        return "low_value_consumer_platform_update"
    normalized = normalized_text(text)
    if domain_matches(domain, DEVELOPER_NEWS_DOMAINS) and any(term in normalized for term in DEVELOPER_NEWS_TERMS):
        return "developer_tool_update_not_newsletter_fit"
    return ""


# Performs the tool query reject reason helper step.
def tool_query_reject_reason(row: dict, item: dict) -> str:
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


# Performs the text has whole term helper step.
def text_has_whole_term(text: str, terms: tuple[str, ...]) -> bool:
    lower = text.lower()
    for term in terms:
        pattern = r"\b" + re.escape(term.lower()).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pattern, lower):
            return True
    return False


MONTH_NUMBER = {
    "jan": "01",
    "january": "01",
    "feb": "02",
    "february": "02",
    "mar": "03",
    "march": "03",
    "apr": "04",
    "april": "04",
    "may": "05",
    "jun": "06",
    "june": "06",
    "jul": "07",
    "july": "07",
    "aug": "08",
    "august": "08",
    "sep": "09",
    "sept": "09",
    "september": "09",
    "oct": "10",
    "october": "10",
    "nov": "11",
    "november": "11",
    "dec": "12",
    "december": "12",
}


# Performs the inferred date from text helper step.
def inferred_date_from_text(text: str = "") -> str:
    """Extract obvious publication dates embedded in result titles or URLs."""
    blob = str(text or "")
    match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", blob)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    match = re.search(
        r"\b("
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?|tember)?|oct(?:ober)?|"
        r"nov(?:ember)?|dec(?:ember)?"
        r")\s+(\d{1,2}),?\s+(20\d{2})\b",
        blob,
        flags=re.IGNORECASE,
    )
    if match:
        month_name, day, year = match.groups()
        month = MONTH_NUMBER.get(month_name.lower()[:3]) or MONTH_NUMBER.get(month_name.lower())
        if month:
            return f"{year}-{month}-{int(day):02d}"
    # FETCHER PERMISSIVE MODE: infer common blog-title dates so freshness can be
    # checked later in filters.py instead of rejecting useful official posts here.
    match = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+("
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?|tember)?|oct(?:ober)?|"
        r"nov(?:ember)?|dec(?:ember)?"
        r")\s*[-,]?\s*(20\d{2})\b",
        blob,
        flags=re.IGNORECASE,
    )
    if match:
        day, month_name, year = match.groups()
        month = MONTH_NUMBER.get(month_name.lower()[:3]) or MONTH_NUMBER.get(month_name.lower())
        if month:
            return f"{year}-{month}-{int(day):02d}"
    return ""


# Returns whether has known company signal is true for the current input.
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


# Performs the infer sector helper step.
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
    return "الذكاء الاصطناعي والتعليم"
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


# Performs the flag weak sectors helper step.
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


# Performs the update sector terms helper step.
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


def normalize_candidate(raw: dict, *, query: str, bucket: str, source: str, single: bool = False, recency_days: int | None = None) -> dict | None:
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
    if not query_site_domain_matches_url(query, url):
        return None
    domain = source_domain(url)
    text = f"{title} {content}"
    date_evidence = f"{title} {url}"
    candidate_flags = []
    # FETCHER PERMISSIVE MODE: do not editorially reject raw search hits here.
    # Reason: fetchers.py should collect candidates; filters.py handles old
    # items/dedupe and the model makes the final relevance/editorial decision.
    hard_reason = source_candidate_hard_reject_reason({"url": url, "title": title, "content": content, "source_domain": domain})
    if hard_reason:
        return None
    if domain_blocked(domain):
        return None
    if text_has_any(text, NOISE_TERMS):
        candidate_flags.append("noise_terms")
    if text_has_any(text, TECHNICAL_ONLY_TERMS):
        candidate_flags.append("technical_only_terms")
    if text_has_any(text, BUSINESS_ONLY_TERMS):
        candidate_flags.append("business_only_terms")
    known_signal = has_known_company_signal(text, domain)
    if text_has_whole_term(text, LOCAL_OR_UNKNOWN_APP_TERMS):
        candidate_flags.append("local_or_unknown_app_terms")
    if text_has_any(text, GEOGRAPHICALLY_LIMITED_TERMS):
        candidate_flags.append("geographically_limited_terms")
    if text_has_any(text, LOW_VALUE_CONSUMER_PLATFORM_TERMS):
        candidate_flags.append("low_value_consumer_platform_terms")
    published_raw = raw.get("publishedDate") or raw.get("published_date") or raw.get("pubdate") or raw.get("date") or ""
    inferred_date = ""
    if not published_raw:
        inferred_date = inferred_date_from_text(date_evidence)
    # FETCHER PERMISSIVE MODE: freshness is recorded, not enforced. filters.py
    # removes explicitly old news after cross-source candidates are merged.
    effective_published = published_raw or inferred_date
    if published_raw and not result_is_recent_enough(published_raw):
        candidate_flags.append("date_outside_lookback_window")
    elif inferred_date and not result_is_recent_enough(inferred_date):
        candidate_flags.append("inferred_date_outside_lookback_window")
    elif not effective_published:
        candidate_flags.append("missing_published_date")
    published_dt = parse_result_datetime(effective_published)
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
        "published_raw": str(effective_published or ""),
        "recency_window_days": recency_days or AI_UPDATES_LOOKBACK_DAYS,
        "known_company_signal": bool(known_signal),
        "candidate_flags": sorted(set(candidate_flags)),
        "fetcher_permissive": True,
    }
    item.update(annotate_news_candidate(item))
    item["owner_key"] = candidate_owner_key(item, url=url, title=title, content=content)
    item["legacy_story_key"] = hashlib.sha1(f"{domain}|{normalized_text(title)[:120]}".encode("utf-8")).hexdigest()[:24]
    return item


# Performs the result is excluded helper step.
def result_is_excluded(item: dict, exclude_items: list[dict] | None = None) -> bool:
    if not exclude_items:
        return False
    url = memory_url_key(item.get("url") or "")
    title = normalized_text(item.get("title") or "")
    text = normalized_text(f"{item.get('title') or ''} {item.get('content') or item.get('summary') or ''}")

    # Performs the topic tokens helper step.
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


SEARXNG_DISCOVERY_PAGE_TIMEOUT = env_int("AI_UPDATES_SEARXNG_DISCOVERY_PAGE_TIMEOUT", "12")
SEARXNG_DISCOVERY_FETCH_RESULTS = env_int("AI_UPDATES_SEARXNG_DISCOVERY_FETCH_RESULTS", "12")
SEARXNG_DISCOVERY_MAX_PAGES_PER_TOOL = env_int("AI_UPDATES_SEARXNG_DISCOVERY_MAX_PAGES_PER_TOOL", "12")
SEARXNG_DISCOVERY_HUB_PATH_TERMS = ("changelog", "releases", "whats-new")

__all__ = [name for name in globals() if not name.startswith("__")]
