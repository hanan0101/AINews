"""News candidate fetching entry points.

This module is the public fetching surface for news. Source-specific
implementations live beside it in this package.
"""

from backend.pipeline.fetching.content.news.normalization import normalize_candidate
from backend.pipeline.fetching.content.news.runtime import fetch_news_candidates as _fetch_news_candidates


def fetch_news_candidates(
    *,
    exclude_items: list[dict] | None = None,
    target_hint: str = "",
    single: bool = False,
    cycle: int = 1,
) -> tuple[list[dict], dict]:
    """Fetch live AI-news candidates from the configured source mix."""
    return _fetch_news_candidates(exclude_items=exclude_items, target_hint=target_hint, single=single, cycle=cycle)


__all__ = ["fetch_news_candidates", "normalize_candidate"]
