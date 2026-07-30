"""Course and film filtering helpers."""

from __future__ import annotations

import re

from backend.config.settings import COURSE_INCLUDE_DOMAINS, domain_matches, memory_url_key, normalized_text, source_domain
from backend.pipeline.fetching.content.courses.discovery import course_url_is_direct
from backend.pipeline.filtering.shared.memory import filter_candidates, item_story_key, save_memory

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

SUPPORTING_SPAM_TERMS = {
    "top 10",
    "best ",
    "alternatives",
    "coupon",
    "promo code",
    "download free",
}

TRUSTED_COURSE_DOMAINS = set(COURSE_INCLUDE_DOMAINS)
MOVIE_SUBSTANTIAL_SIGNAL_MIN_VOTES = 10
MOVIE_SUBSTANTIAL_SIGNAL_MIN_POPULARITY = 2.0


# Performs the support text helper step.

def support_text(item: dict) -> str:
    return " ".join(str(item.get(key) or "") for key in ("title", "text", "summary", "content", "source")).lower()


# Performs the supporting identity keys helper step.

def supporting_identity_keys(item: dict) -> tuple[str, str, str]:
    """Return stable keys used to avoid showing the same support card again."""
    return (
        memory_url_key(item.get("url") or item.get("official_url") or ""),
        normalized_text(item.get("title") or item.get("original_title") or ""),
        str(item.get("story_key") or item_story_key(item) or "").strip(),
    )


# Performs the supporting visible key sets helper step.

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


# Performs the supporting matches visible helper step.

def supporting_matches_visible(item: dict, visible_keys: dict[str, set[str]]) -> bool:
    """True when a candidate is already displayed in the current newsletter."""
    url, title, story = supporting_identity_keys(item)
    return (
        bool(url and url in visible_keys["urls"])
        or bool(title and title in visible_keys["titles"])
        or bool(story and story in visible_keys["stories"])
    )


# Performs the movie has direct ai signal helper step.

def movie_has_direct_ai_signal(text: str = "") -> bool:
    """Return True only when the movie text directly indicates AI, not generic tech."""
    normalized = f" {str(text or '').lower()} "
    if re.search(r"\bai\b|\ba\.i\.\b", normalized):
        return True
    return any(term in normalized for term in MOVIE_AI_TERMS)


# Performs the supporting reject reason helper step.

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
        open_web_direct_course = item.get("open_web_discovery") and course_url_is_direct(
            url,
            title=title,
            content=text,
        )
        if not domain_matches(domain, TRUSTED_COURSE_DOMAINS) and not open_web_direct_course:
            return "untrusted_course_domain"
        # Level-balanced newsletter change: Advanced courses are now part of
        # the saved course bank, so do not reject them solely because the level
        # or wording is advanced. Other quality/date/domain checks still apply.
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


# Prepares filter supporting candidates so downstream stages receive consistent data.

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


# Saves save memory to the configured output or state store.

def save_supporting_memory(items: list[dict], content_type: str) -> int:
    return save_memory(items or [], content_type, {})

__all__ = [
    "filter_supporting_candidates",
    "movie_has_direct_ai_signal",
    "save_supporting_memory",
    "support_text",
    "supporting_identity_keys",
    "supporting_matches_visible",
    "supporting_reject_reason",
    "supporting_visible_key_sets",
]
