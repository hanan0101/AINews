# This file is part of the AI newsletter system.
"""Shared constants and low-level helpers for news discovery.

Content-specific fetching is split across queries, normalization,
SearXNG, Exa, tracker, merge, and runtime modules.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from backend.config.settings import (
    AI_UPDATES_EXA_QUERY_LIMIT,
    AI_UPDATES_EXA_MAX_WORKERS,
    AI_UPDATES_EXA_RESULTS_PER_QUERY,
    AI_UPDATES_EXA_RETRIES,
    AI_UPDATES_EXA_RETRY_BACKOFF_SECONDS,
    AI_UPDATES_EXA_TIMEOUT,
    AI_UPDATES_LOOKBACK_DAYS,
    env_bool,
    AI_UPDATES_SEARXNG_CATEGORIES,
    AI_UPDATES_SEARXNG_MAX_WORKERS,
    AI_UPDATES_SEARXNG_QUERY_LIMIT,
    AI_UPDATES_SEARXNG_RESULTS_PER_QUERY,
    AI_UPDATES_SEARXNG_TIME_RANGE,
    AI_UPDATES_SEARXNG_TIMEOUT,
    AI_UPDATES_SINGLE_EXA_QUERY_LIMIT,
    AI_UPDATES_SINGLE_EXA_RESULTS_PER_QUERY,
    AI_UPDATES_SINGLE_RESULTS_PER_QUERY,
    AI_UPDATES_SINGLE_SEARXNG_QUERY_LIMIT,
    AI_UPDATES_SINGLE_TIMEOUT,
    EXA_API_KEY,
    MONTHLY_TOOLS_FILE,
    NEWS_FETCH_STATE_FILE,
    NEWS_SECTORS,
    SECTOR_TERMS_HISTORY_FILE,
    clean_text,
    domain_matches,
    env_int,
    load_json,
    memory_url_key,
    normalized_text,
    official_site_domain,
    parse_result_datetime,
    recency_cutoff_query_token,
    result_is_recent_enough,
    rotation_state,
    rotation_window,
    safe_write_json,
    save_rotation_state,
    source_domain,
    utc_now,
)
from backend.logging.pipeline_logging import log_event, summarize_items
from backend.pipeline.fetching.fetch_utils import (
    PAGE_FETCH_USER_AGENT,
    SEARXNG_RELIABLE_ENGINES,
    exa_http_error,
    query_site_domain_matches_url,
    query_site_domains,
    safe_print,
)
from backend.pipeline.tool_discovery.official_sites import canonical_official_site
from backend.pipeline.tool_discovery.queries import (
    BUSINESS_ONLY_TERMS,
    GENERAL_NEWS_EXA_ROWS,
    GENERAL_NEWS_SEARXNG_ROWS,
    ensure_ai_scope,
    search_url,
    strict_searxng_ai_product_query,
    text_has_any,
)
from backend.pipeline.tool_discovery.tools_aware import build_tool_queries, load_monthly_tool_records, tool_group
from backend.pipeline.filtering.content.news.editorial import annotate_news_candidate


AI_UPDATES_TOOL_QUERY_ROTATION_POOL = env_int("AI_UPDATES_TOOL_QUERY_ROTATION_POOL", "48")
AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT = max(
    1,
    env_int("AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT", str(AI_UPDATES_TOOL_QUERY_ROTATION_POOL)),
)
# Raised 2026-07 from 6 to 15: SearXNG is self-hosted (no per-query API
# cost, ~0.6-0.75s/query per scripts/test_searxng_health.py), so a bigger
# per-run budget is close to free - unlike Exa, which costs real API
# credit per query and stays capped separately. Combined with the rotation
# fix above, the full registry gets touched roughly every 3 runs instead
# of the same 6 tools forever.
AI_UPDATES_SEARXNG_TOOL_QUERY_LIMIT = max(1, env_int("AI_UPDATES_SEARXNG_TOOL_QUERY_LIMIT", "15"))
AI_UPDATES_GENERAL_NEWS_LAYER_ENABLED = env_bool("AI_UPDATES_GENERAL_NEWS_LAYER_ENABLED", "0")
AI_UPDATES_TRACKER_DISCOVERY_LAYER_ENABLED = env_bool("AI_UPDATES_TRACKER_DISCOVERY_LAYER_ENABLED", "1")
AI_UPDATES_TRACKER_RUN_WHEN_PRIMARY_BELOW = max(
    0,
    env_int("AI_UPDATES_TRACKER_RUN_WHEN_PRIMARY_BELOW", "45"),
)

APP_STORE_DOMAINS = ("apps.apple.com", "play.google.com")


def parse_candidate_datetime(value: object):
    """Parse a discovery date into a timezone-aware UTC datetime."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = date_parser.parse(text, fuzzy=True)
    except (TypeError, ValueError, OverflowError):
        return None
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_news_url(url: str = "", *, keep_query: bool = False) -> str:
    """Return a stable news URL key, optionally preserving its query."""
    parsed = urlparse(str(url or "").strip())
    if not parsed.netloc:
        return ""
    scheme = (parsed.scheme or "https").lower()
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    base = f"{scheme}://{host}{path}"
    return f"{base}?{parsed.query}" if keep_query and parsed.query else base

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

