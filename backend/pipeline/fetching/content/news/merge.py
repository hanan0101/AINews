"""News discovery: source result merging and the general-news layer."""

from .common import *
from .queries import *
from .normalization import *
from .searxng import *
from .exa import *

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

__all__ = [name for name in globals() if not name.startswith("__")]
