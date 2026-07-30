import unittest

from backend.utils.pdf_export_service import extract_ui_styles


class PdfStyleLoadingTests(unittest.TestCase):
    def test_news_pdf_reads_linked_stylesheets(self):
        css = extract_ui_styles("News.html")
        self.assertIn("--bg", css)
        self.assertIn(".page{", css)
        self.assertNotIn("@media print", css)


if __name__ == "__main__":
    unittest.main()