EXA_PRODUCT_UPDATE_BROAD_QUERIES = (
    "AI product update launched new feature users can now",
    "AI tool now available beta launched official changelog",
    "AI agent workflow automation new feature product update",
    "AI assistant new capability available for teams workspace enterprise",
    "creative AI tool product update image video design launched",
    "AI search assistant research assistant new feature product update",
    "AI productivity tool documents email slides spreadsheet new feature",
    "AI platform launches agent builder no-code automation tool",
    "AI video image generation tool changelog new model available",
)

TRUSTED_MEDIA_SOURCES = (
    {"name": "TechCrunch", "domain": "techcrunch.com"},
    {"name": "The Verge", "domain": "theverge.com"},
    {"name": "VentureBeat", "domain": "venturebeat.com"},
    {"name": "ZDNet", "domain": "zdnet.com"},
    {"name": "The Decoder", "domain": "the-decoder.com"},
    {"name": "TNW", "domain": "thenextweb.com"},
    {"name": "Neowin", "domain": "neowin.net"},
    {"name": "UC Today", "domain": "uctoday.com"},
    # Widened 2026-07: real general_news_layer runs showed the 8-domain list
    # rejecting ~44% of otherwise-valid candidates (verified via
    # ai_updates_query_results.json domain audit). Added established global
    # tech/AI/business outlets plus a couple of domains that actually
    # surfaced relevant AI coverage in that audit (SiliconANGLE, HPCwire,
    # Google Cloud's own blog).
    {"name": "Wired", "domain": "wired.com"},
    {"name": "Ars Technica", "domain": "arstechnica.com"},
    {"name": "Engadget", "domain": "engadget.com"},
    {"name": "MIT Technology Review", "domain": "technologyreview.com"},
    {"name": "Fast Company", "domain": "fastcompany.com"},
    {"name": "Axios", "domain": "axios.com"},
    {"name": "SiliconANGLE", "domain": "siliconangle.com"},
    {"name": "HPCwire", "domain": "hpcwire.com"},
    {"name": "Reuters", "domain": "reuters.com"},
    {"name": "Bloomberg", "domain": "bloomberg.com"},
    {"name": "CNBC", "domain": "cnbc.com"},
    {"name": "Business Insider", "domain": "businessinsider.com"},
    {"name": "Google Cloud Blog", "domain": "cloud.google.com"},
)

TRUSTED_MEDIA_TOOL_QUERY_TEMPLATES = (
    'site:{trusted_domain} "{tool}" AI launches',
    'site:{trusted_domain} "{tool}" AI "new feature"',
    'site:{trusted_domain} "{tool}" AI "now available"',
)

TRUSTED_MEDIA_EXA_QUERY_LIMIT = max(0, env_int("AI_UPDATES_TRUSTED_MEDIA_EXA_QUERY_LIMIT", "8"))
TRUSTED_MEDIA_SINGLE_EXA_QUERY_LIMIT = max(0, env_int("AI_UPDATES_TRUSTED_MEDIA_SINGLE_EXA_QUERY_LIMIT", "6"))

