import unittest
from contextlib import nullcontext
from unittest.mock import patch

from backend.pipeline import orchestrator


class SingleNewsExpansionTests(unittest.TestCase):
    def test_single_pipeline_uses_full_fetch_cycle_after_small_pool_fails(self):
        initial = [{"url": "https://example.com/weak", "title": "Weak"}]
        expanded = [{"url": "https://example.com/good", "title": "Good"}]
        reports = [
            {
                "success": False,
                "error": "gpt_selected_no_updates",
                "latest_updates": [],
                "diagnostics": {},
            },
            {
                "success": True,
                "latest_updates": [
                    {
                        "official_url": expanded[0]["url"],
                        "title": "عنوان صالح",
                        "whats_new": "نص صالح.",
                    }
                ],
                "diagnostics": {},
            },
        ]

        with (
            patch.object(
                orchestrator,
                "fetch_news_candidates",
                side_effect=[
                    (initial, {"raw_results": 1, "unique_results": 1, "queries": 1}),
                    (expanded, {"raw_results": 1, "unique_results": 1, "queries": 1}),
                ],
            ) as fetch,
            patch.object(orchestrator, "filter_news_candidates", side_effect=lambda items, _diagnostics, single: items),
            patch.object(orchestrator, "build_large_scan_pool", side_effect=lambda items, _diagnostics: items),
            patch.object(orchestrator, "shortlist_scan_pool_for_gpt", side_effect=lambda items, _diagnostics: items),
            patch.object(orchestrator, "select_news_updates", side_effect=reports) as select,
            patch.object(orchestrator, "model_quota_remaining", return_value=10),
            patch.object(orchestrator, "news_items_from_updates", return_value=[{"id": "generated"}]),
            patch.object(orchestrator, "log_event"),
            patch.object(orchestrator, "timed_stage", side_effect=lambda *_args, **_kwargs: nullcontext()),
        ):
            report = orchestrator.run_single_update_pipeline()

        self.assertTrue(report["success"])
        self.assertEqual(report["item"], {"id": "generated"})
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(fetch.call_args_list[0].kwargs["single"])
        self.assertFalse(fetch.call_args_list[1].kwargs["single"])
        self.assertEqual(fetch.call_args_list[1].kwargs["cycle"], 2)
        self.assertEqual(select.call_count, 2)
        self.assertTrue(report["diagnostics"]["single_expansion"]["success"])


if __name__ == "__main__":
    unittest.main()
