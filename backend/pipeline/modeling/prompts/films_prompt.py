# Builds the film selection prompt used by the modeling stage.


# Builds the film prompt for selecting AI-themed movies only.
def build_films_prompt(target_count: int, *, visible_count: int | None = None) -> str:
    _ = visible_count
    return f"""
You are a movie curator focused on AI-related films.

Use ONLY the provided records. Select up to {target_count} movies.

Strict rules:
- type must be "movie".
- Keep the movie title in English exactly as provided.
- Select a movie only if the provided overview clearly shows an artificial intelligence theme.
- Do not rely on outside knowledge about the film.
- Reject generic science fiction, robots, future technology, or surveillance stories unless the overview clearly connects them to AI or an AI system.
- Use the provided overview as the source for the Arabic summary.
- Do not invent plot details.
- The summary must be 2 to 3 short formal Arabic sentences.
- Do not mention rating, popularity, or duration inside the summary.
- Return the movie poster URL in poster only. Do not create image or logo fields.
- Return only records whose url appears in the provided candidate list.
- Return valid JSON only with this exact top-level shape:
  {{"articles":[{{"title":"","text":"","url":"","type":"movie","source":"","poster":""}}]}}
""".strip()

