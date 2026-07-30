import unittest
from unittest.mock import patch

from backend.pipeline.modeling.content.news import selection


class SingleNewsCandidateRotationTests(unittest.TestCase):
    def test_single_refill_rotates_after_rewrite_omits_first_candidate(self):
        candidates = [
            {"url": "https://example.com/first", "title": "First"},
            {"url": "https://example.com/second", "title": "Second"},
        ]
        selection_payloads = []

        def fake_generate(role, _prompt, payload):
            self.assertEqual(role, "selection")
            selection_payloads.append([item["url"] for item in payload])
            chosen = payload[0]
            return {
                "latest_updates": [
                    {
                        "official_url": chosen["url"],
                        "source_title": chosen["title"],
                    }
                ]
            }

        def fake_attach(items, source_by_url, _diagnostics):
            attached = []
            for item in items:
                source = source_by_url[selection.result_url_key(item["official_url"])]
                attached.append(
                    {
                        **item,
                        "rewrite_id": item["official_url"],
                        "source_item": source,
                    }
                )
            return attached

        def fake_rewrite(items, _diagnostics, _stage):
            if items[0]["official_url"].endswith("/first"):
                return []
            return [{**items[0], "title": "عنوان صالح", "whats_new": "نص صالح."}]

        with (
            patch.object(selection, "model_available", return_value=True),
            patch.object(selection, "model_quota_remaining", return_value=10),
            patch.object(selection, "compact_model_candidate", side_effect=lambda item: dict(item)),
            patch.object(selection, "generate_json_for_role", side_effect=fake_generate),
            patch.object(selection, "attach_source_items", side_effect=fake_attach),
            patch.object(selection, "rewrite_selected_items", side_effect=fake_rewrite),
            patch.object(selection, "finalize_selected_items", side_effect=lambda items, _diagnostics: items),
            patch.object(selection, "balance_for_diversity", side_effect=lambda items, limit, _diagnostics: items[:limit]),
            patch.object(selection, "log_token_usage"),
            patch.object(selection, "log_event"),
        ):
            report = selection.select_news_updates(candidates, {}, single=True)

        self.assertTrue(report["success"])
        self.assertEqual(
            report["latest_updates"][0]["official_url"],
            "https://example.com/second",
        )
        self.assertEqual(selection_payloads[0], ["https://example.com/first", "https://example.com/second"])
        self.assertEqual(selection_payloads[1], ["https://example.com/second"])
        self.assertEqual(report["diagnostics"]["gpt_rejected_candidate_count"], 1)

    def test_single_refill_stops_after_first_success(self):
        candidate = {"url": "https://example.com/only", "title": "Only"}

        with (
            patch.object(selection, "model_available", return_value=True),
            patch.object(selection, "compact_model_candidate", side_effect=lambda item: dict(item)),
            patch.object(
                selection,
                "generate_json_for_role",
                return_value={
                    "latest_updates": [
                        {
                            "official_url": candidate["url"],
                            "source_title": candidate["title"],
                        }
                    ]
                },
            ) as generate,
            patch.object(
                selection,
                "attach_source_items",
                return_value=[
                    {
                        "official_url": candidate["url"],
                        "rewrite_id": candidate["url"],
                        "source_item": candidate,
                    }
                ],
            ),
            patch.object(
                selection,
                "rewrite_selected_items",
                return_value=[
                    {
                        "official_url": candidate["url"],
                        "rewrite_id": candidate["url"],
                        "source_item": candidate,
                        "title": "عنوان صالح",
                        "whats_new": "نص صالح.",
                    }
                ],
            ),
            patch.object(selection, "finalize_selected_items", side_effect=lambda items, _diagnostics: items),
            patch.object(selection, "balance_for_diversity", side_effect=lambda items, limit, _diagnostics: items[:limit]),
            patch.object(selection, "log_token_usage"),
            patch.object(selection, "log_event"),
        ):
            report = selection.select_news_updates([candidate], {}, single=True)

        self.assertTrue(report["success"])
        self.assertEqual(len(report["latest_updates"]), 1)
        generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
