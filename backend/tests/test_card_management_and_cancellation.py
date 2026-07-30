import unittest
from pathlib import Path

from backend.pipeline.orchestrator import run_single_update_pipeline
from backend.server.card_items import normalize_item
from backend.server.generator_bridge import (
    GENERATOR_CANCEL_EVENT,
    GENERATOR_STATE,
    cancel_generator,
)
from backend.server.http_server import remove_item_from_store
from backend.server.single_card_refill import (
    SINGLE_REFILL_CANCEL_EVENT,
    SINGLE_REFILL_STATE,
    cancel_single_refill,
)


class CardManagementAndCancellationTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    def tearDown(self):
        GENERATOR_CANCEL_EVENT.clear()
        SINGLE_REFILL_CANCEL_EVENT.clear()
        GENERATOR_STATE["running"] = False
        GENERATOR_STATE["cancel_requested"] = False
        SINGLE_REFILL_STATE["running"] = False
        SINGLE_REFILL_STATE["cancel_requested"] = False

    def test_news_level_survives_normalization(self):
        item = normalize_item(
            {"id": "n1", "type": "news", "title": "Update", "text": "Details", "url": "https://example.com", "level": "Advanced"},
            "news",
        )
        self.assertEqual(item["level"], "Advanced")

    def test_delete_removes_card_from_all_renderable_views(self):
        card = {"id": "n1", "title": "Update"}
        store = {
            "items": [card, {"id": "n2"}],
            "courses": [],
            "movies": [],
            "news_bank": {"beginner": [dict(card)], "advanced": []},
            "recommended_view": {"news": [dict(card)]},
            "saved_views": {"course": {"all": {"items": [dict(card)], "feature_item": None}}},
        }
        self.assertTrue(remove_item_from_store(store, "items", "n1"))
        self.assertEqual([item["id"] for item in store["items"]], ["n2"])
        self.assertEqual(store["news_bank"]["beginner"], [])
        self.assertEqual(store["recommended_view"]["news"], [])
        self.assertEqual(store["saved_views"]["course"]["all"]["items"], [])

    def test_full_and_single_cancel_flags_are_exposed(self):
        GENERATOR_STATE["running"] = True
        SINGLE_REFILL_STATE["running"] = True
        self.assertTrue(cancel_generator()["cancel_requested"])
        self.assertTrue(cancel_single_refill()["cancel_requested"])
        self.assertTrue(GENERATOR_CANCEL_EVENT.is_set())
        self.assertTrue(SINGLE_REFILL_CANCEL_EVENT.is_set())

    def test_single_pipeline_stops_before_fetch_when_cancelled(self):
        report = run_single_update_pipeline(cancel_check=lambda: True)
        self.assertTrue(report["cancelled"])
        self.assertEqual(report["error"], "cancelled")

    def test_frontend_exposes_delete_level_and_cancel_controls(self):
        news_html = (self.ROOT / "frontend" / "News.html").read_text(encoding="utf-8")
        rendering = (self.ROOT / "frontend" / "newsletter-rendering.js").read_text(encoding="utf-8")
        actions = (self.ROOT / "frontend" / "newsletter-card-actions.js").read_text(encoding="utf-8")
        generation = (self.ROOT / "frontend" / "newsletter-generation.js").read_text(encoding="utf-8")
        versions = (self.ROOT / "frontend" / "versions.html").read_text(encoding="utf-8")
        self.assertIn('id="cancelGenerationBtn"', news_html)
        self.assertIn('data-card-action="delete"', rendering)
        self.assertIn("section === 'courses' || section === 'items'", actions)
        self.assertIn("/generation/cancel", actions)
        self.assertIn("/generation/cancel", generation)
        self.assertIn('id="versionDeleteOverlay"', versions)
        self.assertIn("await confirmVersionDelete()", versions)

    def test_viewer_no_longer_uses_delayed_reveal(self):
        generation = (self.ROOT / "frontend" / "newsletter-generation.js").read_text(encoding="utf-8")
        viewer_branch = generation.split("if(!state.isAdmin){", 1)[1].split("if(shouldRevealRestoredVersion())", 1)[0]
        self.assertIn("revealNewsletterImmediately();", viewer_branch)
        self.assertNotIn("revealNewsletterForUser", viewer_branch)


if __name__ == "__main__":
    unittest.main()
