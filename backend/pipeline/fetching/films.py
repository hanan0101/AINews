# This file is part of the AI newsletter system.
"""AI-themed film fetching from TMDb."""

from __future__ import annotations

from backend.pipeline.fetching.news_discovery import *  # Generic low-level fetch/text helpers (not news logic).

TMDB_AI_KEYWORD_IDS = (310,)


# Performs the rotated movie pages helper step.
def rotated_movie_pages(page_count: int) -> tuple[list[int], dict]:
    """Return TMDb pages for this run and persist the next start page."""
    page_count = max(1, int(page_count or 1))
    max_page = max(page_count, env_int("AI_UPDATES_MOVIE_ROTATION_MAX_PAGE", "6"))
    state = load_json(NEWS_FETCH_STATE_FILE, {})
    rotation = state.get("movie_page_rotation") if isinstance(state.get("movie_page_rotation"), dict) else {}
    start_page = int(rotation.get("next_page") or 1)
    if start_page < 1 or start_page > max_page:
        start_page = 1
    pages = [((start_page - 1 + offset) % max_page) + 1 for offset in range(page_count)]
    next_page = ((start_page - 1 + page_count) % max_page) + 1
    state["movie_page_rotation"] = {
        "updated_at": utc_now().isoformat(),
        "max_page": max_page,
        "page_count": page_count,
        "start_page": start_page,
        "next_page": next_page,
        "selected_pages": pages,
    }
    safe_write_json(NEWS_FETCH_STATE_FILE, state)
    return pages, state["movie_page_rotation"]


# Fetches fetch movie candidates from the configured external source.
def fetch_movie_candidates(target_count: int = 8) -> list[dict]:
    """Fetch AI-themed movie candidates with posters directly from TMDb."""
    if not TMDB_API_KEY:
        safe_print("[AI Updates] TMDb movie skipped: missing TMDB_API_KEY")
        return []
    output = []
    seen = set()
    page_count = max(1, min(3, (target_count // 20) + 1))
    pages, rotation = rotated_movie_pages(page_count)
    log_event(
        "movies.page_rotation",
        target_count=target_count,
        page_count=page_count,
        max_page=rotation.get("max_page"),
        start_page=rotation.get("start_page"),
        next_page=rotation.get("next_page"),
        selected_pages=pages,
    )
    for keyword_id in TMDB_AI_KEYWORD_IDS:
        for page in pages:
            if len(output) >= target_count:
                break
            try:
                response = requests.get(
                    "https://api.themoviedb.org/3/discover/movie",
                    params={
                        "api_key": TMDB_API_KEY,
                        "with_keywords": keyword_id,
                        "sort_by": "popularity.desc",
                        "include_adult": "false",
                        "page": page,
                    },
                    timeout=12,
                )
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                safe_print(f"[AI Updates] TMDb movie failed: {exc}")
                continue
            for result in data.get("results") or []:
                movie_id = result.get("id")
                if not movie_id or movie_id in seen:
                    continue
                seen.add(movie_id)
                poster_path = result.get("poster_path") or ""
                poster = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
                url = f"https://www.themoviedb.org/movie/{movie_id}"
                overview = clean_text(result.get("overview") or "")
                output.append({
                    "id": f"movie-{movie_id}",
                    "title": clean_text(result.get("title") or result.get("original_title") or ""),
                    "text": overview,
                    "summary": overview,
                    "content": overview,
                    "overview": overview,
                    "url": url,
                    "source_url": url,
                    "source": "TMDb",
                    "poster": poster,
                    "rating": result.get("vote_average"),
                    "vote_count": result.get("vote_count"),
                    "popularity": result.get("popularity"),
                    "published": result.get("release_date") or "",
                    "date": result.get("release_date") or "",
                    "type": "movie",
                    "fetch_source": "tmdb_movie_search",
                    "discovery_source": "tmdb_movie_search",
                    "position": len(output) + 1,
                })
                if len(output) >= target_count:
                    break
    safe_print(f"[AI Updates] TMDb movie collected {len(output)}")
    return output[:target_count]

__all__ = ["TMDB_AI_KEYWORD_IDS", "rotated_movie_pages", "fetch_movie_candidates"]
