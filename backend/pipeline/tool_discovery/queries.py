# This file is part of the AI newsletter system.
"""Central query definitions for AI tool discovery and weekly news fetching.

This file is the only place that should own reusable query text. Fetchers and
tool-aware code import these constants/helpers instead of redefining queries.
"""

from __future__ import annotations

import re

from backend.config.settings import CURRENT_YEAR, SEARXNG_URL, clean_text, normalized_text
from backend.pipeline.tool_discovery.official_sites import official_site_query_prefix


# WHAT: Business-only terms that should not be accepted as AI tool/product updates.
# HOW: Shared text guard used by tool discovery and news candidate filtering.
# INPUT: Text normalized by text_has_any().
# OUTPUT: Tuple of lowercase rejection terms.
BUSINESS_ONLY_TERMS = (
    "crm",
    "erp",
    "sales enablement",
    "sales pipeline",
    "customer support",
    "call center",
    "contact center",
    "lead generation",
    "marketing automation",
    "accounting",
    "invoice",
    "invoicing",
    "bookkeeping",
    "payroll",
    "legal tech",
    "law firm",
    "law firms",
    "lawyer",
    "lawyers",
    "contract management",
    "admin tool",
    "administrative workflow",
    "back office",
    "hr software",
    "recruiting",
    "cybersecurity",
    "security operations",
)


# WHAT: Returns the SearXNG search endpoint.
# HOW: Normalizes SEARXNG_URL from config so callers can pass params directly.
# INPUT: No parameters.
# OUTPUT: Search endpoint URL string.
def search_url() -> str:
    base = SEARXNG_URL.rstrip("/")
    return base if base.endswith("/search") else f"{base}/search"


# WHAT: Checks whether a query already mentions AI.
# HOW: Uses literal AI/artificial-intelligence matching.
# INPUT: Query string.
# OUTPUT: Boolean.
def query_has_ai_scope(query: str = "") -> bool:
    clean = f" {str(query or '').lower()} "
    return bool(re.search(r"\bai\b", clean)) or "artificial intelligence" in clean


# WHAT: Adds AI scope to a query when missing.
# HOW: Appends AI/artificial-intelligence terms only when needed.
# INPUT: Query string.
# OUTPUT: AI-scoped query string.
def ensure_ai_scope(query: str = "") -> str:
    clean = re.sub(r"\s+", " ", str(query or "").strip())
    if not clean:
        return ""
    if query_has_ai_scope(clean):
        return clean
    return f"{clean} AI artificial intelligence"


# WHAT: Requires AI + product + action context for literal SearXNG searches.
# HOW: Wraps the query with AND guards and fixes ambiguous terms.
# INPUT: Query string.
# OUTPUT: Strict SearXNG query string.
def strict_searxng_ai_product_query(query: str = "") -> str:
    clean = re.sub(r"\s+", " ", str(query or "").strip())
    if not clean:
        return ""
    clean = re.sub(r"\bships\b", '"rolls out"', clean, flags=re.IGNORECASE)
    clean = re.sub(
        r'(?<![\w"])\bnew\b(?!\s+(?:feature|ai|tool|platform|product|model)\b)',
        '"product update"',
        clean,
        flags=re.IGNORECASE,
    )
    product_signal = '("tool" OR "platform" OR "product" OR "feature" OR "model")'
    action_signal = '("launches" OR "announces" OR "now available" OR "rolls out" OR "introduces" OR "update")'
    return f"({clean}) AND {product_signal} AND {action_signal}"


# WHAT: Checks whether text contains any listed terms.
# HOW: Uses normalized lowercase substring matching.
# INPUT: Text string and tuple of terms.
# OUTPUT: Boolean.
def text_has_any(text: str = "", terms: tuple[str, ...] = ()) -> bool:
    clean = normalized_text(text)
    return any(term in clean for term in terms or ())


# WHAT: Finds currently popular AI tools from broad market/user-adoption searches.
# HOW: Used by Exa and SearXNG live discovery; queries are broad and not tied to one tool.
# INPUT: No runtime input; CURRENT_YEAR keeps year-sensitive wording current.
# OUTPUT: Rows consumed by live tool discovery.
LIVE_TOOL_DISCOVERY_ROWS = [
    {"group": "general_market", "query": "most popular AI tools used by consumers knowledge workers this month"},
    {"group": "general_market", "query": f"most used AI assistants productivity research writing tools {CURRENT_YEAR}"},
    {"group": "general_market", "query": f"AI products with highest user adoption traffic report {CURRENT_YEAR}"},
    {"group": "culture_creative", "query": f"popular AI tools for designers creators image video audio writing {CURRENT_YEAR}"},
    {"group": "culture_creative", "query": f"AI tools for culture creative work design video music storytelling learning {CURRENT_YEAR}"},
    {"group": "culture_creative", "query": f"popular AI tools for Arabic language translation learning content creation {CURRENT_YEAR}"},
]


