# This file is part of the AI newsletter system.
"""Configuration and shared utilities for the standalone AI update pipeline."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# Resolve paths from this file so Docker and local runs read backend assets.
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"

# Keep year-sensitive searches current automatically; no annual manual edit is needed.
CURRENT_YEAR = datetime.now(timezone.utc).year
CURRENT_YEAR_START = f"{CURRENT_YEAR}-01-01"

NEWS_FETCH_STATE_FILE = BACKEND_DIR / "news_fetch_state.json"
SECTOR_TERMS_HISTORY_FILE = BACKEND_DIR / "sector_terms_history.json"
MONTHLY_TOOLS_FILE = BACKEND_DIR / "monthly_tools-site.json"
# Legacy names are kept only so older helper code can import safely. The active
# registry is monthly_tools-site.json and contains tools + official sites.
TOOL_OFFICIAL_SITES_FILE = MONTHLY_TOOLS_FILE
TOOL_SECTOR_MAP_FILE = MONTHLY_TOOLS_FILE
TOOLS_SCORED_FILE = MONTHLY_TOOLS_FILE
QDRANT_DB_DIR = BACKEND_DIR / "vector_db" / "qdrant_db"

# Load the main project env first, then allow the focused AI updates env to
# override only pipeline-related values when present.
load_dotenv(BACKEND_DIR / ".env", override=False)
load_dotenv(BACKEND_DIR / ".env.ai_updates", override=True)


# Performs the env path helper step.
def env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value) if value else default


NEWS_JSON_FILE = env_path("NEWS_JSON_PATH", FRONTEND_DIR / "news.json")
AI_UPDATES_RUN_REPORT_FILE = env_path(
    "AI_UPDATES_RUN_REPORT_PATH",
    FRONTEND_DIR / "ai_updates_run_report.json",
)


# Performs the env bool helper step.
def env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


# Performs the env int helper step.
def env_int(name: str, default: str) -> int:
    try:
        return int(os.getenv(name, default) or default)
    except Exception:
        return int(default)


# Performs the safe write json helper step.
def safe_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(temp_file, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_file, path)


# Reads load json from the current store or request context.
def load_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return dict(default or {})
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else dict(default or {})
    except Exception:
        return dict(default or {})


# Level-balanced newsletter change: the visible recommended view now shows
# 4 news cards while the saved bank still keeps 12 total news cards.
DISPLAY_COUNTS = {
    "items": env_int("AI_UPDATES_VISIBLE_COUNT", "4"),
    "courses": env_int("AI_UPDATES_COURSES_VISIBLE_COUNT", "6"),
    "movies": env_int("AI_UPDATES_MOVIES_VISIBLE_COUNT", "2"),
}

# Keep eight hidden cards so editors can replace weak visible items without a
# new fetch. Change this when the review UI needs a larger or smaller reserve.
BACKUP_NEWS_COUNT = env_int("AI_UPDATES_BACKUP_COUNT", "8")
TOTAL_NEWS_TARGET = DISPLAY_COUNTS["items"] + BACKUP_NEWS_COUNT
SAVE_NEWS_BACKUP_FROM_SELECTION = env_bool("AI_UPDATES_SAVE_BACKUP_FROM_SELECTION", "1")
# 120 gives the model enough variety after source filtering without making
# audits too noisy; raise it only when sources are high quality and fast.
AI_UPDATES_SCAN_POOL_LIMIT = env_int("AI_UPDATES_SCAN_POOL_LIMIT", "90")
# 60 is the practical prompt shortlist limit for stable latency/cost. Increase
# it only when the model misses good stories because the candidate pool is huge.
AI_UPDATES_GPT_SHORTLIST_LIMIT = env_int("AI_UPDATES_GPT_SHORTLIST_LIMIT", "45")
# Tool discovery is refreshed monthly by default because product registries do
# not change enough day-to-day to justify a full rebuild every run.
AI_UPDATES_TOOL_CACHE_REFRESH_DAYS = env_int("AI_UPDATES_TOOL_CACHE_REFRESH_DAYS", "30")
# 120 records keeps the tool cache broad while staying readable in JSON audits.
AI_UPDATES_TOOL_CACHE_MAX_RECORDS = env_int("AI_UPDATES_TOOL_CACHE_MAX_RECORDS", "120")
AI_UPDATES_TOOL_DISCOVERY_ENABLED = env_bool("AI_UPDATES_TOOL_DISCOVERY_ENABLED", "1")
AI_UPDATES_TOOL_DISCOVERY_MODEL = os.getenv("AI_UPDATES_TOOL_DISCOVERY_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
# Six results per discovery query is enough to find official pages without
# flooding the registry with repeated directory/listicle pages.
AI_UPDATES_TOOL_DISCOVERY_RESULTS = env_int("AI_UPDATES_TOOL_DISCOVERY_RESULTS", "6")

SUPPORTING_CONTENT_ENABLED = env_bool("AI_UPDATES_REFRESH_SUPPORTING_CONTENT", "1")
SUPPORTING_CONTENT_PREFETCH = env_bool("AI_UPDATES_SUPPORTING_CONTENT_PREFETCH", "1")
# Level-balanced course bank needs enough clean candidates to keep
# 2 Beginner, 2 Intermediate, and 2 Advanced courses without repetition.
SUPPORTING_COURSE_FETCH_POOL = env_int("AI_UPDATES_SUPPORTING_COURSE_FETCH_POOL", "24")
# Movies come from a noisier public catalogue, so the pool is larger than
# courses. Lower it only if TMDB latency becomes a problem.
SUPPORTING_MOVIE_FETCH_POOL = env_int("AI_UPDATES_SUPPORTING_MOVIE_FETCH_POOL", "40")
DAEMON_ENABLED = env_bool("AI_UPDATES_DAEMON_ENABLED", "0")
# One hour is a safe default for unattended refreshes. Shorten it only for
# demos or breaking-news mode because each run calls paid/external APIs.
DAEMON_INTERVAL_SECONDS = env_int("AI_UPDATES_INTERVAL", "3600")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("AI_UPDATES_OPENAI_MODEL", "gpt-5.2").strip() or "gpt-5.2"
AI_UPDATES_MODEL_PROVIDER = os.getenv("AI_UPDATES_MODEL_PROVIDER", "gemini").strip().lower() or "gemini"
GEMINI_API_KEY = (
    os.getenv("GEMINI_API_KEY")
    or os.getenv("Gemini_API_Key")
    or os.getenv("GEMINI_API_Key")
    or os.getenv("GOOGLE_API_KEY")
    or ""
).strip()
GEMINI_NEWS_MODEL = os.getenv("GEMINI_NEWS_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
GEMINI_REWRITE_MODEL = os.getenv("GEMINI_REWRITE_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
GEMINI_FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
EXA_API_KEY = os.getenv("EXA_API_KEY", "").strip()
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()

# Course discovery is intentionally locked to this trusted domain list. Exa can
# search broadly inside these domains, but outside platforms are rejected.
COURSE_DOMAINS = [
    "satr.tuwaiq.edu.sa",
    "tuwaiq.edu.sa",
    "sda.mcit.gov.sa",
    "futureskills.mcit.gov.sa",
    "sdaia.gov.sa",
    "ethrai.sa",
    "hub.misk.org.sa",
    "academy.kaust.edu.sa",
    "ithra.com",
    "edraak.org",
    "rwaq.org",
    "maharatech.gov.eg",
    "academy.openai.com",
    "anthropic.com",
    "skillsbuild.org",
    "academy.asana.com",
    "academy.notion.com",
    "university.atlassian.com",
    "academy.airtable.com",
    "academy.miro.com",
    "learn.zapier.com",
    "academy.make.com",
    "academy.hubspot.com",
    "semrush.com",
    "academy.synthesia.io",
    "coursera.org",
    "udemy.com",
    "edx.org",
    "linkedin.com",
    "skillshare.com",
    "masterclass.com",
    "domestika.org",
    "futurelearn.com",
    "udacity.com",
    "pluralsight.com",
    "codecademy.com",
    "openclassrooms.com",
    "iversity.org",
    "kaggle.com",
    "datacamp.com",
    "cognitiveclass.ai",
    "deeplearning.ai",
    "fast.ai",
    "huggingface.co",
    "freecodecamp.org",
    "elementsofai.com",
    "learnprompting.org",
    "promptingguide.ai",
    "wandb.ai",
    "scrimba.com",
    "mygreatlearning.com",
    "simplilearn.com",
    "intellipaat.com",
    "upgrad.com",
    "microsoft.com",
    "learn.microsoft.com",
    "google.com",
    "skills.google",
    "cloudskillsboost.google",
    "developers.google.com",
    "grow.google",
    "aws.amazon.com",
    "nvidia.com",
    "trailhead.salesforce.com",
    "learn.databricks.com",
    "university.mongodb.com",
    "education.github.com",
    "adobe.com",
    "canva.com",
    "figma.com",
    "superhi.com",
    "awwwards.com",
    "doroob.sa",
    "doroob.com.sa",
    "saudidigitalacademy.sa",
    "mcit.gov.sa",
    "open.edu",
    "ocw.mit.edu",
    "online.stanford.edu",
    "extension.harvard.edu",
    "mooc.org",
    "swayam.gov.in",
    "nptel.ac.in",
    "spoken-tutorial.org",
    "digiskills.pk",
    "iabac.org",
]


# Performs the course domain host helper step.
def _course_domain_host(value: str) -> str:
    try:
        host = urlparse(f"https://{str(value or '').strip().lstrip('/')}").netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


# Performs the dedupe strings helper step.
def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        clean = str(value or "").strip()
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        output.append(clean)
    return output


COURSE_INCLUDE_DOMAINS = _dedupe_strings([
    _course_domain_host(domain)
    for domain in COURSE_DOMAINS
    if _course_domain_host(domain)
])
COURSE_QUERY = {
    "query": os.getenv("AI_UPDATES_COURSE_QUERY", "").strip(),
    "includeDomains": COURSE_INCLUDE_DOMAINS,
    "startPublishedDate": os.getenv("AI_UPDATES_COURSE_START_PUBLISHED_DATE", "").strip(),
    "numResults": env_int("AI_UPDATES_COURSE_NUM_RESULTS", "10"),
    "type": os.getenv("AI_UPDATES_COURSE_EXA_TYPE", "neural").strip() or "neural",
}
_COURSE_QUERY_VARIANT_DEFAULTS = [
    'site:academy.openai.com ("AI" OR "ChatGPT" OR "agents") ("work" OR "productivity" OR "workflow" OR "courses")',
    'site:anthropic.com/learn ("Claude" OR "AI") ("work" OR "professional" OR "productivity")',
    'site:skills.google ("AI Essentials" OR "generative AI") ("productivity" OR "work" OR "business")',
    'site:learn.microsoft.com/en-us/ai ("business" OR "productivity" OR "Copilot" OR "AI")',
    'site:skillsbuild.org/adult-learners ("artificial intelligence" OR "generative AI")',
    'site:academy.hubspot.com/courses ("AI" OR "artificial intelligence") ("marketing" OR "sales" OR "business")',
    'site:academy.asana.com ("AI for work" OR "AI Studio" OR "productivity")',
    'site:academy.notion.com ("Notion AI" OR "AI") ("docs" OR "projects" OR "work")',
    'site:university.atlassian.com ("Rovo" OR "Atlassian Intelligence" OR "AI")',
    'site:academy.airtable.com ("AI" OR "agentic" OR "automation")',
    'site:academy.miro.com ("AI" OR "Miro AI")',
    'site:learn.zapier.com ("AI" OR "automation" OR "workflow")',
    'site:academy.make.com ("AI" OR "AI Agents" OR "automation")',
    'site:semrush.com/academy ("AI" OR "AI Search") ("marketing" OR "content")',
    'site:academy.synthesia.io ("AI video" OR "video creation" OR "training videos")',
    'site:satr.tuwaiq.edu.sa ("AI" OR "الذكاء الاصطناعي") ("موظفين" OR "مهنيين" OR "تطوير المهارات" OR "سوق العمل" OR "training")',
    'site:tuwaiq.edu.sa/bootcamps ("AI" OR "الذكاء الاصطناعي") ("مهني" OR "تدريب" OR "bootcamp" OR "workforce")',
    'site:sda.mcit.gov.sa/ar/programs ("AI" OR "الذكاء الاصطناعي") ("مهني" OR "مهارات" OR "تدريب" OR "workforce")',
    'site:futureskills.mcit.gov.sa ("AI" OR "الذكاء الاصطناعي") ("مهارات" OR "سوق العمل" OR "موظفين" OR "professional")',
    'site:ethrai.sa ("AI" OR "الذكاء الاصطناعي") ("موظف" OR "مهني" OR "تطوير المهارات" OR "workplace")',
    'site:linkedin.com/learning ("AI" OR "generative AI" OR "prompt engineering") ("employee" OR "professional" OR "workplace" OR "productivity" OR "business")',
    'site:coursera.org/learn ("AI" OR "generative AI") ("employee" OR "professional" OR "business" OR "workplace" OR "productivity")',
    'site:deeplearning.ai/courses ("AI" OR "generative AI" OR "prompt engineering") ("business" OR "professional" OR "work" OR "productivity")',
    'site:microsoft.com/learn ("AI" OR "Copilot" OR "generative AI") ("training" OR "professional" OR "workplace" OR "productivity")',
    'site:learn.microsoft.com/en-us/training ("AI" OR "Copilot" OR "generative AI") ("training" OR "professional" OR "workplace" OR "productivity")',
]
_COURSE_QUERY_VARIANT_ENV = os.getenv("AI_UPDATES_COURSE_QUERY_VARIANTS", "")
COURSE_QUERY_VARIANTS = _dedupe_strings(
    ([COURSE_QUERY["query"]] if COURSE_QUERY["query"] else [])
    + _COURSE_QUERY_VARIANT_DEFAULTS
    + [part.strip() for part in _COURSE_QUERY_VARIANT_ENV.replace("\n", "|").split("|")]
)

SEARXNG_URL = (
    os.getenv("AI_UPDATES_SEARXNG_URL")
    or os.getenv("SEARXNG_URL")
    or os.getenv("SEARXNG_BASE_URL")
    or "http://localhost:8080"
).strip()

# News freshness window: default to the last 7 days so full generation and
# single-card refill only accept updates from the last week. Override with
# AI_UPDATES_LOOKBACK_DAYS in backend/.env when a wider/narrower window is needed.
# Seven days keeps the newsletter current while still catching delayed source
# indexing. Use a shorter window for daily editions, longer for weekly reviews.
AI_UPDATES_LOOKBACK_DAYS = env_int("AI_UPDATES_LOOKBACK_DAYS", "7")
AI_UPDATES_OUTPUT_LIMIT = env_int("AI_UPDATES_OUTPUT_LIMIT", str(TOTAL_NEWS_TARGET))
# Compact limits bound prompt size. Increase them only with a larger model
# context window and after checking latency in the run report.
AI_UPDATES_GPT_COMPACT_LIMIT = env_int("AI_UPDATES_GPT_COMPACT_LIMIT", "60")
AI_UPDATES_SINGLE_OUTPUT_LIMIT = env_int("AI_UPDATES_SINGLE_OUTPUT_LIMIT", "5")
AI_UPDATES_SINGLE_GPT_COMPACT_LIMIT = env_int("AI_UPDATES_SINGLE_GPT_COMPACT_LIMIT", "36")

# SearXNG is cheap but noisy; the query/result/worker defaults keep discovery
# broad while protecting the local metasearch container.
AI_UPDATES_SEARXNG_QUERY_LIMIT = env_int("AI_UPDATES_SEARXNG_QUERY_LIMIT", "12")
AI_UPDATES_SEARXNG_RESULTS_PER_QUERY = env_int("AI_UPDATES_SEARXNG_RESULTS_PER_QUERY", "5")
AI_UPDATES_SEARXNG_TIMEOUT = env_int("AI_UPDATES_SEARXNG_TIMEOUT", "8")
AI_UPDATES_SEARXNG_MAX_WORKERS = env_int("AI_UPDATES_SEARXNG_MAX_WORKERS", "2")
# SearXNG source window: request only week-range results before the Python
# recency filter runs, keeping search aligned with the 7-day newsletter window.
AI_UPDATES_SEARXNG_TIME_RANGE = os.getenv("AI_UPDATES_SEARXNG_TIME_RANGE", "week").strip() or "week"
AI_UPDATES_SEARXNG_CATEGORIES = os.getenv("AI_UPDATES_SEARXNG_CATEGORIES", "news,it,general").strip() or "news,it,general"

# Exa is higher quality but paid/external, so limits are lower than SearXNG.
# Raise these only when API budget and timeout headroom are comfortable.
AI_UPDATES_EXA_QUERY_LIMIT = env_int("AI_UPDATES_EXA_QUERY_LIMIT", "12")
AI_UPDATES_EXA_RESULTS_PER_QUERY = env_int("AI_UPDATES_EXA_RESULTS_PER_QUERY", "4")
AI_UPDATES_EXA_TIMEOUT = env_int("AI_UPDATES_EXA_TIMEOUT", "15")
AI_UPDATES_EXA_MAX_WORKERS = env_int("AI_UPDATES_EXA_MAX_WORKERS", "6")
AI_UPDATES_EXA_RETRIES = env_int("AI_UPDATES_EXA_RETRIES", "2")
AI_UPDATES_EXA_RETRY_BACKOFF_SECONDS = env_int("AI_UPDATES_EXA_RETRY_BACKOFF_SECONDS", "2")
AI_UPDATES_COURSE_EXA_QUERY_LIMIT = env_int("AI_UPDATES_COURSE_EXA_QUERY_LIMIT", "6")
AI_UPDATES_COURSE_EXA_RESULTS_PER_QUERY = env_int("AI_UPDATES_COURSE_EXA_RESULTS_PER_QUERY", "10")

AI_UPDATES_SINGLE_SEARXNG_QUERY_LIMIT = env_int("AI_UPDATES_SINGLE_SEARXNG_QUERY_LIMIT", "10")
AI_UPDATES_SINGLE_EXA_QUERY_LIMIT = env_int("AI_UPDATES_SINGLE_EXA_QUERY_LIMIT", "6")
AI_UPDATES_SINGLE_RESULTS_PER_QUERY = env_int("AI_UPDATES_SINGLE_RESULTS_PER_QUERY", "5")
AI_UPDATES_SINGLE_EXA_RESULTS_PER_QUERY = env_int("AI_UPDATES_SINGLE_EXA_RESULTS_PER_QUERY", "5")
AI_UPDATES_SINGLE_TIMEOUT = env_int("AI_UPDATES_SINGLE_TIMEOUT", "16")

# Semantic memory uses OpenAI embeddings + local Qdrant to prevent repeated
# stories/courses/movies across runs. Limits keep the check bounded.
AI_UPDATES_MEMORY_ENABLED = env_bool("AI_UPDATES_MEMORY_ENABLED", "1")
AI_UPDATES_SEMANTIC_MEMORY_ENABLED = env_bool("AI_UPDATES_SEMANTIC_MEMORY_ENABLED", "1")
# Semantic checks are capped to keep Qdrant/OpenAI embedding work bounded.
# Raise them only if duplicate stories are still reaching the model shortlist.
AI_UPDATES_SEMANTIC_MAX_CHECK = env_int("AI_UPDATES_SEMANTIC_MAX_CHECK", "32")
AI_UPDATES_SINGLE_SEMANTIC_MAX_CHECK = env_int("AI_UPDATES_SINGLE_SEMANTIC_MAX_CHECK", "24")
AI_UPDATES_MEMORY_EXACT_LIMIT = env_int("AI_UPDATES_MEMORY_EXACT_LIMIT", "3000")
AI_UPDATES_EMBED_MODEL = os.getenv("AI_UPDATES_EMBED_MODEL", "text-embedding-3-small").strip() or "text-embedding-3-small"
AI_UPDATES_EMBED_INPUT_LIMIT = env_int("AI_UPDATES_EMBED_INPUT_LIMIT", "1200")
AI_UPDATES_EMBED_SIZE = env_int("AI_UPDATES_EMBED_SIZE", "1536")
AI_UPDATES_QDRANT_COLLECTION = os.getenv("AI_UPDATES_QDRANT_COLLECTION", "content_memory").strip() or "content_memory"
# Duplicate thresholds are intentionally high: below these values the same
# company can have different legitimate updates. Lower only after audit review.
AI_UPDATES_SEMANTIC_DUPLICATE_SCORE = float(os.getenv("AI_UPDATES_SEMANTIC_DUPLICATE_SCORE", "0.925") or "0.925")
AI_UPDATES_SAME_RUN_SEMANTIC_SCORE = float(os.getenv("AI_UPDATES_SAME_RUN_SEMANTIC_SCORE", "0.90") or "0.90")
AI_UPDATES_REJECTED_DUPLICATE_SCORE = float(os.getenv("AI_UPDATES_REJECTED_DUPLICATE_SCORE", "0.89") or "0.89")

CATEGORY_CULTURE = "مجال الثقافة والعلوم"
CATEGORY_DAILY = "مجال الحياة العامة"
CATEGORY_WORK = "مجال الحياة العملية والإنتاجية"

NEWS_SECTORS = [
    "المتاحف",
    "الأفلام",
    "التراث",
    "الأزياء",
    "المكتبات",
    "الموسيقى",
    "الفنون البصرية",
    "الأدب",
    "الطهي",
    "العمارة",
    "المسرح",
    "الصحة النفسية",
    "الصحة الجسدية",
    "إنتاجية العمل",
    "الذكاء الاصطناعي والتعليم",
    "والتدريب والمهام اليومية",
]


# Performs the utc now helper step.
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Performs the recency cutoff helper step.
def recency_cutoff() -> datetime:
    return utc_now() - timedelta(days=max(1, AI_UPDATES_LOOKBACK_DAYS))


# Performs the recency cutoff query token helper step.
def recency_cutoff_query_token() -> str:
    return recency_cutoff().date().isoformat()


# Prepares clean text so downstream stages receive consistent data.
def clean_text(value: str = "") -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# Prepares normalized text so downstream stages receive consistent data.
def normalized_text(value: str = "") -> str:
    text = re.sub(r"https?://(www\.)?", " ", str(value or "").lower())
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


# Performs the source domain helper step.
def source_domain(url: str = "") -> str:
    try:
        host = urlparse(str(url or "")).netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


# Performs the memory url key helper step.
def memory_url_key(url: str = "") -> str:
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return str(url or "").strip().lower().rstrip("/")
    if not parsed.netloc:
        return str(url or "").strip().lower().rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}".rstrip("/")


# Performs the parse result datetime helper step.
def parse_result_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text)
        except Exception:
            dt = None
            for fmt in ("%Y-%m-%d", "%d %b %Y", "%b %d, %Y", "%a, %d %b %Y %H:%M:%S %Z"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except Exception:
                    dt = None
            if dt is None:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Performs the result is recent enough helper step.
def result_is_recent_enough(value) -> bool:
    dt = parse_result_datetime(value)
    return dt is None or dt >= recency_cutoff()
