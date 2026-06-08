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

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"

NEWS_JSON_FILE = FRONTEND_DIR / "news.json"
AI_UPDATES_RUN_REPORT_FILE = FRONTEND_DIR / "ai_updates_run_report.json"
NEWS_FETCH_STATE_FILE = BACKEND_DIR / "news_fetch_state.json"
SECTOR_TERMS_HISTORY_FILE = BACKEND_DIR / "sector_terms_history.json"
MONTHLY_TOOLS_FILE = BACKEND_DIR / "monthly_tools.json"
TOOL_SECTOR_MAP_FILE = BACKEND_DIR / "tool_sector_map.json"
TOOLS_SCORED_FILE = BACKEND_DIR / "tools_scored.json"
QDRANT_DB_DIR = BACKEND_DIR / "qdrant_db"

# Load the main project env first, then allow the focused AI updates env to
# override only pipeline-related values when present.
load_dotenv(BACKEND_DIR / ".env", override=False)
load_dotenv(BACKEND_DIR / ".env.ai_updates", override=True)


def env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: str) -> int:
    try:
        return int(os.getenv(name, default) or default)
    except Exception:
        return int(default)


def safe_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(temp_file, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_file, path)


def load_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return dict(default or {})
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else dict(default or {})
    except Exception:
        return dict(default or {})


# Visible counts are the cards the user sees first in the old UI. Backup counts
# are still saved for navigation, but GPT selection remains the source of truth.
DISPLAY_COUNTS = {
    "items": env_int("AI_UPDATES_VISIBLE_COUNT", "6"),
    "courses": env_int("AI_UPDATES_COURSES_VISIBLE_COUNT", "2"),
    "movies": env_int("AI_UPDATES_MOVIES_VISIBLE_COUNT", "1"),
}

