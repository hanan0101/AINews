"""Canonical, evidence-based course level classification."""

from __future__ import annotations

import re

from backend.config.settings import normalized_text


def classify_course_level_evidence(title: str = "", content: str = "", url: str = "") -> dict:
    """Classify a course from official evidence and retain confidence/source."""
    del url  # URL tokens are deliberately not level evidence.
    title_text = normalized_text(title)
    body = normalized_text(content)
    evidence = f"{title_text} {body}".strip()

    explicit_patterns = (
        ("Advanced", r"\b(?:level|difficulty)\s*[:\-]?\s*(?:advanced|expert)\b"),
        ("Intermediate", r"\b(?:level|difficulty)\s*[:\-]?\s*intermediate\b"),
        ("Beginner", r"\b(?:level|difficulty)\s*[:\-]?\s*(?:beginner|introductory)\b"),
    )
    for level, pattern in explicit_patterns:
        match = re.search(pattern, evidence)
        if match:
            return {
                "level": level,
                "level_confidence": "high",
                "level_source": "official_stated_level",
                "level_evidence": match.group(0),
            }

    no_prerequisite_terms = (
        "no prerequisites", "no prior experience", "no experience required",
        "no coding required", "no technical background", "beginners welcome",
    )
    prerequisite_context = " ".join(
        match.group(0)
        for match in re.finditer(
            r"(?:prerequisites?|requirements?|before (?:taking|starting)|you should know).{0,220}",
            evidence,
        )
    )
    if any(term in evidence for term in no_prerequisite_terms):
        return {
            "level": "Beginner",
            "level_confidence": "high",
            "level_source": "official_prerequisites",
            "level_evidence": "no prior experience or technical prerequisite",
        }

    technical_prerequisite_text = prerequisite_context or evidence
    has_python = "python" in technical_prerequisite_text
    has_ml = any(
        term in technical_prerequisite_text
        for term in ("machine learning", "deep learning", "ml knowledge", "statistics", "linear algebra")
    )
    has_cloud = any(
        term in technical_prerequisite_text
        for term in ("cloud", "aws", "azure", "google cloud")
    )
    requires_signal = any(
        term in technical_prerequisite_text
        for term in ("prerequisite", "required", "should know", "prior experience", "familiarity")
    )
    if requires_signal and has_python and (has_ml or has_cloud):
        return {
            "level": "Advanced",
            "level_confidence": "high",
            "level_source": "official_prerequisites",
            "level_evidence": "Python plus ML/cloud prerequisites",
        }
    if requires_signal and (has_python or has_ml or has_cloud or "api" in technical_prerequisite_text):
        return {
            "level": "Intermediate",
            "level_confidence": "high",
            "level_source": "official_prerequisites",
            "level_evidence": "prior technical familiarity required",
        }

    advanced_modules = (
        "fine tuning", "fine-tuning", "production deployment", "model deployment",
        "mlops", "advanced evaluation", "system architecture", "cloud architecture",
        "ai governance", "deep learning", "complex agents", "multi agent",
    )
    if any(term in evidence for term in advanced_modules):
        return {
            "level": "Advanced",
            "level_confidence": "medium",
            "level_source": "official_modules",
            "level_evidence": "advanced technical modules",
        }
    intermediate_modules = (
        "multi step project", "multi-step project", "hands on project", "hands-on project",
        "api", "data pipeline", "basic coding", "integrated workflow", "automation workflow",
    )
    if any(term in evidence for term in intermediate_modules):
        return {
            "level": "Intermediate",
            "level_confidence": "medium",
            "level_source": "official_modules",
            "level_evidence": "project/API/workflow modules",
        }

    beginner_title_terms = (
        "beginner", "fundamentals", "foundations", "basics", "getting started",
        "for everyone", "introduction", "introductory",
    )
    if any(term in title_text for term in beginner_title_terms):
        return {
            "level": "Beginner",
            "level_confidence": "medium",
            "level_source": "official_title",
            "level_evidence": "introductory title with no conflicting prerequisite evidence",
        }
    return {
        "level": "",
        "level_confidence": "low",
        "level_source": "unverified",
        "level_evidence": "insufficient official level evidence",
    }