# WHAT: Finds successful AI tools with funding, adoption, or growth evidence.
# HOW: Exa neural search; useful when exact keywords differ across articles.
# INPUT: No parameters.
# OUTPUT: Query strings for successful-tool discovery.
SUCCESSFUL_TOOL_EXA_QUERIES = [
    "AI tool raised Series A Series B funding global users",
    "fastest growing AI tools globally million users",
    "AI startup product launch global traction",
    "AI tool viral growth worldwide new users",
    "breakthrough AI product global adoption",
]


# WHAT: Supplements successful-tool discovery with literal web keyword search.
# HOW: SearXNG keyword search for funding/adoption/launch signals.
# INPUT: No parameters.
# OUTPUT: Query strings for successful-tool discovery.
SUCCESSFUL_TOOL_SEARXNG_QUERIES = [
    '"AI tool" "Series A" OR "Series B" OR "raised"',
    '"AI product" "million users" OR "fastest growing"',
    '"new AI tool" "global" "launch"',
]


# WHAT: Expands the tool list from public AI-tool aggregators.
# HOW: Exa searches known aggregator domains that index new/trending tools.
# INPUT: No parameters.
# OUTPUT: Query strings for auto-expansion.
AUTO_EXPAND_AGGREGATOR_EXA_QUERIES = [
    'site:therundown.ai/p "AI tool" launches OR introduces OR new',
    "site:toolify.ai/ai-news new AI tool launches",
    "site:producthunt.com/posts AI tool",
]


# WHAT: Expands the tool list from market growth and funding evidence.
# HOW: Exa neural search over broad market language.
# INPUT: No parameters.
# OUTPUT: Query strings for auto-expansion.
AUTO_EXPAND_GROWTH_EXA_QUERIES = [
    '"AI tool" OR "AI platform" "Series A" OR "Series B" OR "raises"',
    '"AI startup" "million users" OR "fastest growing" OR "viral"',
    '"new AI product" global launch "now available"',
]


# WHAT: Expands the tool list with strict literal web searches.
# HOW: SearXNG uses AND-heavy wording to reduce generic AI-news noise.
# INPUT: No parameters.
# OUTPUT: Query strings for auto-expansion.
AUTO_EXPAND_SEARXNG_QUERIES = [
    '"AI tool" AND ("just launched" OR "now available") AND "global"',
    '"AI startup" AND ("raises" OR "Series A" OR "Series B")',
    '"new AI platform" AND ("million users" OR "fastest growing")',
]


# WHAT: Searches fixed public aggregators every weekly run.
# HOW: Exa news searches over domains that surface tool launches and updates.
# INPUT: No parameters.
# OUTPUT: Query rows appended to tool-specific and general Exa news rows.
EXA_AGGREGATOR_NEWS_ROWS = [
    {
        "bucket": "aggregator_tool_news",
        "source_type": "aggregator",
        "aggregator_source": "therundown.ai",
        "query": "site:therundown.ai/p AI tool update launch new feature",
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "bucket": "aggregator_tool_news",
        "source_type": "aggregator",
        "aggregator_source": "toolify.ai",
        "query": "site:toolify.ai/ai-news AI tool new feature product update",
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "bucket": "aggregator_tool_news",
        "source_type": "aggregator",
        "aggregator_source": "venturebeat.com",
        "query": "site:venturebeat.com/ai AI tool launch announces new feature",
        "use_news_category": True,
        "exa_num_results": 10,
    },
]


# WHAT: Finds AI news that is not tied to the cached tool registry.
# HOW: Exa weekly searches across unlisted tool updates, global AI events, Saudi/SDAIA news, and aggregators.
# INPUT: No parameters.
# OUTPUT: Exa query rows consumed by the general-news fetcher.
GENERAL_NEWS_EXA_ROWS = [
    {
        "layer": "layer1",
        "bucket": "unlisted_ai_tool_updates",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"AI tool" new feature OR launches OR ships OR "now available"',
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer1",
        "bucket": "unlisted_ai_tool_updates",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"AI platform" update OR release OR "just launched" global',
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer1",
        "bucket": "unlisted_ai_tool_updates",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"AI product" announces OR introduces OR "rolling out"',
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer2",
        "bucket": "global_ai_events",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"artificial intelligence" government OR country adopts OR launches OR announces',
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer2",
        "bucket": "global_ai_events",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"national AI strategy" OR "AI regulation" OR "AI policy" announces',
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer2",
        "bucket": "global_ai_events",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"AI" summit OR conference OR museum OR initiative global',
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer2",
        "bucket": "global_ai_events",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"AI" partnership OR adoption institutional OR cultural',
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": "site:sdaia.gov.sa",
        "use_news_category": False,
        "exa_num_results": 10,
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"SDAIA" OR "سدايا" AI announces OR launches OR initiative',
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"Saudi Arabia" artificial intelligence initiative OR platform OR launches',
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"Vision 2030" AI technology announces OR launches',
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": "SDAIA artificial intelligence policy Saudi Arabia",
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": "Saudi Arabia AI policy public consultation",
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": "Saudi AI platform launched government service",
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": "Saudi tourism AI platform TourismX",
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": "سدايا الذكاء الاصطناعي سياسة",
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": "استطلاع مرئيات الذكاء الاصطناعي السعودية",
        "use_news_category": True,
        "exa_num_results": 10,
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": "إطلاق منصة ذكاء اصطناعي السعودية",
        "use_news_category": True,
        "exa_num_results": 10,
    },
    *[{**row, "layer": "aggregator", "query_mix": "general_layer"} for row in EXA_AGGREGATOR_NEWS_ROWS],
]