BACKUP_NEWS_COUNT = env_int("AI_UPDATES_BACKUP_COUNT", "6")
TOTAL_NEWS_TARGET = DISPLAY_COUNTS["items"] + BACKUP_NEWS_COUNT
SAVE_NEWS_BACKUP_FROM_SELECTION = env_bool("AI_UPDATES_SAVE_BACKUP_FROM_SELECTION", "1")
AI_UPDATES_SCAN_POOL_LIMIT = env_int("AI_UPDATES_SCAN_POOL_LIMIT", "120")
AI_UPDATES_GPT_SHORTLIST_LIMIT = env_int("AI_UPDATES_GPT_SHORTLIST_LIMIT", "60")
AI_UPDATES_TOOL_CACHE_REFRESH_DAYS = env_int("AI_UPDATES_TOOL_CACHE_REFRESH_DAYS", "30")
AI_UPDATES_TOOL_CACHE_MAX_RECORDS = env_int("AI_UPDATES_TOOL_CACHE_MAX_RECORDS", "120")
AI_UPDATES_TOOL_DISCOVERY_ENABLED = env_bool("AI_UPDATES_TOOL_DISCOVERY_ENABLED", "1")
AI_UPDATES_TOOL_DISCOVERY_MODEL = os.getenv("AI_UPDATES_TOOL_DISCOVERY_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
AI_UPDATES_TOOL_DISCOVERY_RESULTS = env_int("AI_UPDATES_TOOL_DISCOVERY_RESULTS", "6")

SUPPORTING_CONTENT_ENABLED = env_bool("AI_UPDATES_REFRESH_SUPPORTING_CONTENT", "1")
SUPPORTING_CONTENT_PREFETCH = env_bool("AI_UPDATES_SUPPORTING_CONTENT_PREFETCH", "1")
SUPPORTING_COURSE_FETCH_POOL = env_int("AI_UPDATES_SUPPORTING_COURSE_FETCH_POOL", "10")
SUPPORTING_MOVIE_FETCH_POOL = env_int("AI_UPDATES_SUPPORTING_MOVIE_FETCH_POOL", "40")
DAEMON_ENABLED = env_bool("AI_UPDATES_DAEMON_ENABLED", "0")
DAEMON_INTERVAL_SECONDS = env_int("AI_UPDATES_INTERVAL", "3600")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("AI_UPDATES_OPENAI_MODEL", "gpt-5.2").strip() or "gpt-5.2"
EXA_API_KEY = os.getenv("EXA_API_KEY", "").strip()
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()

# Course discovery is intentionally locked to this trusted domain list. Exa can
# search broadly inside these domains, but outside platforms are rejected.
COURSE_DOMAINS = [
    "coursera.org",
    "udemy.com",
    "edx.org",
    "linkedin.com/learning",
    "skillshare.com",
    "masterclass.com",
    "domestika.org",
    "pluralsight.com",
    "futurelearn.com",
    "udacity.com",
    "deeplearning.ai",
    "fast.ai",
    "huggingface.co/learn",
    "learnprompting.org",
    "promptingguide.ai",
    "anthropic.com/learn",
    "openai.com/research",
    "microsoft.com/learn",
    "google.com/learn",
    "nvidia.com/dli",
    "adobe.com/learn",
    "canva.com/learn",
    "figma.com/resources",
    "superhi.com",
    "awwwards.com/academy",
    "edraak.org",
    "rwaq.org",
    "doroob.com.sa",
    "ncle.gov.sa",
    "almentor.net",
    "khamsat.com/learning",
]


def _course_domain_host(value: str) -> str:
    try:
        host = urlparse(f"https://{str(value or '').strip().lstrip('/')}").netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


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
    "startPublishedDate": os.getenv("AI_UPDATES_COURSE_START_PUBLISHED_DATE", "2026-01-01").strip() or "2026-01-01",
    "numResults": env_int("AI_UPDATES_COURSE_NUM_RESULTS", "10"),
    "type": os.getenv("AI_UPDATES_COURSE_EXA_TYPE", "neural").strip() or "neural",
}
_COURSE_QUERY_VARIANT_DEFAULTS = [
    "site:coursera.org AI course beginner intermediate generative AI",
    "site:deeplearning.ai short course generative AI prompt engineering",
    "site:microsoft.com/learn AI training beginner intermediate productivity",
    "site:linkedin.com/learning AI course beginner intermediate workplace",
    "site:edx.org AI course beginner intermediate certificate",
    "site:google.com/learn AI course beginner intermediate",
    "site:openai.com/academy AI course learn ChatGPT workplace",
    "site:anthropic.com/learn AI course prompt engineering beginner intermediate",
    "site:canva.com/learn AI design course creators",
    "site:adobe.com/learn AI creative course beginners",
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

AI_UPDATES_LOOKBACK_DAYS = env_int("AI_UPDATES_LOOKBACK_DAYS", "14")
AI_UPDATES_OUTPUT_LIMIT = env_int("AI_UPDATES_OUTPUT_LIMIT", str(TOTAL_NEWS_TARGET))
AI_UPDATES_GPT_COMPACT_LIMIT = env_int("AI_UPDATES_GPT_COMPACT_LIMIT", "60")
AI_UPDATES_SINGLE_OUTPUT_LIMIT = env_int("AI_UPDATES_SINGLE_OUTPUT_LIMIT", "5")
AI_UPDATES_SINGLE_GPT_COMPACT_LIMIT = env_int("AI_UPDATES_SINGLE_GPT_COMPACT_LIMIT", "36")

AI_UPDATES_SEARXNG_QUERY_LIMIT = env_int("AI_UPDATES_SEARXNG_QUERY_LIMIT", "40")
AI_UPDATES_SEARXNG_RESULTS_PER_QUERY = env_int("AI_UPDATES_SEARXNG_RESULTS_PER_QUERY", "8")
AI_UPDATES_SEARXNG_TIMEOUT = env_int("AI_UPDATES_SEARXNG_TIMEOUT", "12")
AI_UPDATES_SEARXNG_TIME_RANGE = os.getenv("AI_UPDATES_SEARXNG_TIME_RANGE", "month").strip() or "month"
AI_UPDATES_SEARXNG_CATEGORIES = os.getenv("AI_UPDATES_SEARXNG_CATEGORIES", "news,it,general").strip() or "news,it,general"

AI_UPDATES_EXA_QUERY_LIMIT = env_int("AI_UPDATES_EXA_QUERY_LIMIT", "40")
AI_UPDATES_EXA_RESULTS_PER_QUERY = env_int("AI_UPDATES_EXA_RESULTS_PER_QUERY", "5")
AI_UPDATES_EXA_TIMEOUT = env_int("AI_UPDATES_EXA_TIMEOUT", "10")
AI_UPDATES_COURSE_EXA_QUERY_LIMIT = env_int("AI_UPDATES_COURSE_EXA_QUERY_LIMIT", "4")
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
AI_UPDATES_SEMANTIC_MAX_CHECK = env_int("AI_UPDATES_SEMANTIC_MAX_CHECK", "32")
AI_UPDATES_SINGLE_SEMANTIC_MAX_CHECK = env_int("AI_UPDATES_SINGLE_SEMANTIC_MAX_CHECK", "24")
AI_UPDATES_MEMORY_EXACT_LIMIT = env_int("AI_UPDATES_MEMORY_EXACT_LIMIT", "3000")
AI_UPDATES_EMBED_MODEL = os.getenv("AI_UPDATES_EMBED_MODEL", "text-embedding-3-small").strip() or "text-embedding-3-small"
AI_UPDATES_EMBED_INPUT_LIMIT = env_int("AI_UPDATES_EMBED_INPUT_LIMIT", "1200")
AI_UPDATES_EMBED_SIZE = env_int("AI_UPDATES_EMBED_SIZE", "1536")
AI_UPDATES_QDRANT_COLLECTION = os.getenv("AI_UPDATES_QDRANT_COLLECTION", "content_memory").strip() or "content_memory"
AI_UPDATES_SEMANTIC_DUPLICATE_SCORE = float(os.getenv("AI_UPDATES_SEMANTIC_DUPLICATE_SCORE", "0.925") or "0.925")
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
    "الذكاء الاصطناعي والتعلي",
    "والتدريب والمهام اليومية",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def recency_cutoff() -> datetime:
    return utc_now() - timedelta(days=max(1, AI_UPDATES_LOOKBACK_DAYS))


def recency_cutoff_query_token() -> str:
    return recency_cutoff().date().isoformat()


def clean_text(value: str = "") -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalized_text(value: str = "") -> str:
    text = re.sub(r"https?://(www\.)?", " ", str(value or "").lower())
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def source_domain(url: str = "") -> str:
    try:
        host = urlparse(str(url or "")).netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def memory_url_key(url: str = "") -> str:
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return str(url or "").strip().lower().rstrip("/")
    if not parsed.netloc:
        return str(url or "").strip().lower().rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}".rstrip("/")


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


def result_is_recent_enough(value) -> bool:
    dt = parse_result_datetime(value)
    return dt is None or dt >= recency_cutoff()
