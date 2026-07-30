import re
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


class FrontendAssetTests(unittest.TestCase):
    def test_card_ai_toolbar_matches_the_beige_hint_surface(self):
        css = (FRONTEND / "news.css").read_text(encoding="utf-8")
        match = re.search(r"(?m)^\s*\.card-popover\{([^}]+)\}", css)
        self.assertIsNotNone(match)
        popover_rule = match.group(1)
        self.assertIn("background:var(--chrome-bg)", popover_rule)
        self.assertIn("box-shadow:0 7px 18px rgba(91,61,38,.14)", popover_rule)
        self.assertIn(".card-popover button::after", css)
        self.assertIn("content:attr(aria-label)", css)
        rendering = (FRONTEND / "newsletter-rendering.js").read_text(encoding="utf-8")
        self.assertNotIn('title="${escapeHtml(t(\'cardBack\'))}"', rendering)
        self.assertNotIn('title="${escapeHtml(t(\'cardForward\'))}"', rendering)

    def test_duplicate_version_names_show_a_clear_error(self):
        core = (FRONTEND / "newsletter-core.js").read_text(encoding="utf-8")
        versions = (FRONTEND / "versions.html").read_text(encoding="utf-8")
        self.assertIn("duplicate_version_title", core)
        self.assertIn("duplicate_version_title", versions)
        self.assertIn("يوجد ملف محفوظ بنفس الاسم", versions)

    def test_news_page_is_composed_from_external_assets(self):
        html = (FRONTEND / "News.html").read_text(encoding="utf-8")
        self.assertNotIn("<style>", html)
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)[^>]*>")
        self.assertLess(len(html.splitlines()), 400)

        references = re.findall(r'(?:src|href)="([^"]+)"', html)
        local_assets = [
            reference
            for reference in references
            if not reference.startswith(("http://", "https://", "/", "#"))
        ]
        missing = [asset for asset in local_assets if not (FRONTEND / asset).is_file()]
        self.assertEqual(missing, [])

    def test_frontend_uses_renamed_shared_functions_file(self):
        for page_name in ("News.html", "versions.html"):
            html = (FRONTEND / page_name).read_text(encoding="utf-8")
            self.assertIn("shared-functions.js", html)
            self.assertNotIn('src="shared.js"', html)

    def test_removed_email_and_scheduling_features_are_not_exposed(self):
        frontend_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in FRONTEND.glob("*")
            if path.suffix.lower() in {".html", ".js", ".css"}
        )
        for removed_token in (
            "/api/send-newsletter",
            "recipient_email",
            "NEWSLETTER_PUBLICATION_LEAD_DAYS",
        ):
            self.assertNotIn(removed_token, frontend_text)


if __name__ == "__main__":
    unittest.main()
