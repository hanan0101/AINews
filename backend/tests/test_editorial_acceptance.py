"""Acceptance tests for news freshness/diversity/writing and course levels."""

from __future__ import annotations

import unittest
from datetime import timedelta

from backend.config.settings import utc_now
from backend.pipeline.fetching.content.courses.bank import infer_level_from_evidence
from backend.pipeline.fetching.content.courses.discovery import classify_course_level_evidence
from backend.pipeline.modeling.content.news.selection import (
    apply_functional_diversity,
    arabic_summary_word_count,
    event_freshness_reject_reason,
    rewrite_claim_reject_reason,
    selected_item_quality_reject_reason,
)


def news_item(index: int, category: str, topic: str) -> dict:
    return {
        "official_url": f"https://example{index}.com/news/{index}",
        "title": f"خبر عملي جديد رقم {index}",
        "owner_key": f"owner-{index}",
        "functional_category": category,
        "topic_group": topic,
    }


class EditorialAcceptanceTests(unittest.TestCase):
    def test_recent_article_about_three_week_old_event_is_rejected(self):
        item = {
            "event_type": "available_launch",
            "event_date": (utc_now() - timedelta(days=21)).date().isoformat(),
            "event_date_basis": "official launch page",
        }
        self.assertEqual(
            event_freshness_reject_reason(item, {"published_date": utc_now().isoformat()}),
            "original_event_outside_lookback_window",
        )

    def test_real_update_inside_window_is_accepted(self):
        item = {
            "event_type": "product_update",
            "event_date": (utc_now() - timedelta(days=1)).date().isoformat(),
            "event_date_basis": "official release note dated yesterday",
        }
        self.assertEqual(event_freshness_reject_reason(item), "")

    def test_audio_video_is_capped_at_two_when_alternatives_exist(self):
        items = [news_item(i, "audio_video", f"media-{i}") for i in range(3)]
        alternatives = ("daily_use", "data_analytics", "security_privacy", "education_research")
        items += [news_item(i, category, f"alternative-{i}") for i, category in enumerate(alternatives, 3)]
        selected = apply_functional_diversity(items, 6, {})
        self.assertLessEqual(sum(row["functional_category"] == "audio_video" for row in selected), 2)

    def test_three_similar_agent_workflows_are_not_selected(self):
        items = [news_item(i, "office_productivity", "agent_workflow") for i in range(3)]
        alternatives = ("daily_use", "data_analytics", "security_privacy", "education_research")
        items += [news_item(i, category, f"alternative-{i}") for i, category in enumerate(alternatives, 3)]
        selected = apply_functional_diversity(items, 6, {})
        self.assertLessEqual(sum(row["topic_group"] == "agent_workflow" for row in selected), 2)

    def test_early_access_cannot_be_rewritten_as_available_to_all(self):
        item = {
            "availability_status": "limited_access",
            "title": "معاينة أداة جديدة",
            "whats_new": "أطلقت الشركة الأداة وهي متاحة للجميع الآن.",
        }
        self.assertEqual(rewrite_claim_reject_reason(item), "availability_claim_mismatch")

    def test_absolute_marketing_claim_is_rejected(self):
        item = {
            "availability_status": "available_now",
            "title": "تحديث منصة العمل",
            "whats_new": "تقول البطاقة إن المنتج هو الأفضل في السوق ويضمن الأمان.",
        }
        self.assertEqual(rewrite_claim_reject_reason(item), "absolute_marketing_claim")

    def test_introduction_with_no_prerequisites_is_beginner(self):
        result = classify_course_level_evidence(
            "Introduction to Generative AI",
            "No prerequisites or prior experience required.",
        )
        self.assertEqual(result["level"], "Beginner")
        self.assertEqual(result["level_confidence"], "high")

    def test_introduction_with_python_and_ml_prerequisites_is_not_beginner(self):
        result = classify_course_level_evidence(
            "Introduction to AI Systems",
            "Prerequisites: Python and machine learning knowledge plus cloud experience.",
        )
        self.assertIn(result["level"], {"Intermediate", "Advanced"})
        self.assertNotEqual(result["level"], "Beginner")

    def test_missing_level_evidence_stays_unverified(self):
        result = classify_course_level_evidence(
            "AI at Work",
            "Explore useful ideas for modern organizations.",
        )
        self.assertEqual(result["level"], "")
        self.assertEqual(result["level_confidence"], "low")
        self.assertEqual(result["level_source"], "unverified")

    def test_course_bank_uses_same_prerequisite_rules(self):
        level = infer_level_from_evidence(
            "",
            "Introduction to AI. Prerequisites: Python, machine learning, and cloud experience.",
        )
        self.assertEqual(level, "advanced")

    def test_course_bank_does_not_default_unknown_level_to_intermediate(self):
        self.assertEqual(infer_level_from_evidence("", "AI skills for modern work."), "")

    def test_news_summary_must_contain_50_to_64_words(self):
        valid_summary = " ".join(["ميزة"] * 50)
        invalid_summary = " ".join(["ميزة"] * 49)
        base = {"title": "تحديث عملي واضح للمستخدم", "level": "beginner"}
        self.assertEqual(arabic_summary_word_count(valid_summary), 50)
        self.assertEqual(selected_item_quality_reject_reason({**base, "whats_new": valid_summary}, {}), "")
        self.assertEqual(
            selected_item_quality_reject_reason({**base, "whats_new": invalid_summary}, {}),
            "summary_word_count_out_of_range",
        )


if __name__ == "__main__":
    unittest.main()
