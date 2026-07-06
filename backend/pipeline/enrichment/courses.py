"""Course enrichment and supporting-content persistence entry points."""

from backend.pipeline.enrichment.supporting import (
    apply_supporting_content,
    build_supporting_content,
    refresh_supporting_content,
)


def build_course_content(pre_run_payload: dict | None = None, run_id: str = "", mode: str = "") -> dict:
    """Build supporting content and return the course portion inside the shared payload."""
    return build_supporting_content(pre_run_payload, run_id, mode)


def refresh_course_content(pre_run_payload: dict | None = None) -> dict:
    """Refresh supporting content, including courses, for the saved newsletter."""
    return refresh_supporting_content(pre_run_payload)


__all__ = [
    "apply_supporting_content",
    "build_course_content",
    "build_supporting_content",
    "refresh_course_content",
    "refresh_supporting_content",
]
