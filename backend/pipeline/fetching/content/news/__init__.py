"""News fetching implementation modules."""

from .runtime import fetch_news_candidates
from .normalization import normalize_candidate

__all__ = ["fetch_news_candidates", "normalize_candidate"]