# WHAT: Mirrors the general Exa layer for web/news keyword search.
# HOW: SearXNG weekly searches with stricter literal wording.
# INPUT: No parameters.
# OUTPUT: SearXNG query rows consumed by the general-news fetcher.
GENERAL_NEWS_SEARXNG_ROWS = [
    {
        "layer": "layer1",
        "bucket": "unlisted_ai_tool_updates",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"AI tool" "new feature" OR "product update" OR "just launched"',
    },
    {
        "layer": "layer1",
        "bucket": "unlisted_ai_tool_updates",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"AI platform" launches OR "rolls out" OR "now available"',
    },
    {
        "layer": "layer2",
        "bucket": "global_ai_events",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"artificial intelligence" government launches OR announces',
    },
    {
        "layer": "layer2",
        "bucket": "global_ai_events",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"AI initiative" OR "AI strategy" country OR city',
    },
    {
        "layer": "layer2",
        "bucket": "global_ai_events",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"AI" museum OR cultural institution OR heritage',
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": "site:sdaia.gov.sa",
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"سدايا" OR "SDAIA" ذكاء اصطناعي إطلاق OR مبادرة',
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"Saudi Arabia" AI launches OR announces',
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"Vision 2030" artificial intelligence',
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"SDAIA" "artificial intelligence" "policy"',
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"Saudi Arabia" "AI policy" "public consultation"',
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"Saudi" "AI platform" "launched"',
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"سدايا" "سياسة" "الذكاء الاصطناعي"',
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"استطلاع مرئيات" "الذكاء الاصطناعي"',
    },
    {
        "layer": "layer3",
        "bucket": "saudi_ai_news",
        "source_type": "general_news_layer",
        "query_mix": "general_layer",
        "query": '"إطلاق" "منصة" "ذكاء اصطناعي" "السعودية"',
    },
]


# WHAT: Launch/update vocabulary used when building tool-specific queries.
# HOW: Official-site queries skip broad update terms; general web queries include them.
# INPUT: official_site_known boolean in announcement_terms_query().
# OUTPUT: OR-group query text.
ANNOUNCEMENT_LAUNCH_TERMS = (
    "launches",
    "introducing",
    "announces",
    "ships",
    "rolls out",
    "debuts",
)
ANNOUNCEMENT_AVAILABILITY_TERMS = (
    "now available",
    "generally available",
    "GA",
    "live now",
    "out now",
)
ANNOUNCEMENT_UPDATE_TERMS = (
    "new feature",
    "product update",
    "just updated",
    "we added",
    "now supports",
    "improved",
)


# WHAT: Builds launch/update vocabulary for official or general tool searches.
# HOW: Uses launch and availability terms; adds broader update terms when no official site exists.
# INPUT: official_site_known boolean.
# OUTPUT: Parenthesized OR query string.
def announcement_terms_query(*, official_site_known: bool) -> str:
    groups = [ANNOUNCEMENT_LAUNCH_TERMS, ANNOUNCEMENT_AVAILABILITY_TERMS, ANNOUNCEMENT_UPDATE_TERMS]
    terms = [term for group in groups for term in group]
    return "(" + " OR ".join(f'"{term}"' for term in terms) + ")"


# WHAT: Builds one tool-specific release/update query.
# HOW: Uses site: official source when present; otherwise uses tool/company names.
# INPUT: tool name, official site, and company.
# OUTPUT: Search query string for Exa or SearXNG.
def tool_release_query(name: str, site: str = "", company: str = "") -> str:
    name = clean_text(name or company or "")
    site_prefix = official_site_query_prefix(site)
    release_terms = announcement_terms_query(official_site_known=bool(site_prefix))
    if site_prefix:
        return f'{site_prefix}"{name}" {release_terms}'
    company_part = f' "{company}"' if company and normalized_text(company) != normalized_text(name) else ""
    return f'"{name}"{company_part} {release_terms}'
