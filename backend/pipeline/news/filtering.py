"""Filter and deduplicate news candidates for the news pipeline."""

from backend.pipeline.filtering.news import filter_news_candidates, items_same_story

__all__ = ["filter_news_candidates", "items_same_story"]


