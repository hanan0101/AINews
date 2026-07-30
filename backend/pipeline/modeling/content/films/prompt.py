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
- Write the summary as ONE flowing Arabic sentence (around 35-60 Arabic words), not a list of separate templated sentences.
- Chain the plot details as coordinated clauses joined by connectors like "حيث"، "بحيث"، "مع"، "كما"، "ليكتشف"، "مما" — do NOT break them into separate sentences. The summary must end with a single Arabic full stop "." — never end a clause on a comma with no closing sentence, and never place a period before the very last clause.
- Do not mention rating, popularity, or duration inside the summary.
- Return the movie poster URL in poster only. Do not create image or logo fields.
- Return only records whose url appears in the provided candidate list.
- Return valid JSON only with this exact top-level shape:
  {{"articles":[{{"title":"","text":"","url":"","type":"movie","source":"","poster":""}}]}}
""".strip()

