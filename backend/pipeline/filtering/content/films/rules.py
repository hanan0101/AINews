"""Film filtering entry points."""

from backend.pipeline.filtering.shared.supporting import (
    filter_supporting_candidates,
    save_supporting_memory,
    supporting_reject_reason,
)


def filter_movie_candidates(
    candidates: list[dict],
    limit: int,
    *,
    visible_items: list[dict] | None = None,
) -> list[dict]:
    """Filter film candidates for AI relevance, quality, duplicates, and memory."""
    return filter_supporting_candidates(candidates, "movie", limit, visible_items=visible_items)


__all__ = [
    "filter_movie_candidates",
    "filter_supporting_candidates",
    "save_supporting_memory",
    "supporting_reject_reason",
]
