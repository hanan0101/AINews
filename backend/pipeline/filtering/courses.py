"""Course filtering entry points."""

from backend.pipeline.filtering.supporting import (
    filter_supporting_candidates,
    save_supporting_memory,
    supporting_reject_reason,
)
from backend.pipeline.filtering.level_balancing import normalize_level


def filter_course_candidates(
    candidates: list[dict],
    limit: int,
    *,
    visible_items: list[dict] | None = None,
) -> list[dict]:
    """Filter course candidates for quality, recency, duplicates, and memory."""
    return filter_supporting_candidates(candidates, "course", limit, visible_items=visible_items)


__all__ = [
    "filter_course_candidates",
    "filter_supporting_candidates",
    "normalize_level",
    "save_supporting_memory",
    "supporting_reject_reason",
]
