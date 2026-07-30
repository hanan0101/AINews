"""News model-selection entry points."""

from backend.pipeline.modeling.content.news.selection import (
    save_model_report,
    select_news_updates as _select_news_updates,
)


def select_news_updates(candidates: list[dict], diagnostics: dict, *, single: bool = False) -> dict:
    """Ask the editorial model to select and rewrite news cards."""
    return _select_news_updates(candidates, diagnostics, single=single)


__all__ = ["save_model_report", "select_news_updates"]
