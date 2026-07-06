# This file is part of the AI newsletter system.
"""Level-based newsletter bank building and display filtering helpers.

The pipeline still fetches, filters, and rewrites content the same way. This
module only adds the new layer requested for the newsletter: prepare a complete
balanced bank first, then choose the visible view from that bank.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


LEVELS = ("beginner", "intermediate", "advanced")
NEWS_PER_LEVEL = 4
COURSES_PER_LEVEL = 2
DEFAULT_NEWS_VIEW = {"beginner": 2, "intermediate": 1, "advanced": 1}
DEFAULT_COURSE_VIEW = {"beginner": 2, "intermediate": 2, "advanced": 2}


# Prepares normalize level so downstream stages receive consistent data.
def normalize_level(value: str = "") -> str:
    """Normalize any user/model/platform level spelling to the three UI levels."""
    text = str(value or "").strip().lower()
    if text in {"beginner", "basic", "intro", "introductory", "foundation", "foundational"}:
        return "beginner"
    if text in {"intermediate", "mid", "practical", "applied"}:
        return "intermediate"
    if text in {"advanced", "expert", "professional", "technical"}:
        return "advanced"
    return ""


# Performs the display level helper step.
def display_level(value: str = "") -> str:
    """Return the display label stored on cards for the frontend and JSON."""
    normalized = normalize_level(value)
    return {"beginner": "Beginner", "intermediate": "Intermediate", "advanced": "Advanced"}.get(normalized, "")


# Performs the text blob helper step.
def _text_blob(item: dict, keys: Iterable[str]) -> str:
    return " ".join(str(item.get(key) or "") for key in keys).lower()


# Performs the infer topic group helper step.
def infer_topic_group(item: dict) -> str:
    """Assign a topic group so each level avoids repeating the same use case."""
    text = _text_blob(item, ("title", "text", "whats_new", "url", "tool_name", "sector", "topic_group"))
    topic_terms = [
        ("translation", ("translate", "translation", "language")),
        ("personal_assistant", ("assistant", "chat", "siri", "voice assistant")),
        ("content_creation", ("content", "writing", "copy", "blog", "avatar", "video")),
        ("design", ("design", "figma", "canva", "image", "visual")),
        ("research", ("research", "search", "citations", "sources")),
        ("work_productivity", ("productivity", "meeting", "office", "copilot", "workflow")),
        ("automation_agents", ("agent", "automation", "automate", "browser", "files")),
        ("education_training", ("course", "learning", "education", "training")),
        ("security", ("security", "safety", "privacy", "guardrail")),
        ("developer_tools", ("api", "plugin", "code", "developer", "sdk")),
        ("creative_tools", ("music", "film", "creative", "story", "art")),
        ("data_analysis", ("data", "analysis", "analytics", "spreadsheet")),
        ("communication", ("email", "message", "communication", "call")),
    ]
    for topic, terms in topic_terms:
        if any(term in text for term in terms):
            return topic
    words = re.findall(r"[a-zA-Z]{4,}", text)
    return words[0].lower() if words else "general"


# Performs the classify news item helper step.
def classify_news_item(item: dict) -> dict:
    """Preserve model-provided news level and topic fields before banking."""
    result = dict(item or {})
    level = normalize_level(result.get("level") or result.get("news_level") or "")
    result["level"] = display_level(level)
    result["news_level"] = normalize_level(level)
    result["topic_group"] = result.get("topic_group") or infer_topic_group(result)
    result.setdefault("solution_provided", result.get("text") or result.get("title") or "")
    result.setdefault("main_user_benefit", result.get("text") or "")
    result.setdefault("level_source", "model" if level else "missing")
    return result


# Performs the classify course item helper step.
def classify_course_item(item: dict) -> dict:
    """Preserve platform/model course level without inferring from text."""
    result = dict(item or {})
    platform_level = normalize_level(result.get("level") or "")
    if platform_level:
        result["level_source"] = result.get("level_source") or "platform"
        result["classification_reason"] = result.get("classification_reason") or "Used course platform level"
    else:
        result["level_source"] = result.get("level_source") or "missing"
        result["classification_reason"] = result.get("classification_reason") or "No usable course level provided"
    result["level"] = display_level(platform_level)
    result["course_level"] = normalize_level(platform_level)
    result["topic_group"] = result.get("topic_group") or infer_topic_group(result)
    return result


# Performs the item key helper step.
def _item_key(item: dict) -> str:
    return str(item.get("id") or item.get("url") or item.get("title") or id(item)).strip().lower()


# Performs the select topic diverse helper step.
def select_topic_diverse(items: list[dict], count: int, *, used_keys: set[str] | None = None) -> tuple[list[dict], list[str]]:
    """Select items while avoiding more than two of one topic when possible."""
    selected: list[dict] = []
    fallbacks: list[dict] = []
    topic_counts: Counter[str] = Counter()
    used_keys = used_keys if used_keys is not None else set()
    notes: list[str] = []
    for item in items or []:
        key = _item_key(item)
        if key in used_keys:
            continue
        topic = item.get("topic_group") or "general"
        if topic_counts[topic] >= 2:
            fallbacks.append(item)
            continue
        selected.append(item)
        used_keys.add(key)
        topic_counts[topic] += 1
        if len(selected) >= count:
            return selected, notes
    for item in fallbacks + list(items or []):
        if len(selected) >= count:
            break
        key = _item_key(item)
        if key in used_keys:
            continue
        selected.append(item)
        used_keys.add(key)
        notes.append("topic_diversity_fallback_used")
    return selected[:count], notes


# Builds build level bank for the next pipeline or API step.
def build_level_bank(items: list[dict], per_level: int, classifier) -> tuple[dict[str, list[dict]], list[dict], list[str]]:
    """Create a complete Beginner/Intermediate/Advanced bank with fallbacks."""
    classified = [classifier(item) for item in items or [] if isinstance(item, dict)]
    grouped = {level: [item for item in classified if normalize_level(item.get("level")) == level] for level in LEVELS}
    bank = {level: [] for level in LEVELS}
    used_keys: set[str] = set()
    notes: list[str] = []

    for level in LEVELS:
        picked, level_notes = select_topic_diverse(grouped[level], per_level, used_keys=used_keys)
        bank[level].extend(picked)
        notes.extend(f"{level}:{note}" for note in level_notes)

    # Fallback rule: if one level is short, fill from the closest available
    # unused items but keep metadata so reviewers know the bank was imperfect.
    fallback_pool = classified
    for level in LEVELS:
        missing = per_level - len(bank[level])
        if missing <= 0:
            continue
        extra, _ = select_topic_diverse(fallback_pool, missing, used_keys=used_keys)
        for item in extra:
            copied = dict(item)
            copied["level_bank_fallback_for"] = level
            bank[level].append(copied)
        if extra:
            notes.append(f"{level}:filled_{len(extra)}_with_fallback_level")

    flat = [item for level in LEVELS for item in bank[level]]
    return bank, flat, notes


# Builds build recommended view for the next pipeline or API step.
def build_recommended_view(news_bank: dict[str, list[dict]], courses_bank: dict[str, list[dict]], movies: list[dict]) -> dict:
    """Build the default All-levels view: readable mixed content first."""
    news = []
    for level, count in DEFAULT_NEWS_VIEW.items():
        news.extend((news_bank.get(level) or [])[:count])
    courses = []
    for level, count in DEFAULT_COURSE_VIEW.items():
        courses.extend((courses_bank.get(level) or [])[:count])
    return {"news": news[:4], "courses": courses[:6], "movie": (movies or [{}])[0] if movies else {}}


# Builds build filter view for the next pipeline or API step.
def build_filter_view(news_bank: dict[str, list[dict]], courses_bank: dict[str, list[dict]], levels: list[str], movies: list[dict]) -> dict:
    """Return the visible view for one, two, or all selected levels."""
    chosen = [normalize_level(level) for level in levels or []]
    chosen = [level for level in LEVELS if level in set(chosen)]
    if not chosen or len(chosen) == 3:
        return build_recommended_view(news_bank, courses_bank, movies)
    if len(chosen) == 1:
        level = chosen[0]
        return {"news": (news_bank.get(level) or [])[:4], "courses": (courses_bank.get(level) or [])[:2], "movie": (movies or [{}])[0] if movies else {}}
    news = []
    courses = []
    for level in chosen[:2]:
        news.extend((news_bank.get(level) or [])[:2])
        courses.extend((courses_bank.get(level) or [])[:2])
    return {"news": news[:4], "courses": courses[:4], "movie": (movies or [{}])[0] if movies else {}}