# CHANGE: SearXNG broad queries are stricter than Exa broad queries.
# Reason: SearXNG matches literal keywords, so each broad query must require
# AI context + an announcement action + a product/tool signal to reduce noise
# from unrelated pages such as politics, shipping, car news, or shopping deals.
SEARXNG_STRICT_GENERAL_AI_UPDATE_ROWS = [
    {"bucket": "general_update", "query": '"AI tool" AND ("new feature" OR "product update" OR "just launched")'},
    {"bucket": "general_update", "query": '"artificial intelligence" AND ("launches" OR "announces") AND ("tool" OR "platform" OR "product")'},
    # Use "rolls out" instead of the maritime-ambiguous word "ships".
    {"bucket": "general_update", "query": '"AI model" AND ("now available" OR "generally available" OR "rolls out")'},
    {"bucket": "general_assistant", "query": '"AI assistant" AND ("update" OR "new feature" OR "rolling out")'},
    {"bucket": "general_update", "query": '"AI" AND ("releases" OR "introducing") AND ("feature" OR "capability" OR "tool")'},
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

BROAD_SEARXNG_ROWS = []

AI_DISCOVERY_TRACKER_QUERIES = [
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

SAUDI_AI_TRACKER_QUERIES = [
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
    "last.fm",
    "lastminute.com",
    "zoominfo.com",
    "leadiq.com",
)

# AI Security Layer 1 (hard gate): reject SSRF-shaped and malformed links
# before any candidate is fetched, parsed, or stored. Checked at the top of
# every function that does requests.get(url, ...) on a candidate's own URL,
# and again inside normalize_candidate() for the URL that ends up stored.
ALLOWED_URL_SCHEMES = {"http", "https"}

# Hostnames/suffixes that never point to a legitimate public news source.
# Suffix matching mirrors domain_blocked()'s "== or endswith('.'+blocked)"
# convention below, so "local"/"internal" also cover subdomains like
# metadata.google.internal without needing every metadata hostname listed.
SSRF_BLOCKED_HOST_PATTERNS = (
    "localhost",
    "local",
    "internal",
)

# Punycode (xn--) hosts are rejected by default (homograph-lookalike risk).
# Empty on purpose - add a specific host here only if a real source needs it.
SSRF_ALLOWED_PUNYCODE_HOSTS: tuple[str, ...] = ()


def url_safety_reject_reason(url: str) -> str:
    """Hard SSRF/malformed-link gate. Empty string means the URL is safe to fetch."""
    raw = str(url or "").strip()
    if not raw:
        return "missing_url"
    try:
        parsed = urlparse(raw)
    except Exception:
        return "unparseable_url"
    if (parsed.scheme or "").lower() not in ALLOWED_URL_SCHEMES:
        return "disallowed_url_scheme"
    if parsed.username or parsed.password:
        return "url_contains_userinfo"
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return "missing_host"
    try:
        ipaddress.ip_address(hostname)
        return "raw_ip_literal_host"
    except ValueError:
        pass
    if any(hostname == blocked or hostname.endswith(f".{blocked}") for blocked in SSRF_BLOCKED_HOST_PATTERNS):
        return "blocked_internal_host"
    if hostname not in SSRF_ALLOWED_PUNYCODE_HOSTS and any(label.startswith("xn--") for label in hostname.split(".")):
        return "punycode_host_not_allowlisted"
    return ""


# AI Security Layer 1 (neutralize, not reject): fetched article text can
# carry instruction-shaped spans aimed at a later AI step (prompt injection).
# Only the matched span is replaced - the rest of the article still proceeds
# through the pipeline. English + Arabic patterns per the reviewed design.
INJECTION_NEUTRALIZED_PLACEHOLDER = "[محتوى محذوف]"

INJECTION_SPAN_PATTERNS = (
    ("ignore_previous_instructions", re.compile(r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+instructions", re.IGNORECASE)),
    ("disregard_instructions", re.compile(r"disregard\s+.{0,40}?instructions", re.IGNORECASE)),
    ("system_role_marker", re.compile(r"system\s*:", re.IGNORECASE)),
    ("you_are_now", re.compile(r"you\s+are\s+now\b", re.IGNORECASE)),
    ("ar_ignore_previous_instructions", re.compile(r"تجاهل\s+التعليمات\s+السابقة")),
    ("ar_you_are_now", re.compile(r"أنت\s+الآن")),
)


def neutralize_injection_spans(text: str) -> tuple[str, list[dict]]:
    """Strip prompt-injection-shaped spans from fetched text; keep the rest intact."""
    value = str(text or "")
    matches: list[dict] = []
    for pattern_name, pattern in INJECTION_SPAN_PATTERNS:
        def _replace(match: re.Match, _name: str = pattern_name) -> str:
            matches.append({"pattern": _name, "span_length": len(match.group(0))})
            return INJECTION_NEUTRALIZED_PLACEHOLDER
        value = pattern.sub(_replace, value)
    return value, matches


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

# Editorial policy: reject narrow/local availability even when the restriction
# appears only inside the article body, not in the headline.
GEOGRAPHICALLY_LIMITED_TERMS = (
    "available in the us",
    "available in the u.s.",
    "available only in the us",
    "available only in the u.s.",
    "us only",
    "u.s. only",
    "united states only",
    "in the united states only",
    "for us users",
    "for u.s. users",
    "for users in the united states",
    "rolling out in the us",
    "rolling out in the u.s.",
    "rolling out first in the us",
    "rolling out first in the u.s.",
    "starting in the us",
    "starting in the u.s.",
    "limited to the us",
    "limited to the u.s.",
    "currently available in the us",
    "currently available in the u.s.",
    "available in the uk",
    "rolling out first in the uk",
    "available in india",
    "mainland china",
)

# Editorial policy: low-value consumer-platform updates are usually app/user
# notices rather than strong AI newsletter items, so block them before GPT.
LOW_VALUE_CONSUMER_PLATFORM_TERMS = (
    "facebook",
    "facebook users",
    "facebook app",
    "meta facebook",
    "android users",
    "android app",
    "android apps",
    "android phones",
    "android devices",
    "android update",
    "google play",
    "play store",
)

# Official-domain quality gate: a company domain is not automatically a good
# news source. Forum/docs/help/cookbook/GitHub-release pages often match
# site:company.com queries but are not editorial product-update articles.
BAD_NEWS_HOST_PREFIXES = (
    "forum.",
    "community.",
    "support.",
    "help.",
    "privacy.",
    "answers.",
    "discuss.",
)

BAD_NEWS_DOMAINS = (
    "newreleases.io",
    "github.com",
    "github.io",
    "gist.github.com",
)

BAD_NEWS_PATH_TERMS = (
    "/forum/",
    "/community/",
    "/discussions/",
    "/discussion/",
    "/questions/",
    "/answers/",
    "/support/",
    "/help/",
    "/cookbook/",
    "/examples/",
    "/example/",
    "/api/",
    "/reference/",
    "/bug",
    "/issues/",
    "/issue/",
    "/jobs/",
    "/careers/",
    "/tutorial",
    "/tutorials",
    "/course",
    "/courses",
    "/download",
    "/downloads",
    "/install",
    "/installation",
    "/pricing",
    "/privacy",
    "/login",
    "/signin",
    "/sign-in",
)

DOCS_NEWS_HOST_PREFIXES = (
    "docs.",
    "developer.",
    "developers.",
)

REAL_RELEASE_PATH_TERMS = (
    "changelog",
    "release-notes",
    "release_notes",
    "releases",
    "whats-new",
    "what-is-new",
    "updates",
    "announcements",
)

BAD_NEWS_TEXT_TERMS = (
    "bug report",
    "bug reports",
    "community forum",
    "forum post",
    "support article",
    "help article",
    "privacy center",
    "unexpected error",
    "api reference",
    "developer documentation",
    "cookbook",
    "job board",
    "job posting",
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
    # 2026-07-18: exact-substring matching missed the -ing/-s verb forms
    # that real launch headlines actually use ("Introducing Claude Opus 4.8"
    # has none of the terms above) - confirmed live: that page is on
    # anthropic.com, Claude's registered official_site, but got rejected by
    # result_looks_like_update() purely for this reason.
    "introducing",
    "announces",
    "announcing",
    "unveils",
    "unveiling",
)


def result_looks_like_update(title: str = "", url: str = "", content: str = "") -> bool:
    text = f"{title} {url} {content}"
    if text_has_any(text, UPDATE_TERMS):
        return True
    path = normalized_text(urlparse(str(url or "")).path.replace("/", " "))
    return text_has_any(path, UPDATE_TERMS)

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
    "youtube",
    "video tutorial",
    "online course",
    "free course",
    "download",
    "download app",
    "install",
    "installation guide",
    "is down",
    " down on ",
    "outage",
    "status update",
    "ipo",
    "public-market",
    "public market",
    "stock",
    "share price",
    "budget",
    "conference",
    "expo",
    "summit",
    "event",
)

SEARXNG_NEGATIVE_QUERY_TERMS = (
    "video",
    "repository",
    "documentation",
    "login",
    "pricing",
)

SEARXNG_HARD_REJECT_FLAGS = {
    "domain_blocked",
    "noise_terms",
    "bad_page_type_github_or_release_mirror",
    "bad_page_type_forum_or_support_subdomain",
    "bad_page_type_docs_not_release_notes",
    "bad_page_type_path_not_news",
    "bad_page_type_text_not_news",
}

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

DEVELOPER_NEWS_DOMAINS = (
    "github.blog",
    "github.com",
    "devblogs.microsoft.com",
    "developers.googleblog.com",
    "developer.nvidia.com",
    "docs.anthropic.com",
    "platform.openai.com",
)

DEVELOPER_NEWS_TERMS = (
    "vs code",
    "visual studio code",
    "github copilot",
    "copilot chat",
    "coding agent",
    "code agent",
    "developer",
    "developers",
    "api",
    "sdk",
    "cli",
    "mcp",
    "model context protocol",
    "ide",
    "pull request",
    "repository",
    "release notes",
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


# Returns whether has arabic text is true for the current input.

__all__ = [name for name in globals() if not name.startswith("__")]
