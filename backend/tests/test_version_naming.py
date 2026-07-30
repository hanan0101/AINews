import json
import unittest
from datetime import date
from unittest.mock import patch

from backend.storage.manage_versions.versions_db import (
    legacy_unique_title_updates,
    normalize_version_title,
    requested_version_title_from_news,
    version_title_exists,
    version_title_from_news,
)
from backend.storage.newsletter_store import current_arabic_month_year


class VersionNamingTests(unittest.TestCase):
    def test_duplicate_lookup_excludes_the_current_version(self):
        class FakeCursor:
            def __init__(self):
                self.query = ""
                self.values = ()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, values):
                self.query = query
                self.values = values

            def fetchone(self):
                return (1,)

        class FakeConnection:
            def __init__(self):
                self.last_cursor = None

            def cursor(self):
                self.last_cursor = FakeCursor()
                return self.last_cursor

        connection = FakeConnection()
        self.assertTrue(
            version_title_exists(
                connection,
                "  August   Newsletter ",
                exclude_id=7,
            )
        )
        self.assertIn("LOWER(BTRIM(title))", connection.last_cursor.query)
        self.assertIn("id <> %s", connection.last_cursor.query)
        self.assertEqual(connection.last_cursor.values, ("August Newsletter", 7))

    def test_title_whitespace_is_normalized(self):
        self.assertEqual(
            normalize_version_title("  نشرة   الذكاء الاصطناعي  "),
            "نشرة الذكاء الاصطناعي",
        )

    def test_legacy_duplicates_receive_deterministic_suffixes(self):
        self.assertEqual(
            legacy_unique_title_updates(
                [
                    (1, "August Newsletter"),
                    (2, "august newsletter"),
                    (3, "August Newsletter"),
                ]
            ),
            [
                ("august newsletter (2)", 2),
                ("August Newsletter (3)", 3),
            ],
        )

    def test_month_year_uses_the_supplied_month_without_lead_date_shift(self):
        label = current_arabic_month_year(date(2026, 7, 31))
        self.assertEqual(label, "يوليو 2026")

    def test_explicit_metadata_title_is_preserved(self):
        content = json.dumps(
            {"metadata": {"requested_version_title": "نسخة مراجعة الإدارة"}},
            ensure_ascii=False,
        )
        self.assertEqual(
            requested_version_title_from_news(content),
            "نسخة مراجعة الإدارة",
        )

    @patch(
        "backend.storage.manage_versions.versions_db.load_newsletter_settings",
        return_value={"issue_number": 8, "month_year_override": "أغسطس 2026"},
    )
    def test_fallback_title_uses_issue_and_current_month_metadata(self, _settings):
        issue, title = version_title_from_news("{}")
        self.assertEqual(issue, 8)
        self.assertIn("8", title)
        self.assertIn("أغسطس 2026", title)


if __name__ == "__main__":
    unittest.main()
