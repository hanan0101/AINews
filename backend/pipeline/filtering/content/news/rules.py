"""News filtering and deduplication entry points."""

from backend.pipeline.filtering.shared.memory import (
    filter_news_candidates as _filter_news_candidates,
    item_story_key,
    items_same_story,
    save_news_memory,
    story_owner_key,
)


def filter_news_candidates(candidates: list[dict], diagnostics: dict, *, single: bool = False) -> list[dict]:
    """Filter, deduplicate, and memory-check live news candidates."""
    return _filter_news_candidates(candidates, diagnostics, single=single)


__all__ = [
    "filter_news_candidates",
    "item_story_key",
    "items_same_story",
    "save_news_memory",
    "story_owner_key",
]
