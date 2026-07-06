"""Course model-selection entry points."""

from backend.pipeline.modeling.supporting import (
    balance_course_levels,
    select_supporting_content_cards,
)


def select_course_cards(
    candidates: list[dict],
    target_count: int,
    *,
    visible_count: int | None = None,
    use_course_bank: bool = True,
) -> list[dict]:
    """Ask the editorial model to select and rewrite course cards."""
    return select_supporting_content_cards(
        candidates,
        "course",
        target_count,
        visible_count=visible_count,
        use_course_bank=use_course_bank,
    )


__all__ = ["balance_course_levels", "select_course_cards", "select_supporting_content_cards"]
