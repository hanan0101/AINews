import unittest
from unittest.mock import patch

from backend.pipeline.orchestrator import run_single_supporting_pipeline


class MovieLevelIndependenceTests(unittest.TestCase):
    def test_movie_refill_ignores_requested_level_and_removes_level_fields(self) -> None:
        movie = {
            "id": "movie-1",
            "title": "AI Film",
            "text": "Film description",
            "url": "https://movies.test/ai-film",
            "poster": "https://images.test/poster.jpg",
            "type": "movie",
            "level": "Advanced",
            "difficulty": "advanced",
        }
        with (
            patch("backend.pipeline.orchestrator.fetch_movie_candidates", return_value=[movie]),
            patch("backend.pipeline.orchestrator.filter_supporting_candidates", return_value=[movie]),
            patch("backend.pipeline.orchestrator.select_supporting_content_cards", return_value=[dict(movie)]),
        ):
            report = run_single_supporting_pipeline("movie", requested_level="beginner")

        self.assertEqual(report["performance"]["requested_level"], "")
        self.assertNotIn("level", report["cards"][0])
        self.assertNotIn("difficulty", report["cards"][0])


if __name__ == "__main__":
    unittest.main()
