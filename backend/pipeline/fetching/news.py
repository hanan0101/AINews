"""News candidate fetching entry points.

This module is the public fetching surface for news. The lower-level news
collector lives in ``sources.py`` because it owns the shared Exa, SearXNG,
tool-discovery, and tracker integrations used by news discovery.
"""

from backend.pipeline.fetching.sources import (
    fetch_news_candidates as _fetch_news_candidates,
    normalize_candidate,
)


def fetch_news_candidates(
    *,
    exclude_items: list[dict] | None = None,
    target_hint: str = "",
    single: bool = False,
) -> tuple[list[dict], dict]:
    """Fetch live AI-news candidates from the configured source mix."""
    return _fetch_news_candidates(exclude_items=exclude_items, target_hint=target_hint, single=single)


__all__ = ["fetch_news_candidates", "normalize_candidate"]
