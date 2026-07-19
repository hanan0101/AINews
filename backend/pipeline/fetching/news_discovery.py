# This file is part of the AI newsletter system.
"""Live news discovery: Exa/SearXNG query building, source fetching, and
candidate normalization for the news pipeline.

This file owns discovery only — it leaves final editorial judgment to the
modeling stage. Course and film fetching live in their own files
(`fetching/courses.py`, `fetching/films.py`); they import a handful of
generic low-level helpers from here (HTTP/text utilities), not news logic.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import quote, urlparse

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
    AI_UPDATES_COURSE_EXA_QUERY_LIMIT,
    AI_UPDATES_COURSE_EXA_RESULTS_PER_QUERY,
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
    COURSE_INCLUDE_DOMAINS,
    COURSE_QUERY,
    COURSE_QUERY_VARIANTS,
    CURRENT_YEAR_START,
    EXA_API_KEY,
    MONTHLY_TOOLS_FILE,
    NEWS_FETCH_STATE_FILE,
    NEWS_SECTORS,
    SECTOR_TERMS_HISTORY_FILE,
    SEARXNG_URL,
    TMDB_API_KEY,
    clean_text,
    env_int,
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
from backend.logging.pipeline_logging import log_event, summarize_items
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
from backend.pipeline.fetching.course_bank import upsert_course_bank
from backend.pipeline.filtering.editorial_rules import annotate_news_candidate


def safe_print(message: str) -> None:
    """Print safely when stdout is redirected through a narrow Windows encoding."""
    text = str(message)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")
    print(safe_text, flush=True)


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
AI_UPDATES_COURSE_EXA_ALLOW_OUTSIDE_INCLUDE_DOMAINS = env_bool("AI_UPDATES_COURSE_EXA_ALLOW_OUTSIDE_INCLUDE_DOMAINS", "1")
AI_UPDATES_GENERAL_NEWS_LAYER_ENABLED = env_bool("AI_UPDATES_GENERAL_NEWS_LAYER_ENABLED", "0")
AI_UPDATES_TRACKER_DISCOVERY_LAYER_ENABLED = env_bool("AI_UPDATES_TRACKER_DISCOVERY_LAYER_ENABLED", "1")
AI_UPDATES_TRACKER_RUN_WHEN_PRIMARY_BELOW = max(
    0,
    env_int("AI_UPDATES_TRACKER_RUN_WHEN_PRIMARY_BELOW", "45"),
)

APP_STORE_DOMAINS = ("apps.apple.com", "play.google.com")

# Brave/Startpage/DuckDuckGo are currently CAPTCHA/rate-limited on this
# self-hosted SearXNG instance (confirmed live testing 2026-07). Every
# SearXNG request in this module should request only the engines that are
# actually answering right now; the others stay enabled in
# searxng/settings.yml so SearXNG itself can use them once unblocked.
SEARXNG_RELIABLE_ENGINES = (os.getenv("AI_UPDATES_SEARXNG_ENGINES") or "google,bing").strip()

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


def official_site_domain(site: str = "") -> str:
    value = str(site or "").strip()
    if not value:
        return ""
    if not re.match(r"^https?://", value, flags=re.IGNORECASE):
        value = f"https://{value}"
    return source_domain(value)


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
def has_arabic_text(value: str = "") -> bool:
    return bool(re.search(r"[\u0600-\u06ff]", str(value or "")))


# Performs the unique full query rows helper step.
def unique_full_query_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for row in rows:
        query = clean_text(row.get("query") or "") if row.get("tool_query_required") else ensure_ai_scope(row.get("query") or "")
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


def root_site_token(site: str = "") -> str:
    value = str(site or "").strip().replace("https://", "").replace("http://", "").strip("/")
    if not value:
        return ""
    parsed = urlparse(f"https://{value}")
    return (parsed.netloc or value.split("/", 1)[0]).lower().removeprefix("www.")


def official_site_token(site: str = "") -> str:
    return canonical_official_site(site or "")


def trusted_media_exa_rows(tools: list[dict], *, single: bool = False) -> list[dict]:
    limit = TRUSTED_MEDIA_SINGLE_EXA_QUERY_LIMIT if single else TRUSTED_MEDIA_EXA_QUERY_LIMIT
    if limit <= 0:
        return []
    rows = []
    for tool in tools:
        tool_name = clean_text(tool.get("tool") or tool.get("company") or "")
        if not tool_name:
            continue
        for media in TRUSTED_MEDIA_SOURCES:
            trusted_domain = media["domain"]
            for template in TRUSTED_MEDIA_TOOL_QUERY_TEMPLATES:
                query = template.format(trusted_domain=trusted_domain, tool=tool_name)
                rows.append({
                    "query": query,
                    "bucket": "trusted_media_tool_update",
                    "query_mix": "trusted_media_tool_update",
                    "source_lane": "trusted_media_exa",
                    "source_type": "exa_trusted_media_tool_update",
                    "tool_query_variant": "trusted_media_tool_ai_update",
                    "tool": tool_name,
                    "company": clean_text(tool.get("company") or ""),
                    "trusted_media_name": media["name"],
                    "trusted_media_domain": trusted_domain,
                    "exa_num_results": 5 if single else 8,
                    "use_news_category": True,
                })
                if len(rows) >= limit:
                    return rows
    return rows


# Performs the next exa tool rotation offset helper step.
# Unlike SearXNG's tool-driven rows (see next_news_query_rotation), the Exa
# official-tool-update rows used to always take the same top-N tools by
# popularity_score every cycle and every run. This mirrors the same
# load/advance/persist pattern against NEWS_FETCH_STATE_FILE so each cycle
# covers a different slice of the pool once it grows past batch_size.
def next_tool_rotation_offset(pool_size: int, batch_size: int, *, state_key: str = "exa_tool_driven_rotation") -> int:
    if pool_size <= 0:
        return 0
    state = load_json(NEWS_FETCH_STATE_FILE, {})
    rotation = state.get(state_key) if isinstance(state.get(state_key), dict) else {}
    offset = int(rotation.get("next_offset") or 0) % pool_size
    state[state_key] = {
        "updated_at": utc_now().isoformat(),
        "offset": offset,
        "pool_size": pool_size,
        "batch_size": batch_size,
        "next_offset": (offset + max(1, batch_size)) % pool_size,
    }
    safe_write_json(NEWS_FETCH_STATE_FILE, state)
    return offset


# Kept as a thin alias: existing call sites and the persisted state-file key
# (exa_tool_driven_rotation) predate the searxng rotation fix below and
# should not shift on upgrade.
def next_exa_tool_rotation_offset(pool_size: int, batch_size: int) -> int:
    return next_tool_rotation_offset(pool_size, batch_size, state_key="exa_tool_driven_rotation")


def exa_tool_update_script_rows(*, single: bool = False, cycle: int = 1) -> tuple[list[dict], list[dict]]:
    limit = AI_UPDATES_SINGLE_EXA_QUERY_LIMIT if single else AI_UPDATES_EXA_QUERY_LIMIT
    tool_limit = 6 if single else max(limit, AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT)
    if single:
        tools = load_monthly_tool_records(limit=tool_limit)
        cycle_tool_limit = 6
    else:
        # Pull a pool larger than one cycle's query budget so there is
        # something real to rotate through; falls back gracefully to the
        # same static top-N behavior while the registry stays small.
        pool = load_monthly_tool_records(limit=max(tool_limit * 4, 160))
        # CHANGE: while the tool registry is smaller than the configured
        # rotation batch (AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT, default 48),
        # every cycle took tools[:48] = the whole pool regardless of the
        # rotation offset, so cycle 1 and cycle 2 of the same run fetched
        # ~the same candidates twice (hit in production 2026-07-11: 41-tool
        # registry, 229 vs 215 nearly-identical unique results per cycle).
        # Splitting the CURRENT pool across this run's cycles makes each
        # cycle query a genuinely different slice; the cap at
        # AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT still applies once the
        # registry grows large enough that a 48-tool slice no longer risks
        # cross-cycle overlap.
        cycles_per_run = max(1, min(2, env_int("AI_UPDATES_NEWS_FETCH_CYCLES", "2")))
        cycle_tool_limit = min(AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT, max(1, math.ceil(len(pool) / cycles_per_run))) if pool else AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT
        offset = next_exa_tool_rotation_offset(len(pool), cycle_tool_limit)
        tools = rotate_list(pool, offset)
    rows = []
    official_tools = tools[:cycle_tool_limit]
    for tool in official_tools:
        tool_name = clean_text(tool.get("tool") or tool.get("company") or "")
        if not tool_name:
            continue
        official_site = official_site_token(tool.get("official_site") or "")
        official_domain = root_site_token(tool.get("official_site") or "")
        # CHANGE: the single word "update" biases Exa's neural ranking toward
        # help-center "Release Notes" index pages (which list dozens of small
        # changes and get correctly rejected downstream as roundup/aggregator
        # pages) and away from genuine flagship launch posts that use
        # different language ("Introducing...", "GPT-5.6: Frontier
        # intelligence...") - verified live 2026-07-11: this narrow query
        # missed OpenAI's actual GPT-5.6 launch post entirely, while adding
        # launch-style verbs and excluding the help subdomain surfaced it
        # (and xAI's "Introducing Grok 4.5", Cursor's dedicated changelog
        # entries) directly. -site: is Exa-supported query syntax, same as
        # site:.
        help_exclusion = f' -site:help.{official_domain} -site:support.{official_domain}' if official_domain else ""
        query = (
            f'site:{official_domain}{help_exclusion} "{tool_name}" '
            f'(update OR launch OR launches OR introducing OR unveils OR announces OR "now available")'
            if official_domain else
            f'"{tool_name}" (update OR launch OR launches OR introducing OR unveils OR announces OR "now available")'
        )
        rows.append({
            "query": query,
            "bucket": "official_tool_update",
            "query_mix": "verified_exa_recent_tool_update",
            "source_lane": "official_exa",
            "source_type": "exa_recent_tool_updates_style",
            "tool_query_variant": "tool_name_update_verified_site_search",
            "tool": tool_name,
            "company": clean_text(tool.get("company") or ""),
            "official_site": official_site,
            "official_domain": official_domain,
            "exa_script_style": True,
            "exa_num_results": 5 if single else 8,
            "exa_keep_results": 3 if single else 4,
        })
    rows.extend(trusted_media_exa_rows(tools, single=single))
    # CHANGE: these 9 queries carry no per-tool/per-cycle variable (unlike
    # the tool-rotation and trusted-media rows above), so re-running them on
    # cycle 2+ of the same run returns byte-identical results to cycle 1 -
    # verified live 2026-07-11 (same 4 URLs, same order, for the same query
    # string in both cycles). That wastes half of cycle 2's Exa query budget
    # on zero new information. Only run them on the first cycle of a run;
    # rotated tool coverage already grows on later cycles.
    broad_queries = list(EXA_PRODUCT_UPDATE_BROAD_QUERIES[:3] if single else EXA_PRODUCT_UPDATE_BROAD_QUERIES) if cycle <= 1 else []
    for query in broad_queries:
        rows.append({
            "query": query,
            "bucket": "general_update",
            "query_mix": "exa_product_update_broad",
            "source_lane": "fallback_broad",
            "source_type": "exa_product_update_broad",
            "tool_query_variant": "product_update_broad",
            "exa_num_results": 6 if single else 12,
            "use_news_category": False,
        })
    return rows, tools


# Builds compose query mix rows for the next pipeline or API step.
def compose_query_mix_rows(
    tool_rows: list[dict],
    specialized_rows: list[dict],
    broad_rows: list[dict],
    limit: int,
    *,
    fixed_budgets: dict[str, int] | None = None,
) -> tuple[list[dict], dict]:
    """Apply the intended 50/30/20 query mix without making it a result quota."""
    limit = max(1, int(limit or 1))
    if fixed_budgets:
        requested = {
            "tool_driven": max(0, int(fixed_budgets.get("tool_driven") or 0)),
            "specialized": max(0, int(fixed_budgets.get("specialized") or 0)),
            "broad": max(0, int(fixed_budgets.get("broad") or 0)),
        }
        budgets = {"tool_driven": 0, "specialized": 0, "broad": 0}
        remaining = limit
        for key in ("tool_driven", "specialized", "broad"):
            budgets[key] = min(requested[key], remaining)
            remaining -= budgets[key]
    else:
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


LAST_DISCOVERY_META: dict[str, dict] = {}

NEWS_QUERY_ANGLE_PROFILES = [
    {
        "name": "official_tool_updates",
        "keywords": ("release", "changelog", "official", "product", "general_market"),
        "budgets": {"tool_driven": 24, "specialized": 10, "broad": 3},
    },
    {
        "name": "culture_creative",
        "keywords": (
            "culture", "creative", "music", "audio", "voice", "film", "video",
            "design", "visual", "fashion", "writing", "literature", "archive",
            "heritage", "museum", "library",
        ),
        "budgets": {"tool_driven": 16, "specialized": 16, "broad": 5},
    },
    {
        "name": "daily_work_learning",
        "keywords": (
            "daily", "assistant", "shopping", "travel", "mobile", "personal",
            "work", "workflow", "productivity", "meeting", "document", "learning",
            "education", "health", "wellness", "cooking",
        ),
        "budgets": {"tool_driven": 16, "specialized": 14, "broad": 7},
    },
    {
        "name": "broad_market_scan",
        "keywords": ("impact", "market", "launch", "available", "rollout", "new ai"),
        "budgets": {"tool_driven": 14, "specialized": 8, "broad": 15},
    },
]


# Performs the rotate list helper step.
def rotate_list(items: list[dict], offset: int = 0) -> list[dict]:
    if not items:
        return []
    offset = int(offset or 0) % len(items)
    return list(items[offset:]) + list(items[:offset])


# Performs the row matches keywords helper step.
def row_matches_keywords(row: dict, keywords: tuple[str, ...]) -> bool:
    haystack = normalized_text(" ".join(str(row.get(key) or "") for key in (
        "bucket",
        "query",
        "tool",
        "company",
        "source_type",
        "tool_type",
        "sector",
        "sector_hint",
    )))
    return any(normalized_text(keyword) in haystack for keyword in keywords)


# Performs the prioritize angle rows helper step.
def prioritize_angle_rows(rows: list[dict], keywords: tuple[str, ...]) -> list[dict]:
    rows = list(rows or [])
    if not keywords:
        return rows
    matching = [row for row in rows if row_matches_keywords(row, keywords)]
    rest = [row for row in rows if not row_matches_keywords(row, keywords)]
    return matching + rest


# Performs the next news query rotation helper step.
def next_news_query_rotation(source: str, totals: dict[str, int]) -> tuple[dict, dict]:
    """Rotate full-generation search angles so consecutive runs explore different pools."""
    state = load_json(NEWS_FETCH_STATE_FILE, {})
    all_rotation = state.get("news_query_rotation") if isinstance(state.get("news_query_rotation"), dict) else {}
    previous = all_rotation.get(source) if isinstance(all_rotation.get(source), dict) else {}
    angle_index = int(previous.get("next_angle_index") or 0) % len(NEWS_QUERY_ANGLE_PROFILES)
    profile = NEWS_QUERY_ANGLE_PROFILES[angle_index]

    offsets = {
        "tool_driven": int(previous.get("next_tool_offset") or 0),
        "specialized": int(previous.get("next_specialized_offset") or 0),
        "broad": int(previous.get("next_broad_offset") or 0),
    }
    budgets = profile.get("budgets") or {}
    next_record = {
        "updated_at": utc_now().isoformat(),
        "source": source,
        "angle": profile.get("name") or "",
        "angle_index": angle_index,
        "next_angle_index": (angle_index + 1) % len(NEWS_QUERY_ANGLE_PROFILES),
        "tool_offset": offsets["tool_driven"],
        "specialized_offset": offsets["specialized"],
        "broad_offset": offsets["broad"],
        "next_tool_offset": (offsets["tool_driven"] + max(1, int(budgets.get("tool_driven") or 1))) % max(1, int(totals.get("tool_driven") or 1)),
        "next_specialized_offset": (offsets["specialized"] + max(1, int(budgets.get("specialized") or 1))) % max(1, int(totals.get("specialized") or 1)),
        "next_broad_offset": (offsets["broad"] + max(1, int(budgets.get("broad") or 1))) % max(1, int(totals.get("broad") or 1)),
        "totals": totals,
        "budgets": budgets,
    }
    all_rotation[source] = next_record
    state["news_query_rotation"] = all_rotation
    safe_write_json(NEWS_FETCH_STATE_FILE, state)
    return profile, next_record


# Performs the discovery rows helper step.
def discovery_rows(source: str, *, single: bool = False, target_hint: str = "", cycle: int = 1) -> list[dict]:
    """Return the final query rows for one provider.

    Full generation uses a larger query budget. Single refill uses the same
    discovery strategy with smaller limits and a target hint from the card.
    """
    if source == "searxng":
        limit = AI_UPDATES_SINGLE_SEARXNG_QUERY_LIMIT if single else AI_UPDATES_SEARXNG_QUERY_LIMIT
        searxng_limit = min(limit, 6 if single else AI_UPDATES_SEARXNG_TOOL_QUERY_LIMIT)
        if single:
            tools = load_monthly_tool_records(limit=searxng_limit)
        else:
            # CHANGE: SearXNG used to always take the same top-N tools by
            # popularity_score every run (no rotation), unlike Exa which
            # already rotates through the registry - so 35+ of the 41
            # registered tools never got a SearXNG query at all. Mirror
            # Exa's rotation here with its own offset/state key so the two
            # sources don't have to move in lockstep.
            pool = load_monthly_tool_records(limit=max(searxng_limit * 4, 160))
            offset = next_tool_rotation_offset(len(pool), searxng_limit, state_key="searxng_tool_driven_rotation")
            tools = rotate_list(pool, offset)
        rows = []
        for tool in tools[:searxng_limit]:
            tool_name = clean_text(tool.get("tool") or tool.get("company") or "")
            if not tool_name:
                continue
            # REVERTED 2026-07-11: tried mirroring Exa's site:+exclusions+OR
            # query here, but live results showed 23/24 SearXNG queries
            # returning raw_count=0 (including the one with no site:
            # restriction at all) - SearXNG scrapes Google's HTML rather
            # than using an official API, and a long, unusual boolean query
            # is much more likely to trip Google's bot detection into
            # serving an empty/challenge page than a real API would notice.
            # Back to the simple query that was actually verified to return
            # results (3-6 accepted per run).
            official_domain = root_site_token(tool.get("official_site") or "")
            query = f'"{tool_name}" update'
            rows.append({
                "query": query,
                "bucket": "searxng_url_discovery",
                "query_mix": "tool_name_update",
                "source_lane": "tool_searxng",
                "source_type": "searxng_url_discovery",
                "tool": tool_name,
                "company": clean_text(tool.get("company") or ""),
                "official_site": clean_text(tool.get("official_site") or ""),
                "official_domain": official_domain,
                "searxng_url_discovery_only": True,
            })
        LAST_DISCOVERY_META[source] = {
            "tool_count": len(tools),
            "official_tool_query_limit": AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT,
            "searxng_tool_query_limit": searxng_limit,
            "tool_names": [tool.get("tool") for tool in tools],
            "query_mix": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
            "tool_query_variant_rows": {"tool_name_update": sum(1 for row in rows if row.get("query_mix") == "tool_name_update")},
            "query_mix_budgets": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
            "query_angle": "searxng_tool_name_update",
            "single": bool(single),
        }
        return rows

    if source == "exa":
        rows, tools = exa_tool_update_script_rows(single=single, cycle=cycle)
        LAST_DISCOVERY_META[source] = {
            "tool_count": len(tools),
            "official_tool_query_limit": AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT,
            "tool_names": [tool.get("tool") for tool in tools],
            "tool_group_counts": dict(Counter(tool_group(tool) for tool in tools)),
            "query_mix": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
            "tool_query_variant_rows": dict(Counter(row.get("tool_query_variant") or "none" for row in rows)),
            "query_mix_budgets": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
            "trusted_media_sources": [source["domain"] for source in TRUSTED_MEDIA_SOURCES],
            "query_angle": "exa_recent_tool_updates_style",
            "single": bool(single),
        }
        return rows

    # CHANGE: Keep Exa on the original neural-friendly broad query bank, but
    # switch only SearXNG to strict AND-condition broad queries because SearXNG
    # is literal keyword search and needs tighter AI/action/product constraints.
    general_update_rows = SEARXNG_STRICT_GENERAL_AI_UPDATE_ROWS if source == "searxng" else GENERAL_AI_UPDATE_ROWS

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
            [MOTHER_QUERY_ROW, *general_update_rows, *broad],
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
    tools = load_monthly_tool_records(limit=max(24, AI_UPDATES_TOOL_QUERY_ROTATION_POOL))
    tool_queries = build_tool_queries(tools).get(source, [])
    full_query_budget = min(limit, 37)
    profile, rotation = next_news_query_rotation(
        source,
        {
            "tool_driven": len(tool_queries),
            "specialized": len(DEFAULT_QUERY_ROWS),
            "broad": len([MOTHER_QUERY_ROW, *general_update_rows, *broad]),
        },
    )
    keywords = tuple(profile.get("keywords") or ())
    tool_queries = rotate_list(prioritize_angle_rows(tool_queries, keywords), rotation.get("tool_offset"))
    specialized_rows = rotate_list(
        prioritize_angle_rows(DEFAULT_QUERY_ROWS, keywords),
        rotation.get("specialized_offset"),
    )
    broad_rows = rotate_list(
        prioritize_angle_rows([MOTHER_QUERY_ROW, *general_update_rows, *broad], keywords),
        rotation.get("broad_offset"),
    )
    rows, mix_meta = compose_query_mix_rows(
        tool_queries,
        specialized_rows,
        broad_rows,
        full_query_budget,
        fixed_budgets=profile.get("budgets") or {"tool_driven": 24, "specialized": 10, "broad": 3},
    )
    LAST_DISCOVERY_META[source] = {
        "tool_count": len(tools),
        "tool_names": [tool.get("tool") for tool in tools],
        "tool_group_counts": dict(Counter(tool_group(tool) for tool in tools)),
        "query_mix": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
        "tool_query_variant_rows": dict(Counter(row.get("tool_query_variant") or "none" for row in rows)),
        "query_mix_budgets": mix_meta.get("budgets", {}),
        "query_angle": profile.get("name") or "",
        "query_rotation": rotation,
        "single": False,
    }
    return rows


# Performs the freshness query helper step.
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


# Prepares normalize candidate so downstream stages receive consistent data.
def query_site_domains(query: str = "") -> set[str]:
    domains = set()
    for raw_site in re.findall(r"site:([^\s)\"']+)", str(query or ""), flags=re.IGNORECASE):
        site = raw_site.strip().rstrip(".,;")
        if not site:
            continue
        domain = source_domain(f"https://{site}")
        if domain:
            domains.add(domain)
    return domains


def query_site_domain_matches_url(query: str = "", url: str = "") -> bool:
    domains = query_site_domains(query)
    if not domains:
        return True
    result_domain = source_domain(url)
    if not result_domain:
        return False
    return any(result_domain == domain or result_domain.endswith(f".{domain}") for domain in domains)


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


def searxng_discovery_canonical_url(url: str = "") -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.netloc:
        return ""
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{scheme}://{host}{path}"


def searxng_discovery_parse_date(value: object):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = date_parser.parse(text, fuzzy=True)
    except Exception:
        return None
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# 2026-07-18: identifying as a bot in the User-Agent gets a real, measured
# share of page fetches 403'd or timed out by sites with basic bot blocking
# (confirmed live: 11 HTTPError + 3 ReadTimeout out of 144 SearXNG results in
# one run) - a browser UA is not deceptive here, it's what any reader's
# browser would send to load the same public page.
PAGE_FETCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


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
        date_value = searxng_discovery_parse_date(time_tag.get("datetime") if time_tag else "")
        if not date_value and time_tag:
            date_value = searxng_discovery_parse_date(time_tag.get_text(" ", strip=True))
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
            parsed = searxng_discovery_parse_date(item.get("datePublished"))
            if parsed:
                candidates.append({"date": parsed, "confidence": 10, "source": "json_ld_datePublished"})
    for attrs in ({"property": "article:published_time"}, {"name": "article:published_time"}):
        tag = soup.find("meta", attrs=attrs)
        parsed = searxng_discovery_parse_date(tag.get("content") if tag else "")
        if parsed:
            candidates.append({"date": parsed, "confidence": 9, "source": "meta_article_published_time"})
    for tag in soup.find_all("time"):
        if searxng_discovery_has_modified_context(tag):
            continue
        parsed = searxng_discovery_parse_date(tag.get("datetime") or "")
        if parsed:
            candidates.append({"date": parsed, "confidence": 7, "source": "time_datetime"})
    head_text = soup.get_text(" ", strip=True)[:2000]
    for match in re.finditer(r"\d{4}-\d{2}-\d{2}", head_text):
        context = head_text[max(0, match.start() - 40): match.end() + 40].lower()
        if "modified" in context or "updated" in context:
            continue
        parsed = searxng_discovery_parse_date(match.group(0))
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
                key=lambda item: searxng_discovery_parse_date(str(item.get("publishedDate") or item.get("date") or "")) or utc_now() - timedelta(days=3650),
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
                key = searxng_discovery_canonical_url(url)
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
                        entry_key = searxng_discovery_canonical_url(entry["url"])
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


def exa_recent_parse_date(value: object):
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
                parsed = exa_recent_parse_date(item.get(key))
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
        parsed = exa_recent_parse_date(tag.get("content") if tag else "")
        if parsed:
            return parsed
    return None


def exa_recent_date_from_time_tag(soup: BeautifulSoup):
    for tag in soup.find_all("time"):
        parsed = exa_recent_parse_date(tag.get("datetime") or tag.get_text(" ", strip=True))
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
            parsed = exa_recent_parse_date(match.group(0))
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
    return exa_recent_parse_date(header) if header else None


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
    canonical_target = exa_recent_canonical_url(url)
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
            if exa_recent_canonical_url(loc.get_text(strip=True)) != canonical_target:
                continue
            lastmod = entry.find("lastmod")
            parsed_date = exa_recent_parse_date(lastmod.get_text(strip=True) if lastmod else "")
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


def exa_recent_canonical_url(url: str = "") -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.netloc:
        return ""
    scheme = (parsed.scheme or "https").lower()
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{scheme}://{host}{path}?{parsed.query}" if parsed.query else f"{scheme}://{host}{path}"


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


def domain_matches(domain: str, allowed: tuple[str, ...] | list[str] | set[str]) -> bool:
    """Return true when a domain is equal to or under one of the allowed domains."""
    normalized_domain = str(domain or "").lower().removeprefix("www.")
    for allowed_domain in allowed or ():
        normalized_allowed = str(allowed_domain or "").lower().removeprefix("www.")
        if normalized_domain == normalized_allowed or normalized_domain.endswith(f".{normalized_allowed}"):
            return True
    return False


def exa_http_error(response: requests.Response) -> str:
    """Return a stable Exa error code without exposing request credentials."""
    status = getattr(response, "status_code", 0)
    if status == 402:
        body = ""
        try:
            body = response.text[:800]
        except Exception:
            body = ""
        lowered = body.lower()
        if "no_more_credits" in lowered or "credits limit" in lowered or "top up" in lowered:
            return "exa_no_credits:402"
        return "exa_billing_required:402"
    return f"exa_request_failed:{status}"


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
                key = exa_recent_canonical_url(item.get("url") or "")
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
def combine_source_results(source_results: list[tuple[str, list[dict], dict]], *, mode: str) -> tuple[list[dict], dict]:
    seen = set()
    output = []
    raw_results = 0
    total_queries = 0
    source_diagnostics = {}
    failures = {}
    failure_details = {}

    def similar_title_index(item: dict) -> int:
        title = normalized_text(item.get("title") or "")
        if not title:
            return -1
        for index, existing in enumerate(output):
            existing_title = normalized_text(existing.get("title") or "")
            if existing_title and SequenceMatcher(None, title, existing_title).ratio() > 0.80:
                return index
        return -1

    for source, items, diagnostics in source_results:
        source_diagnostics[source] = diagnostics
        raw_results += int(diagnostics.get("raw_results") or 0)
        total_queries += int(diagnostics.get("queries") or 0)
        if diagnostics.get("error"):
            failures[source] = diagnostics.get("error")
            source_errors = diagnostics.get("errors") if isinstance(diagnostics.get("errors"), list) else []
            failure_details[source] = diagnostics.get("exception") or (source_errors[:8] if source_errors else diagnostics.get("error"))
        for item in items:
            key = item.get("url") or ""
            if key in seen:
                continue
            similar_index = similar_title_index(item)
            if similar_index >= 0:
                existing = output[similar_index]
                if item.get("fetch_source") == "exa" and existing.get("fetch_source") != "exa":
                    if existing.get("url"):
                        seen.discard(existing.get("url"))
                    output[similar_index] = item
                    if key:
                        seen.add(key)
                continue
            seen.add(key)
            output.append(item)
    diagnostics = {
        "mode": mode,
        "sources": list(source_diagnostics.keys()),
        "source_diagnostics": source_diagnostics,
        "source_failures": failures,
        "source_failures_detail": failure_details,
        "queries": total_queries,
        "raw_results": raw_results,
        "unique_results": len(output),
        "source_candidate_counts": dict(Counter(item.get("fetch_source") or "unknown" for item in output)),
        "source_lane_counts": dict(Counter(item.get("source_lane") or "unknown" for item in output)),
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


# General news layer: runs after the existing tool-driven fetch and uses both
# Exa and SearXNG in parallel to catch unlisted AI tools, global AI events,
# Saudi/SDAIA news, and fixed aggregator sources.
# General-layer quality gate: this layer was disabled in production because
# its open-web broad queries (no site: restriction) surfaced low-quality
# marketing/SEO-farm content. Re-enabled with a trusted-domain allowlist
# instead of an open search - layer3 (saudi_ai_news) must match an official
# Saudi government domain or a known Saudi/regional trusted media outlet;
# layer1/layer2 (unlisted tools, global AI events) must match a known tech
# media outlet. Aggregator rows are already site:-scoped at the query level
# and pass through unfiltered.
def general_news_layer_domain_allowed(item: dict) -> bool:
    layer = str(item.get("layer") or "")
    if layer == "aggregator" or not layer:
        return True
    url = str(item.get("url") or item.get("official_url") or "")
    if not url:
        return False
    if layer == "layer3":
        allowlist = SAUDI_OFFICIAL_DOMAINS + SAUDI_TRUSTED_MEDIA_DOMAINS
    else:
        allowlist = tuple(source["domain"] for source in TRUSTED_MEDIA_SOURCES)
    return any(official_domain_matches(url, domain) for domain in allowlist)


def fetch_general_news_layer(*, exclude_items: list[dict] | None = None) -> tuple[list[dict], dict]:
    """Fetch non-tool-list AI news layers and return merged candidates."""
    started = time.time()
    source_results = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(fetch_exa_query_rows, GENERAL_NEWS_EXA_ROWS, exclude_items=exclude_items, single=False): "exa",
            executor.submit(fetch_searxng_query_rows, GENERAL_NEWS_SEARXNG_ROWS, exclude_items=exclude_items, single=False): "searxng",
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                items, diagnostics = future.result()
            except Exception as exc:
                items, diagnostics = [], {
                    "source": source,
                    "error": f"general_news_{source}_fetch_exception",
                    "exception": str(exc),
                    "queries": 0,
                    "raw_results": 0,
                    "query_results": [],
                }
            source_results.append((source, items, diagnostics))
    items, diagnostics = combine_source_results(source_results, mode="general_news_layer_parallel")
    pre_filter_count = len(items)
    items = [item for item in items if general_news_layer_domain_allowed(item)]
    diagnostics["domain_allowlist_rejected"] = pre_filter_count - len(items)
    diagnostics["unique_results"] = len(items)
    # Query audit flattening: expose the inner Exa/SearXNG query rows at this
    # layer level so ai_updates_query_results.json shows all general-layer
    # searches alongside the existing tool-driven searches.
    diagnostics["query_results"] = [
        query
        for source_diag in (diagnostics.get("source_diagnostics") or {}).values()
        if isinstance(source_diag, dict)
        for query in (source_diag.get("query_results") or [])
    ]
    diagnostics["layer_counts"] = dict(Counter(item.get("layer") or "unknown" for item in items))
    diagnostics["general_news_layer_seconds"] = round(time.time() - started, 2)
    log_event(
        "general_news_layer.finished",
        raw_results=diagnostics.get("raw_results", 0),
        unique_results=len(items),
        domain_allowlist_rejected=diagnostics["domain_allowlist_rejected"],
        seconds=diagnostics["general_news_layer_seconds"],
        layer_counts=diagnostics.get("layer_counts", {}),
        source_failures=diagnostics.get("source_failures", {}),
    )
    return items, diagnostics


TRACKER_RESULTS_PER_QUERY = env_int("AI_UPDATES_TRACKER_RESULTS_PER_QUERY", "8")
TRACKER_PAGE_TIMEOUT = env_int("AI_UPDATES_TRACKER_PAGE_TIMEOUT", "12")

TRACKER_LAUNCH_SIGNALS = (
    "introducing", "announcing", "launches", "unveils", "releases", "debuts",
    "open sources", "generally available", "now available", "public beta",
)
TRACKER_NOISE_INDICATORS = (
    "medium.com/@", "substack.com/p/", "reddit.com/r/", "linkedin.com/pulse",
    "opinion", "analysis", "explained", "how to", "tutorial", "guide", "review",
)
TRACKER_DEVELOPER_TERMS = (
    "github copilot", "vs code", "visual studio code", "api", "sdk", "coding agent",
    "developer tool", "developers", "framework", "library", "repository", "repo",
    "github", "cli", "ide", "code editor", "programming", "software development",
    "open source model", "benchmark", "inference", "fine-tuning", "deployment",
)
TRACKER_GENERAL_USER_DOMAINS = (
    "writing", "search", "meeting", "notes", "presentation", "design", "image",
    "video", "audio", "music", "productivity", "education", "learning", "tourism",
    "culture", "government service", "customer service", "workflow", "workspace",
    "document", "spreadsheet", "email", "browser",
)
TRACKER_USER_VALUE_TERMS = (
    "users can", "lets users", "helps users", "teams can", "customers can",
    "creators can", "teachers can", "students can", "now you can",
    "available to users", "for teams", "for creators", "for students",
    "for businesses", "for employees", "no-code", "without coding",
)

SAUDI_OFFICIAL_DOMAINS = (
    "spa.gov.sa", "sdaia.gov.sa", "ndmo.gov.sa", "mcit.gov.sa", "humain.ai",
    "my.gov.sa", "ai.gov.sa", "gov.sa", "mofa.gov.sa", "moh.gov.sa",
    "moe.gov.sa", "mt.gov.sa", "moc.gov.sa", "momrah.gov.sa", "mewa.gov.sa",
    "moenergy.gov.sa", "tourism.gov.sa",
)
SAUDI_TRUSTED_MEDIA_DOMAINS = (
    "arabnews.com", "saudigazette.com.sa", "argaam.com", "reuters.com", "bloomberg.com",
    "alarabiya.net", "aawsat.com", "asharqbusiness.com", "wamda.com", "zawya.com",
    "okaz.com.sa", "alriyadh.com", "spa.gov.sa", "leaders.com.sa", "tech-wd.com",
    # Widened 2026-07: confirmed via a real-run domain audit
    # (ai_updates_query_results.json) as established Saudi/Gulf outlets that
    # were being rejected despite carrying legitimate Saudi AI coverage.
    "sabq.org", "al-madina.com", "almowaten.net", "agbi.com", "fastcompanyme.com",
)
SAUDI_TERMS_TRACKER = (
    "saudi", "saudi arabia", "riyadh", "kingdom", "vision 2030", "sdaia",
    "humain", "ndmo", "mcit", "kaust", "neom", "kacst",
    "سعود", "السعودية", "المملكة", "الرياض", "رؤية 2030", "سدايا", "هيومين", "نيوم", "وزارة", "هيئة",
)
SAUDI_AI_TERMS_TRACKER = (
    "ai", "artificial intelligence", "generative ai", "machine learning", "llm", "model",
    "الذكاء الاصطناعي", "ذكاء اصطناعي", "نموذج",
)
SAUDI_POLICY_TERMS = (
    "policy", "regulation", "governance", "framework", "public consultation", "consultation",
    "سياسة", "سياسات", "تنظيم", "لوائح", "لائحة", "حوكمة", "إطار تنظيمي", "استطلاع مرئيات", "مرئيات",
)
SAUDI_PLATFORM_TERMS = (
    "platform", "service", "engine", "launch", "launched", "unveils", "introduces",
    "منصة", "خدمة", "محرك", "أطلقت", "يطلق", "تطلق", "إطلاق",
)
SAUDI_GOV_SERVICE_TERMS = (
    "government service", "public service", "municipal", "ministry", "authority",
    "خدمة حكومية", "الخدمات الحكومية", "الخدمات البلدية", "وزارة", "هيئة",
)
SAUDI_SECTOR_TERMS = (
    "tourism", "education", "health", "culture", "municipal", "water", "energy",
    "السياحة", "التعليم", "الصحة", "الثقافة", "البلدية", "البلديات", "المياه", "الطاقة",
)
SAUDI_PARTNERSHIP_TERMS = ("partnership", "agreement", "signs", "cooperation", "collaboration", "شراكة", "اتفاقية", "تعاون", "وقعت")
SAUDI_TRAINING_TERMS = ("bootcamp", "course", "training", "academy", "workshop", "program", "معسكر", "دورة", "تدريب", "أكاديمية", "ورشة")
SAUDI_MARKET_REPORT_TERMS = ("market size", "market growth", "forecast", "cagr", "market report", "حجم السوق", "نمو السوق", "تقرير سوق")


def tracker_canonical_url(url: str = "") -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.netloc:
        return ""
    return f"{(parsed.scheme or 'https').lower()}://{parsed.netloc.lower().removeprefix('www.')}{parsed.path.rstrip('/')}"


def tracker_dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    output = []
    for item in items:
        key = tracker_canonical_url(item.get("url") or "")
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
def fetch_news_candidates(*, exclude_items: list[dict] | None = None, target_hint: str = "", single: bool = False, cycle: int = 1) -> tuple[list[dict], dict]:
    """Fetch news candidates from Exa and SearXNG in parallel."""
    started = time.time()
    exa_rows = discovery_rows("exa", single=single, target_hint=target_hint, cycle=cycle)
    searxng_rows = discovery_rows("searxng", single=single, target_hint=target_hint)
    mode = "single_parallel" if single else "full_parallel"
    safe_print(f"[AI Updates] Parallel fetch: exa={len(exa_rows)} searxng={len(searxng_rows)} mode={mode}")
    log_event(
        "source_fetch.plan",
        mode=mode,
        target_hint=target_hint,
        exa_queries=len(exa_rows),
        searxng_queries=len(searxng_rows),
        exa_query_sample=[row.get("query") for row in exa_rows[:8]],
        searxng_query_sample=[row.get("query") for row in searxng_rows[:8]],
        tool_discovery=dict(LAST_DISCOVERY_META),
        query_angles={
            source: meta.get("query_angle")
            for source, meta in LAST_DISCOVERY_META.items()
            if meta.get("query_angle")
        },
    )
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
    primary_unique_results = len(items)
    tracker_threshold = AI_UPDATES_TRACKER_RUN_WHEN_PRIMARY_BELOW
    tracker_should_run = (
        not single
        and AI_UPDATES_TRACKER_DISCOVERY_LAYER_ENABLED
        and primary_unique_results < tracker_threshold
    )
    if not single and AI_UPDATES_TRACKER_DISCOVERY_LAYER_ENABLED and not tracker_should_run:
        diagnostics["tracker_discovery_layer"] = {
            "enabled": True,
            "skipped": True,
            "skip_reason": "primary_candidates_above_threshold",
            "primary_unique_results": primary_unique_results,
            "run_when_primary_below": tracker_threshold,
        }
        log_event(
            "tracker_discovery_layer.skipped",
            reason="primary_candidates_above_threshold",
            primary_unique_results=primary_unique_results,
            run_when_primary_below=tracker_threshold,
        )
    if tracker_should_run:
        tracker_items, tracker_diagnostics = fetch_tracker_discovery_layer(exclude_items=exclude_items)
        merged_items, _ = combine_source_results(
            [
                ("tool_driven", items, {"raw_results": 0, "queries": 0}),
                ("tracker_discovery_layer", tracker_items, {"raw_results": 0, "queries": 0}),
            ],
            mode=f"{mode}_merged_tracker_discovery_layer",
        )
        items = merged_items
        diagnostics["raw_results"] = int(diagnostics.get("raw_results") or 0) + int(tracker_diagnostics.get("raw_results") or 0)
        diagnostics["queries"] = int(diagnostics.get("queries") or 0) + int(tracker_diagnostics.get("queries") or 0)
        diagnostics["unique_results"] = len(items)
        diagnostics.setdefault("source_diagnostics", {})["tracker_discovery_layer"] = tracker_diagnostics
        diagnostics.setdefault("source_failures", {}).update(tracker_diagnostics.get("source_failures") or {})
        diagnostics["tracker_discovery_layer"] = {
            "enabled": True,
            "queries": tracker_diagnostics.get("queries", 0),
            "raw_results": tracker_diagnostics.get("raw_results", 0),
            "unique_results": tracker_diagnostics.get("unique_results", 0),
            "layer_counts": tracker_diagnostics.get("layer_counts", {}),
            "seconds": tracker_diagnostics.get("tracker_discovery_layer_seconds", 0),
        }
        diagnostics["source_candidate_counts"] = dict(Counter(item.get("fetch_source") or "unknown" for item in items))
    # General layer merge: full weekly generation adds non-tool-list AI news
    # after the existing tool-driven fetch, then deduplicates by URL/title
    # before the shared quality and LLM filtering stages.
    # CHANGE: GENERAL_NEWS_EXA_ROWS/GENERAL_NEWS_SEARXNG_ROWS are fixed query
    # text with no per-cycle variable (same root cause as the
    # EXA_PRODUCT_UPDATE_BROAD_QUERIES fix above) - verified live 2026-07-11
    # that general_news_layer.finished logged byte-identical raw_results (239),
    # unique_results (23), and domain_allowlist_rejected (98) on both cycle 1
    # and cycle 2 of the same run. Only run it on the first cycle.
    if not single and AI_UPDATES_GENERAL_NEWS_LAYER_ENABLED and cycle <= 1:
        general_items, general_diagnostics = fetch_general_news_layer(exclude_items=exclude_items)
        merged_items, _ = combine_source_results(
            [
                ("tool_driven", items, {"raw_results": 0, "queries": 0}),
                ("general_news_layer", general_items, {"raw_results": 0, "queries": 0}),
            ],
            mode=f"{mode}_merged_general_layer",
        )
        items = merged_items
        diagnostics["raw_results"] = int(diagnostics.get("raw_results") or 0) + int(general_diagnostics.get("raw_results") or 0)
        diagnostics["queries"] = int(diagnostics.get("queries") or 0) + int(general_diagnostics.get("queries") or 0)
        diagnostics["unique_results"] = len(items)
        diagnostics.setdefault("source_diagnostics", {})["general_news_layer"] = general_diagnostics
        diagnostics.setdefault("source_failures", {}).update(general_diagnostics.get("source_failures") or {})
        diagnostics["general_news_layer"] = {
            "enabled": True,
            "queries": general_diagnostics.get("queries", 0),
            "raw_results": general_diagnostics.get("raw_results", 0),
            "unique_results": general_diagnostics.get("unique_results", 0),
            "layer_counts": general_diagnostics.get("layer_counts", {}),
            "seconds": general_diagnostics.get("general_news_layer_seconds", 0),
        }
        diagnostics["source_candidate_counts"] = dict(Counter(item.get("fetch_source") or "unknown" for item in items))
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
    safe_print(f"[AI Updates] Parallel fetch collected unique={len(items)} raw={diagnostics.get('raw_results')} seconds={diagnostics['parallel_fetch_seconds']}")
    log_event(
        "source_fetch.finished",
        mode=mode,
        raw_results=diagnostics.get("raw_results"),
        unique_results=len(items),
        seconds=diagnostics["parallel_fetch_seconds"],
        source_candidate_counts=diagnostics.get("source_candidate_counts", {}),
        source_failures=diagnostics.get("source_failures", {}),
        source_failures_detail=diagnostics.get("source_failures_detail", {}),
        tool_group_counts=diagnostics.get("tool_group_counts", {}),
        query_mix_counts=diagnostics.get("query_mix_counts", {}),
    )
    return items, diagnostics


