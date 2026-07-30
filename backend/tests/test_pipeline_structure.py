import ast
import importlib
import pathlib
import unittest

from backend.pipeline.fetching.content.news.common import (
    canonical_news_url,
    parse_candidate_datetime,
)


class PipelineStructureTests(unittest.TestCase):
    def test_removed_pipeline_facades_are_not_imported(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        forbidden = {
            f"backend.pipeline.{stage}.{name}"
            for stage, names in {
                "enrichment": ("courses", "films", "logos", "news", "supporting"),
                "fetching": ("course_bank", "courses", "films", "news", "news_discovery"),
                "filtering": (
                    "courses",
                    "editorial_rules",
                    "films",
                    "level_balancing",
                    "memory",
                    "news",
                    "supporting",
                ),
                "modeling": ("courses", "films", "news", "selection", "supporting"),
            }.items()
            for name in names
        }
        found = []
        for scan_root in (root / "backend", root / "scripts"):
            for path in scan_root.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        found.extend(
                            (str(path.relative_to(root)), alias.name)
                            for alias in node.names
                            if alias.name in forbidden
                        )
                    elif isinstance(node, ast.ImportFrom) and node.module in forbidden:
                        found.append((str(path.relative_to(root)), node.module))
        self.assertEqual(found, [])

    def test_each_stage_exposes_all_content_types(self):
        modules = (
            "backend.pipeline.fetching.content.news.fetch",
            "backend.pipeline.fetching.content.courses.discovery",
            "backend.pipeline.fetching.content.films.discovery",
            "backend.pipeline.filtering.content.news.rules",
            "backend.pipeline.filtering.content.courses.rules",
            "backend.pipeline.filtering.content.films.rules",
            "backend.pipeline.modeling.content.news.model",
            "backend.pipeline.modeling.content.courses.model",
            "backend.pipeline.modeling.content.films.model",
            "backend.pipeline.enrichment.content.news.pipeline",
            "backend.pipeline.enrichment.content.courses.pipeline",
            "backend.pipeline.enrichment.content.films.pipeline",
        )
        for module_name in modules:
            with self.subTest(module=module_name):
                self.assertIsNotNone(importlib.import_module(module_name))

    def test_content_entrypoints_expose_expected_operations(self):
        expected = {
            "backend.pipeline.fetching.content.news.fetch": "fetch_news_candidates",
            "backend.pipeline.fetching.content.courses.discovery": "fetch_course_candidates",
            "backend.pipeline.fetching.content.films.discovery": "fetch_movie_candidates",
            "backend.pipeline.filtering.content.news.rules": "filter_news_candidates",
            "backend.pipeline.filtering.content.courses.rules": "filter_course_candidates",
            "backend.pipeline.filtering.content.films.rules": "filter_movie_candidates",
            "backend.pipeline.modeling.content.news.model": "select_news_updates",
            "backend.pipeline.modeling.content.courses.model": "select_supporting_content_cards",
            "backend.pipeline.modeling.content.films.model": "select_supporting_content_cards",
        }
        for module_name, operation in expected.items():
            with self.subTest(module=module_name, operation=operation):
                module = importlib.import_module(module_name)
                self.assertTrue(callable(getattr(module, operation)))

    def test_shared_news_url_and_date_helpers_preserve_source_semantics(self):
        url = "HTTPS://www.Example.com/releases/item/?ref=feed"
        self.assertEqual(
            canonical_news_url(url),
            "https://example.com/releases/item",
        )
        self.assertEqual(
            canonical_news_url(url, keep_query=True),
            "https://example.com/releases/item?ref=feed",
        )
        parsed = parse_candidate_datetime("2026-07-30 09:00 +03:00")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)


if __name__ == "__main__":
    unittest.main()
