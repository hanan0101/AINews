"""News candidate fetching entry points.

This module is the stable public fetching surface for news. The full
implementation lives in ``news_discovery.py`` (Exa, SearXNG, tool-discovery,
and tracker integrations).
"""

from backend.pipeline.fetching.news_discovery import (
    fetch_news_candidates as _fetch_news_candidates,
    normalize_candidate,
)


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
