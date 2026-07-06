"""Film model-selection entry points."""

from backend.pipeline.modeling.supporting import select_supporting_content_cards


def select_movie_cards(
    candidates: list[dict],
    target_count: int,
    *,
    visible_count: int | None = None,
) -> list[dict]:
    """Ask the editorial model to select and rewrite film cards."""
    return select_supporting_content_cards(
        candidates,
        "movie",
        target_count,
        visible_count=visible_count,
        use_course_bank=False,
    )


__all__ = ["select_movie_cards", "select_supporting_content_cards"]
