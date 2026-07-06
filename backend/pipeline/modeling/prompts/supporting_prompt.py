# Routes supporting-content prompt requests to the course or film prompt file.

from backend.pipeline.modeling.prompts.courses_prompt import build_courses_prompt
from backend.pipeline.modeling.prompts.films_prompt import build_films_prompt


# Builds the correct supporting-content prompt for the requested content type.
def build_supporting_prompt(content_type: str, target_count: int, *, visible_count: int | None = None) -> str:
    if content_type == "course":
        return build_courses_prompt(target_count, visible_count=visible_count)
    if content_type == "movie":
        return build_films_prompt(target_count, visible_count=visible_count)
    return f"""
Use ONLY the provided records. Select up to {target_count} valid items.
Write concise factual Arabic summaries and do not invent missing information.
""".strip()

