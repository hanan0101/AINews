# This file is part of the AI newsletter system.
import unittest

from backend.pipeline.fetching.courses import normalize_course_candidate


class CourseCandidateNormalizationTests(unittest.TestCase):
    # Performs the test accepts unknown domain when url and text look like a certificate course helper step.
    def test_accepts_unknown_domain_when_url_and_text_look_like_a_certificate_course(self) -> None:
        item = normalize_course_candidate(
            {
                "title": "AI for Everyone Certificate",
                "url": "https://academy.example.org/courses/ai-for-everyone",
                "content": "A practical course with a certificate and hands-on projects.",
                "published_date": "2026-06-20",
            },
            fetch_source="exa_course_search",
            query="AI course certificate",
        )

        self.assertIsNotNone(item)
        self.assertEqual(item["type"], "course")
        self.assertEqual(item["source"], "Academy Example Org")
        self.assertIn("certificate", item["certificate"].lower())


if __name__ == "__main__":
    unittest.main()
