"""Quality filters, dedupe, and Qdrant semantic memory.

This file does not write newsletter copy. It removes bad sources, exact
duplicates, same-story duplicates, and semantic repeats before GPT sees the
shortlist.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import Counter, defaultdict

from openai import OpenAI

from .config import (
    AI_UPDATES_EMBED_INPUT_LIMIT,
    AI_UPDATES_EMBED_MODEL,
    AI_UPDATES_EMBED_SIZE,
    AI_UPDATES_MEMORY_ENABLED,
    AI_UPDATES_MEMORY_EXACT_LIMIT,
    AI_UPDATES_QDRANT_COLLECTION,
    AI_UPDATES_REJECTED_DUPLICATE_SCORE,
    AI_UPDATES_SEMANTIC_DUPLICATE_SCORE,
    AI_UPDATES_SEMANTIC_MAX_CHECK,
    AI_UPDATES_SEMANTIC_MEMORY_ENABLED,
    AI_UPDATES_SINGLE_SEMANTIC_MAX_CHECK,
    COURSE_INCLUDE_DOMAINS,
    OPENAI_API_KEY,
    QDRANT_DB_DIR,
    memory_url_key,
    normalized_text,
    source_domain,
    utc_now,
)
from .fetchers import candidate_owner_key, infer_sector

# Course cards must come only from the configured Exa includeDomains bank.
# Keep this tied to COURSE_DOMAINS/COURSE_INCLUDE_DOMAINS so a supplement
# source cannot introduce courses from unapproved platforms.
TRUSTED_COURSE_DOMAINS = set(COURSE_INCLUDE_DOMAINS)

MOVIE_AI_TERMS = {
    "artificial intelligence",
    "a.i.",
    "machine intelligence",
    "synthetic intelligence",
    "superintelligence",
    "sentient machine",
    "sentient computer",
    "self-aware computer",
    "self aware computer",
    "self-aware robot",
    "self aware robot",
    "autonomous intelligence",
    "computer intelligence",
    "virtual intelligence",
    "ai system",
    "ai assistant",
    "neural network",
    "algorithmic decision",
}

MOVIE_BLOCKED_TERMS = {
    " sex",
    "sexual",
    "erotic",
    "porn",
    "adult",
    "nsfw",
    "hot night",
    "sex robot",
    "prostitute",
    "brothel",
    "fetish",
}
MOVIE_SUBSTANTIAL_SIGNAL_MIN_VOTES = 10
MOVIE_SUBSTANTIAL_SIGNAL_MIN_POPULARITY = 2.0

SUPPORTING_SPAM_TERMS = {
    "top 10",
    "best ",
    "alternatives",
    "coupon",
    "promo code",
    "download free",
}

ADVANCED_COURSE_TERMS = {
    "advanced",
    "advanced-level",
    "advanced level",
    "graduate-level",
    "graduate level",
    "postgraduate",
    "intermediate to advanced",
}

# qdrant_client is optional at import time. If it is not installed or the local
# Qdrant folder is locked by another process, the pipeline degrades to exact
# in-run dedupe instead of crashing the Generate flow.
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams
except Exception:
    QdrantClient = None
    Distance = None
    FieldCondition = None
    Filter = None
    MatchValue = None
    PointStruct = None
    VectorParams = None

_QDRANT_LOCK = threading.Lock()
_BORROWED_QDRANT_IDS = set()
_QDRANT_LOCK_WARNING_SHOWN = False
_openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

TECH_OR_NEWS_DOMAINS = {
    "techcrunch.com",
    "theverge.com",
    "venturebeat.com",
    "wired.com",
    "zdnet.com",
    "technologyreview.com",
    "arstechnica.com",
    "thenextweb.com",
    "digitaltrends.com",
    "engadget.com",
    "cnet.com",
    "forbes.com",
    "businessinsider.com",
    "yahoo.com",
    "news.google.com",
}

def item_title_key(item: dict) -> str:
    return normalized_text(item.get("title") or item.get("original_title") or "")


SAME_STORY_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "that", "this", "your", "users", "user",
    "new", "now", "available", "launch", "launches", "launched", "release", "released",
    "update", "updates", "feature", "features", "capability", "capabilities", "adds",
    "add", "ai", "artificial", "intelligence", "tool", "tools", "app", "product",
    "official", "announcement", "announces", "rolling", "rollout", "can", "use", "using",
    "inside", "platform", "model", "assistant", "technology",
    "الذكاء", "الاصطناعي", "ذكاء", "اصطناعي", "تحديث", "جديد", "ميزة", "إطلاق",
    "يطلق", "تطلق", "أطلقت", "أعلن", "أعلنت", "المستخدم", "المستخدمين", "داخل",
    "يمكن", "يتيح", "تتيح", "يسمح", "تسمح", "الأداة", "التطبيق", "المنتج",
}

STORY_TOKEN_ALIASES = {
    "citation": "source",
    "citations": "source",
    "cite": "source",
    "cites": "source",
    "cited": "source",
    "sources": "source",
    "conversation": "chat",
    "conversations": "chat",
    "chats": "chat",
    "images": "image",
    "photos": "image",
    "pictures": "image",
    "videos": "video",
    "clips": "video",
    "voices": "voice",
    "audio": "voice",
    "audios": "voice",
    "designs": "design",
    "designing": "design",
    "searches": "search",
    "searching": "search",
    "researching": "research",
    "researches": "research",
}

SAME_STORY_STRONG_TOKENS = {
    "agent",
    "archive",
    "browser",
    "canvas",
    "chat",
    "code",
    "coding",
    "design",
    "editing",
    "image",
    "research",
    "search",
    "source",
    "translation",
    "video",
    "voice",
    "web",
    "workspace",
}


def story_owner_key(item: dict) -> str:
    return (
        item.get("owner_key")
        or candidate_owner_key(
            item,
            url=item.get("url") or item.get("official_url") or "",
            title=item.get("title") or item.get("original_title") or "",
            content=item.get("content") or item.get("summary") or item.get("text") or "",
        )
    )


def story_tokens(item: dict) -> set[str]:
    text = " ".join(
        str(item.get(key) or "")
        for key in (
            "title",
            "original_title",
            "content",
            "summary",
            "text",
            "source_update_signal",
            "tool_name",
            "tool",
            "company_name",
            "company",
            "source_query",
            "query",
            "source_title",
        )
    ).lower()
    tokens = set()
    for token in re.findall(r"[\w\u0600-\u06ff]{3,}", text, flags=re.UNICODE):
        if token in SAME_STORY_STOPWORDS or token.isdigit():
            continue
        tokens.add(STORY_TOKEN_ALIASES.get(token, token))
    owner_tokens = set(str(story_owner_key(item) or "").replace("-", " ").split())
    return tokens - owner_tokens


def same_story_tokens(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    overlap = len(left & right)
    if overlap < 4:
        if overlap < 3 or not (left & right & SAME_STORY_STRONG_TOKENS):
            return False
    smaller = min(len(left), len(right)) or 1
    union = len(left | right) or 1
    return (
        overlap >= 5
        or (overlap / smaller) >= 0.65
        or (overlap / union) >= 0.42
        or (overlap >= 3 and (overlap / smaller) >= 0.38 and (left & right & SAME_STORY_STRONG_TOKENS))
    )


def items_same_story(left: dict, right: dict) -> bool:
    """Return True when two candidates describe the same update/story."""
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    left_story = str(left.get("story_key") or item_story_key(left) or "").strip()
    right_story = str(right.get("story_key") or item_story_key(right) or "").strip()
    if left_story and right_story and left_story == right_story:
        return True
    left_owner = story_owner_key(left)
    right_owner = story_owner_key(right)
    if left_owner and right_owner and left_owner != right_owner:
        return False
    return same_story_tokens(story_tokens(left), story_tokens(right))


def item_story_key(item: dict) -> str:
    owner = normalized_text(story_owner_key(item))
    words = sorted(story_tokens(item))[:14]
    return hashlib.sha1(f"{owner}|{' '.join(words)}".encode("utf-8")).hexdigest()[:24]


def rank_candidates(items: list[dict]) -> list[dict]:
    """Order candidates before memory checks so high-signal items survive caps."""
    """Add lightweight market/source signals without deciding the final story order."""
    owner_counts = Counter(item.get("owner_key") or source_domain(item.get("url") or "") for item in items or [])
    owner_sources = defaultdict(set)
    for item in items or []:
        owner = item.get("owner_key") or source_domain(item.get("url") or "")
        if owner:
            owner_sources[owner].add(source_domain(item.get("url") or ""))

    for item in items or []:
        item["sector"] = item.get("sector") or infer_sector(item.get("title") or "", item.get("content") or "", item.get("bucket") or "")
        item["story_key"] = item.get("story_key") or item_story_key(item)
        owner = item.get("owner_key") or source_domain(item.get("url") or "")
        domain = source_domain(item.get("url") or "")
        item["market_signals"] = {
            "repeat_mentions": int(owner_counts.get(owner, 0)),
            "multi_source": len(owner_sources.get(owner, set())) > 1,
            "source_type": "tech_media" if any(domain == root or domain.endswith(f".{root}") for root in TECH_OR_NEWS_DOMAINS) else "product_or_official_site",
        }
    return list(items or [])


def ensure_qdrant_collection(qdrant) -> bool:
    """Create the shared memory collection when using local or borrowed Qdrant."""
    if qdrant is None:
        return False
    try:
        names = [collection.name for collection in qdrant.get_collections().collections]
        if AI_UPDATES_QDRANT_COLLECTION not in names and VectorParams is not None:
            qdrant.create_collection(
                collection_name=AI_UPDATES_QDRANT_COLLECTION,
                vectors_config=VectorParams(size=AI_UPDATES_EMBED_SIZE, distance=Distance.COSINE),
            )
        return True
    except Exception:
        return False


def borrowed_qdrant_memory():
    """No legacy Qdrant borrowing; the modular pipeline owns memory access."""
    return None


def open_qdrant_memory():
    """Open Qdrant memory safely for the modular pipeline."""
    global _QDRANT_LOCK_WARNING_SHOWN
    if not AI_UPDATES_MEMORY_ENABLED or QdrantClient is None:
        return None
    borrowed = borrowed_qdrant_memory()
    if borrowed is not None:
        return borrowed
    try:
        QDRANT_DB_DIR.mkdir(parents=True, exist_ok=True)
        qdrant = QdrantClient(path=str(QDRANT_DB_DIR))
        ensure_qdrant_collection(qdrant)
        return qdrant
    except Exception as exc:
        if not _QDRANT_LOCK_WARNING_SHOWN:
            print(f"[AI Updates] Qdrant memory skipped: {exc}", flush=True)
            _QDRANT_LOCK_WARNING_SHOWN = True
        return None


def close_qdrant_memory(qdrant) -> None:
    try:
        if qdrant is not None:
            if id(qdrant) in _BORROWED_QDRANT_IDS:
                return
            qdrant.close()
    except Exception:
        pass


def qdrant_type_filter(content_type: str = "news"):
    if Filter is None or FieldCondition is None or MatchValue is None:
        return None
    return Filter(must=[FieldCondition(key="type", match=MatchValue(value=content_type))])


def semantic_text(item: dict) -> str:
    return " ".join([
        str(item.get("title") or ""),
        str(item.get("original_title") or ""),
        str(item.get("content") or item.get("text") or item.get("summary") or ""),
        str(item.get("company") or item.get("company_name") or item.get("tool_name") or ""),
        str(item.get("sector") or ""),
        str(item.get("bucket") or item.get("source_bucket") or ""),
        source_domain(item.get("url") or item.get("official_url") or ""),
    ])[:AI_UPDATES_EMBED_INPUT_LIMIT]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts or _openai_client is None:
        return []
    try:
        response = _openai_client.embeddings.create(model=AI_UPDATES_EMBED_MODEL, input=texts)
        return [item.embedding for item in response.data]
    except Exception as exc:
        print(f"[AI Updates] semantic embeddings skipped: {exc}", flush=True)
        return []


def load_exact_memory(diagnostics: dict, *, content_type: str = "news") -> dict:
    """Load URL/title/story keys for fast exact duplicate blocking."""
    entries = {"urls": set(), "titles": set(), "stories": set()}
    diagnostics["memory_enabled"] = bool(AI_UPDATES_MEMORY_ENABLED)
    diagnostics["semantic_memory_enabled"] = bool(AI_UPDATES_SEMANTIC_MEMORY_ENABLED)
    diagnostics["memory_content_type"] = content_type
    if not AI_UPDATES_MEMORY_ENABLED:
        diagnostics["memory_exact_available"] = False
        diagnostics["memory_status"] = "disabled"
        return entries
    started = time.time()
    with _QDRANT_LOCK:
        qdrant = open_qdrant_memory()
        if qdrant is None:
            diagnostics["memory_exact_available"] = False
            diagnostics["memory_status"] = "qdrant_unavailable"
            return entries
        try:
            diagnostics["memory_exact_available"] = True
            records, _ = qdrant.scroll(
                collection_name=AI_UPDATES_QDRANT_COLLECTION,
                scroll_filter=qdrant_type_filter(content_type),
                limit=AI_UPDATES_MEMORY_EXACT_LIMIT,
                with_payload=True,
                with_vectors=False,
            )
            for record in records:
                payload = getattr(record, "payload", {}) or {}
                url = memory_url_key(payload.get("url") or "")
                title = normalized_text(payload.get("title") or "")
                story = str(payload.get("story_key") or payload.get("story_signature") or "").strip()
                if url:
                    entries["urls"].add(url)
                if title:
                    entries["titles"].add(title)
                if story:
                    entries["stories"].add(story)
            diagnostics["memory_exact_entries"] = len(entries["urls"]) + len(entries["titles"]) + len(entries["stories"])
            diagnostics["memory_status"] = "exact_loaded"
        except Exception as exc:
            diagnostics["memory_exact_error"] = str(exc)
            diagnostics["memory_status"] = "exact_error"
        finally:
            close_qdrant_memory(qdrant)
    diagnostics["memory_exact_seconds"] = round(time.time() - started, 2)
    return entries


def semantic_duplicate(qdrant, item: dict, vector: list[float], *, content_type: str = "news") -> tuple[bool, str]:
    """Check Qdrant cosine similarity against previous visible selections."""
    """Check one candidate vector against final and rejected memory records."""
    if qdrant is None or not vector:
        return False, ""
    try:
        result = qdrant.query_points(
            collection_name=AI_UPDATES_QDRANT_COLLECTION,
            query=vector,
            limit=3,
            query_filter=qdrant_type_filter(content_type),
        )
        points = list(getattr(result, "points", []) or [])
    except Exception as exc:
        return False, f"qdrant_query_error:{exc}"
    item_story = str(item.get("story_key") or item_story_key(item))
    item_url = memory_url_key(item.get("url") or "")
    for point in sorted(points, key=lambda p: float(getattr(p, "score", 0) or 0), reverse=True):
        score = float(getattr(point, "score", 0) or 0)
        payload = getattr(point, "payload", {}) or {}
        stage = str(payload.get("memory_stage") or "")
        threshold = AI_UPDATES_REJECTED_DUPLICATE_SCORE if stage == "rejected" else AI_UPDATES_SEMANTIC_DUPLICATE_SCORE
        if score < threshold:
            continue
        if item_url and item_url == memory_url_key(payload.get("url") or ""):
            return True, "semantic_same_url_memory_duplicate"
        if item_story and item_story == str(payload.get("story_key") or payload.get("story_signature") or ""):
            return True, "semantic_same_story_memory_duplicate"
        return True, "semantic_rejected_memory_duplicate" if stage == "rejected" else "semantic_memory_duplicate"
    return False, ""


def filter_candidates(items: list[dict], diagnostics: dict, *, semantic_limit: int, content_type: str = "news") -> list[dict]:
    """Run exact memory and bounded semantic memory over normalized candidates."""
    """Run exact memory, same-run dedupe, and a capped semantic duplicate pass."""
    if not items:
        return []
    started = time.time()
    ranked = rank_candidates(items)
    memory = load_exact_memory(diagnostics, content_type=content_type)
    exact_kept = []
    seen_urls = set()
    seen_titles = set()
    seen_stories = set()
    seen_story_fingerprints: list[tuple[str, set[str]]] = []
    exact_skipped = 0
    same_run_skipped = 0
    same_run_story_skipped = 0
    for item in ranked:
        url = memory_url_key(item.get("url") or "")
        title = item_title_key(item)
        story = item.get("story_key") or item_story_key(item)
        if (url and url in memory["urls"]) or (title and title in memory["titles"]) or (story and story in memory["stories"]):
            exact_skipped += 1
            continue
        if (url and url in seen_urls) or (title and title in seen_titles) or (story and story in seen_stories):
            same_run_skipped += 1
            continue
        owner = story_owner_key(item)
        tokens = story_tokens(item)
        if owner and any(owner == seen_owner and same_story_tokens(tokens, seen_tokens) for seen_owner, seen_tokens in seen_story_fingerprints):
            same_run_story_skipped += 1
            continue
        seen_urls.add(url)
        seen_titles.add(title)
        seen_stories.add(story)
        if owner and tokens:
            seen_story_fingerprints.append((owner, tokens))
        exact_kept.append(item)

    diagnostics["memory_exact_skipped"] = exact_skipped
    diagnostics["same_run_duplicates_skipped"] = same_run_skipped
    diagnostics["same_run_story_duplicates_skipped"] = same_run_story_skipped
    if not AI_UPDATES_SEMANTIC_MEMORY_ENABLED or not exact_kept:
        diagnostics["semantic_memory_available"] = False if not AI_UPDATES_SEMANTIC_MEMORY_ENABLED else diagnostics.get("memory_exact_available", False)
        diagnostics["semantic_memory_checked"] = 0
        diagnostics["semantic_memory_skipped"] = 0
        diagnostics["memory_filter_seconds"] = round(time.time() - started, 2)
        diagnostics["memory_filter_status"] = "exact_only"
        return exact_kept

    checked = exact_kept[: max(0, semantic_limit)]
    unchecked = exact_kept[len(checked):]
    diagnostics["semantic_memory_requested"] = len(checked)
    vectors = embed_texts([semantic_text(item) for item in checked])
    if len(vectors) != len(checked):
        diagnostics["semantic_memory_checked"] = 0
        diagnostics["semantic_memory_available"] = False
        diagnostics["memory_filter_status"] = "embedding_failed"
        diagnostics["memory_filter_seconds"] = round(time.time() - started, 2)
        return exact_kept

    semantic_kept = []
    semantic_skipped = 0
    with _QDRANT_LOCK:
        qdrant = open_qdrant_memory()
        if qdrant is None:
            diagnostics["semantic_memory_available"] = False
            diagnostics["memory_filter_status"] = "qdrant_unavailable"
            diagnostics["memory_filter_seconds"] = round(time.time() - started, 2)
            return exact_kept
        try:
            diagnostics["semantic_memory_available"] = True
            for item, vector in zip(checked, vectors):
                duplicate, reason = semantic_duplicate(qdrant, item, vector, content_type=content_type)
                if duplicate:
                    semantic_skipped += 1
                    continue
                if reason.startswith("qdrant_query_error"):
                    diagnostics.setdefault("semantic_memory_errors", []).append(reason[:180])
                semantic_kept.append(item)
        finally:
            close_qdrant_memory(qdrant)

    result = rank_candidates(semantic_kept + unchecked)
    diagnostics["semantic_memory_checked"] = len(checked)
    diagnostics["semantic_memory_skipped"] = semantic_skipped
    diagnostics["memory_filter_seconds"] = round(time.time() - started, 2)
    diagnostics["memory_filter_status"] = "semantic_checked"
    print(
        f"[AI Updates] memory filter kept={len(result)}/{len(items)} "
        f"exact={exact_skipped} semantic={semantic_skipped} "
        f"status={diagnostics['memory_filter_status']} time={diagnostics['memory_filter_seconds']}s",
        flush=True,
    )
    return result


def filter_news_candidates(candidates: list[dict], diagnostics: dict, *, single: bool = False) -> list[dict]:
    """Filter news candidates before the large-scan shortlist is built."""
    """News-specific wrapper that uses a smaller semantic window for single refill."""
    semantic_limit = AI_UPDATES_SINGLE_SEMANTIC_MAX_CHECK if single else AI_UPDATES_SEMANTIC_MAX_CHECK
    diagnostics["valid_before_memory"] = len(candidates or [])
    filtered = filter_candidates(candidates or [], diagnostics, semantic_limit=semantic_limit, content_type="news")
    diagnostics["unique_results"] = len(filtered)
    return filtered


def domain_matches(domain: str, allowed: set[str]) -> bool:
    domain = (domain or "").lower().replace("www.", "")
    return any(domain == root or domain.endswith(f".{root}") for root in allowed)


def support_text(item: dict) -> str:
    return " ".join(str(item.get(key) or "") for key in ("title", "text", "summary", "content", "source")).lower()


def supporting_identity_keys(item: dict) -> tuple[str, str, str]:
    """Return stable keys used to avoid showing the same support card again."""
    return (
        memory_url_key(item.get("url") or item.get("official_url") or ""),
        normalized_text(item.get("title") or item.get("original_title") or ""),
        str(item.get("story_key") or item_story_key(item) or "").strip(),
    )


def supporting_visible_key_sets(items: list[dict] | None) -> dict[str, set[str]]:
    """Build URL/title/story lookup sets for currently visible course/movie cards."""
    keys = {"urls": set(), "titles": set(), "stories": set()}
    for item in items or []:
        url, title, story = supporting_identity_keys(item if isinstance(item, dict) else {})
        if url:
            keys["urls"].add(url)
        if title:
            keys["titles"].add(title)
        if story:
            keys["stories"].add(story)
    return keys


def supporting_matches_visible(item: dict, visible_keys: dict[str, set[str]]) -> bool:
    """True when a candidate is already displayed in the current newsletter."""
    url, title, story = supporting_identity_keys(item)
    return (
        bool(url and url in visible_keys["urls"])
        or bool(title and title in visible_keys["titles"])
        or bool(story and story in visible_keys["stories"])
    )


def movie_has_direct_ai_signal(text: str = "") -> bool:
    """Return True only when the movie text directly indicates AI, not generic tech."""
    normalized = f" {str(text or '').lower()} "
    if re.search(r"\bai\b|\ba\.i\.\b", normalized):
        return True
    return any(term in normalized for term in MOVIE_AI_TERMS)


def supporting_reject_reason(item: dict, content_type: str) -> str:
    if not isinstance(item, dict):
        return "invalid_item"
    title = str(item.get("title") or "").strip()
    url = str(item.get("url") or "").strip()
    text = support_text(item)
    if not title or not url or url == "#":
        return "missing_title_or_url"
    if any(term in text for term in SUPPORTING_SPAM_TERMS):
        return "seo_or_affiliate_content"
    if content_type == "course":
        domain = source_domain(url)
        if not domain_matches(domain, TRUSTED_COURSE_DOMAINS):
            return "untrusted_course_domain"
        if str(item.get("level") or "").strip().lower() == "advanced" or any(term in text for term in ADVANCED_COURSE_TERMS):
            return "advanced_course_level"
        return ""
    if content_type == "movie":
        if str(item.get("adult") or "").lower() in {"1", "true", "yes"}:
            return "adult_movie"
        if any(term in f" {text}" for term in MOVIE_BLOCKED_TERMS):
            return "adult_or_exploitative_movie"
        if not (item.get("poster") or item.get("image")):
            return "missing_movie_poster"
        if len(text) < 80:
            return "weak_movie_overview"
        if not movie_has_direct_ai_signal(text):
            return "movie_not_ai_related"
        try:
            votes = float(item.get("vote_count") or 0)
            popularity = float(item.get("popularity") or 0)
            if votes < MOVIE_SUBSTANTIAL_SIGNAL_MIN_VOTES and popularity < MOVIE_SUBSTANTIAL_SIGNAL_MIN_POPULARITY:
                return "weak_movie_signal"
        except (TypeError, ValueError):
            pass
        return ""
    return ""


def filter_supporting_candidates(
    candidates: list[dict],
    content_type: str,
    limit: int,
    *,
    visible_items: list[dict] | None = None,
) -> list[dict]:
    """Filter course/movie candidates and compare only against visible cards."""
    """Quality and memory filter for supporting course/movie candidate lists."""
    diagnostics = {}
    cleaned = []
    rejected = {}
    visible_keys = supporting_visible_key_sets(visible_items)
    visible_skipped = 0
    for item in candidates or []:
        reason = supporting_reject_reason(item, content_type)
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        if supporting_matches_visible(item, visible_keys):
            visible_skipped += 1
            continue
        cleaned.append(item)
    if rejected:
        print(f"[AI Updates] {content_type} quality rejected: {rejected}", flush=True)
    if visible_skipped:
        print(f"[AI Updates] {content_type} current visible skipped: {visible_skipped}", flush=True)
    filtered = filter_candidates(cleaned, diagnostics, semantic_limit=12, content_type=content_type)
    if len(filtered) >= min(limit, len(cleaned)):
        return filtered[:limit]

    # Supporting cards should not freeze forever because old Qdrant records
    # remember past cards. Keep the current visible cards blocked, but if memory
    # removes too much, refill from quality-clean candidates in this run.
    seen = set()
    relaxed = []
    for item in filtered + cleaned:
        key = supporting_identity_keys(item)
        compact_key = tuple(part for part in key if part)
        if compact_key and compact_key in seen:
            continue
        if compact_key:
            seen.add(compact_key)
        relaxed.append(item)
        if len(relaxed) >= limit:
            break
    added = max(0, len(relaxed) - len(filtered))
    if added:
        print(
            f"[AI Updates] {content_type} memory relaxed fallback added={added} "
            f"filtered={len(filtered)} clean={len(cleaned)}",
            flush=True,
        )
    return relaxed[:limit]


def save_memory(items: list[dict], content_type: str, diagnostics: dict | None = None) -> int:
    """Persist visible selections into exact and semantic memory."""
    """Persist final selected items in Qdrant so future runs avoid repetition."""
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    diagnostics["memory_save_requested"] = len(items or [])
    diagnostics["memory_save_content_type"] = content_type
    diagnostics["memory_save_enabled"] = bool(AI_UPDATES_MEMORY_ENABLED)
    if not AI_UPDATES_MEMORY_ENABLED or not items or PointStruct is None:
        diagnostics["memory_save_status"] = "disabled_or_empty"
        return 0
    vectors = embed_texts([semantic_text(item) for item in items])
    diagnostics["memory_save_embedding_count"] = len(vectors)
    if len(vectors) != len(items):
        diagnostics["memory_save_error"] = "embedding_failed"
        diagnostics["memory_save_status"] = "embedding_failed"
        return 0
    now = utc_now().isoformat()
    points = []
    for item, vector in zip(items, vectors):
        url = item.get("url") or item.get("official_url") or ""
        title = item.get("title") or item.get("original_title") or ""
        story = item.get("story_key") or item_story_key(item)
        uid = hashlib.md5(f"{content_type}|final|{title}|{url}".encode("utf-8", errors="ignore")).hexdigest()
        points.append(PointStruct(
            id=uid,
            vector=vector,
            payload={
                "title": title,
                "url": url,
                "type": content_type,
                "memory_stage": "final",
                "saved_at": now,
                "story_key": story,
                "story_signature": story,
                "source_domain": source_domain(url),
                "company": item.get("company") or item.get("company_name") or "",
            },
        ))
    with _QDRANT_LOCK:
        qdrant = open_qdrant_memory()
        if qdrant is None:
            diagnostics["memory_save_error"] = "qdrant_unavailable"
            diagnostics["memory_save_status"] = "qdrant_unavailable"
            print(f"[AI Updates] semantic memory save failed: qdrant_unavailable type={content_type}", flush=True)
            return 0
        try:
            qdrant.upsert(collection_name=AI_UPDATES_QDRANT_COLLECTION, points=points)
            saved = len(points)
            diagnostics["memory_save_status"] = "saved"
        except Exception as exc:
            diagnostics["memory_save_error"] = str(exc)
            diagnostics["memory_save_status"] = "upsert_failed"
            saved = 0
        finally:
            close_qdrant_memory(qdrant)
    diagnostics["memory_save_count"] = saved
    if saved:
        print(f"[AI Updates] saved semantic memory item(s): {saved} type={content_type}", flush=True)
    else:
        print(
            f"[AI Updates] semantic memory save failed: "
            f"{diagnostics.get('memory_save_error') or diagnostics.get('memory_save_status')} type={content_type}",
            flush=True,
        )
    return saved


def save_news_memory(items: list[dict], diagnostics: dict | None = None) -> int:
    return save_memory(items or [], "news", diagnostics)


def save_supporting_memory(items: list[dict], content_type: str) -> None:
    save_memory(items or [], content_type, {})
