import unittest
from unittest.mock import patch

from backend.storage.newsletter_store import save_published_store_memory


class PublishedSemanticMemoryTests(unittest.TestCase):
    def test_indexes_visible_manual_cards_for_every_content_type(self) -> None:
        store = {
            "news_display_count": 4,
            "items": [{"title": f"Manual news {index}", "url": f"https://news.test/{index}"} for index in range(6)],
            "courses": [{"title": f"Manual course {index}", "url": f"https://courses.test/{index}"} for index in range(8)],
            "movies": [{"title": f"Manual movie {index}", "url": f"https://movies.test/{index}"} for index in range(3)],
        }

        with (
            patch("backend.pipeline.filtering.memory.save_news_memory", return_value=4) as save_news,
            patch("backend.pipeline.filtering.supporting.save_supporting_memory", side_effect=[6, 2]) as save_supporting,
        ):
            counts = save_published_store_memory(store)

        self.assertEqual(counts, {"news": 4, "course": 6, "movie": 2})
        self.assertEqual(len(save_news.call_args.args[0]), 4)
        self.assertEqual(len(save_supporting.call_args_list[0].args[0]), 6)
        self.assertEqual(save_supporting.call_args_list[0].args[1], "course")
        self.assertEqual(len(save_supporting.call_args_list[1].args[0]), 2)
        self.assertEqual(save_supporting.call_args_list[1].args[1], "movie")


if __name__ == "__main__":
    unittest.main()
