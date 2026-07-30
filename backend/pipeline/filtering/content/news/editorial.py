"""Editorial rules shared by discovery tests and the production pipeline."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse


ACCEPTED_SAUDI_AI_EDITORIAL_TYPES = {
    "official_ai_policy",
    "official_ai_platform",
    "official_ai_government_service",
    "official_ai_sector_adoption",
}

SAUDI_OFFICIAL_DOMAINS = {
    "spa.gov.sa",
    "sdaia.gov.sa",
    "ndmo.gov.sa",
    "mcit.gov.sa",
    "humain.ai",
    "my.gov.sa",
    "ai.gov.sa",
    "gov.sa",
    "mofa.gov.sa",
    "moh.gov.sa",
    "moe.gov.sa",
    "mt.gov.sa",
    "moc.gov.sa",
    "momrah.gov.sa",
    "mewa.gov.sa",
    "moenergy.gov.sa",
    "tourism.gov.sa",
}

SAUDI_TERMS = (
    "saudi",
    "saudi arabia",
    "riyadh",
    "kingdom",
    "vision 2030",
    "sdaia",
    "humain",
    "ndmo",
    "mcit",
    "kaust",
    "neom",
    "kacst",
    "سعود",
    "السعودية",
    "المملكة",
    "الرياض",
    "رؤية 2030",
    "سدايا",
    "هيومين",
    "نيوم",
    "كاوست",
    "وزارة",
    "هيئة",
)

AI_TERMS = (
    "ai",
    "artificial intelligence",
    "generative ai",
    "machine learning",
    "llm",
    "model",
    "الذكاء الاصطناعي",
    "ذكاء اصطناعي",
    "نموذج",
)

POLICY_TERMS = (
    "policy",
    "regulation",
    "governance",
    "framework",
    "public consultation",
    "consultation",
    "سياسة",
    "سياسات",
    "تنظيم",
    "لوائح",
    "لائحة",
    "حوكمة",
    "إطار تنظيمي",
    "أطر تنظيمية",
    "استطلاع مرئيات",
    "مرئيات",
    "الذكاء الاصطناعي أولا",
    "الذكاء الاصطناعي أولًا",
)

PLATFORM_TERMS = (
    "platform",
    "service",
    "engine",
    "launch",
    "launched",
    "unveils",
    "introduces",
    "منصة",
    "خدمة",
    "محرك",
    "أطلقت",
    "يطلق",
    "تطلق",
    "إطلاق",
)

GOVERNMENT_SERVICE_TERMS = (
    "government service",
    "public service",
    "municipal",
    "ministry",
    "authority",
    "خدمة حكومية",
    "الخدمات الحكومية",
    "الخدمات البلدية",
    "وزارة",
    "هيئة",
)

SECTOR_TERMS = (
    "tourism",
    "education",
    "health",
    "culture",
    "municipal",
    "water",
    "energy",
    "السياحة",
    "التعليم",
    "الصحة",
    "الثقافة",
    "البلدية",
    "البلديات",
    "المياه",
    "الطاقة",
)

PARTNERSHIP_TERMS = (
    "partnership",
    "agreement",
    "signs",
    "cooperation",
    "collaboration",
    "شراكة",
    "اتفاقية",
    "تعاون",
    "وقعت",
    "يوقع",
)

TRAINING_TERMS = (
    "bootcamp",
    "course",
    "training",
    "academy",
    "workshop",
    "برنامج تدريبي",
    "معسكر",
    "دورة",
    "كورسات",
    "تدريب",
    "أكاديمية",
    "ورشة",
)

MARKET_REPORT_TERMS = (
    "market size",
    "market growth",
    "forecast",
    "cagr",
    "market report",
    "حجم السوق",
    "نمو السوق",
    "توقعات السوق",
    "تقرير سوق",
)

DEVELOPER_TOOL_TERMS = (
    "github copilot",
    "vs code",
    "visual studio code",
    "api",
    "sdk",
    "coding agent",
    "coding agents",
    "developer tool",
    "developers",
    "framework",
    "library",
    "repository",
    " repo ",
    "github",
    "cli",
    "ide",
    "code editor",
    "programming",
    "software development",
    "devtools",
    "open source model",
    "open-source model",
    "benchmark",
    "inference",
    "fine-tuning",
    "deployment",
    "kubernetes",
    "python package",
    "npm",
    "برمجة",
    "مطوري",
    "مطوّري",
    "واجهة برمجة",
    "إطار عمل",
    "مكتبة",
)

GENERAL_USER_DOMAINS = (
    "writing",
    "writer",
    "search",
    "meeting",
    "meetings",
    "notes",
    "presentation",
    "design",
    "image",
    "video",
    "audio",
    "music",
    "productivity",
    "education",
    "learning",
    "teacher",
    "student",
    "tourism",
    "culture",
    "government service",
    "public service",
    "customer service",
    "workflow",
    "workspace",
    "document",
    "spreadsheet",
    "email",
    "browser",
    "writing assistant",
    "meeting assistant",
    "design tool",
    "أداة",
    "مساعد",
    "كتابة",
    "تصميم",
    "فيديو",
    "صور",
    "اجتماعات",
    "إنتاجية",
    "تعليم",
    "سياحة",
    "ثقافة",
    "خدمة حكومية",
)

USER_VALUE_TERMS = (
    "users can",
    "lets users",
    "helps users",
    "teams can",
    "customers can",
    "creators can",
    "teachers can",
    "students can",
    "now you can",
    "available to users",
    "for teams",
    "for creators",
    "for businesses",
    "for employees",
    "no-code",
    "without coding",
    "can now",
    "now available",
    "general availability",
    "يستطيع المستخدم",
    "يمكن للمستخدمين",
    "متاح الآن",
    "بدون برمجة",
)

KNOWN_AI_PRODUCT_TERMS = (
    "chatgpt",
    "openai",
    "claude",
    "anthropic",
    "gemini",
    "notebooklm",
    "heygen",
    "firefly",
    "adobe",
    "grok",
    "runway",
    "midjourney",
    "perplexity",
    "canva",
    "suno",
    "udio",
    "ltx",
    "krea",
    "kling",
    "luma",
    "figma",
    "elevenlabs",
    "deepseek",
    "cursor",
    "copilot",
    "exa",
)

GENERIC_UPDATE_INDEX_TITLES = {
    "changelog",
    "what's new",
    "what‘s new",
    "product updates",
    "product updates category",
    "release notes",
    "model news release notes",
    "newsroom",
    "latest press releases news from ltx",
    "photo editor online adobe lightroom",
}

GENERIC_UPDATE_INDEX_PATHS = (
    "/changelog",
    "/changelogs",
    "/release-notes",
    "/updates",
    "/newsroom",
    "/news/android",
    "/blog/category/product-updates",
    "/blog-category/product-updates",
)

GENERIC_UPDATE_TITLE_PREFIXES = (
    "product updates",
    "model news",
    "release notes",
    "azure updates",
    "microsoft 365 copilot news",
    "grammarly superhuman features",
    "new features product releases",
)

SIDE_STORY_TERMS = (
    "lawsuit",
    "sued",
    "stock",
    "ipo",
    "funding",
    "acquisition",
    "movie may have found",
    "sam altman movie",
    "patent:",
    "market report",
    "forecast",
    "price prediction",
)

GUIDE_OR_TUTORIAL_TERMS = (
    "tutorial:",
    "how to use",
    "guide)",
    "builder guide",
    "what we learned",
    "i tried",
    "review",
)

# User request 2026-07-18: stop selecting video-game/game-development stories
# for the newsletter (e.g. Roblox's AI game-building tool) regardless of how
# strong the underlying AI update otherwise looks. Multi-word phrases and
# named platforms only, same as the other term lists here, so this doesn't
# false-positive on unrelated idioms like "game-changing" or "game theory".
GAME_DEVELOPMENT_TERMS = (
    "video game",
    "video games",
    "game development",
    "game developer",
    "game engine",
    "game design",
    "game studio",
    "gaming platform",
    "build a game",
    "building a game",
    "create a game",
    "creating a game",
    "playable game",
    "roblox",
    "unity engine",
    "unreal engine",
    "esports",
)

LOW_VALUE_UI_CHANGE_TERMS = (
    "new cursor interface",
    "full-screen tabs",
    "compact chats",
    "canvas improvements",
    "more discoverable",
    "smart suggestions",
    "keyboard-first design",
    "new materials",
    "more expressive canvas",
    "context usage report",
)

STRONG_AI_CAPABILITY_TERMS = (
    "agent",
    "assistant",
    "voice",
    "image generation",
    "video generation",
    "generate",
    "native audio",
    "multimodal",
    "reasoning",
    "workflow",
    "automation",
    "analytics",
    "search",
    "transcription",
    "scribe",
    "presentation",
    "now available",
    "general availability",
    "rollout",
    "launch",
    "launched",
    "introducing",
    "ØªÙˆÙ„ÙŠØ¯",
    "Ù…Ø³Ø§Ø¹Ø¯",
    "ÙˆÙƒÙŠÙ„",
    "ØµÙˆØª",
    "ÙÙŠØ¯ÙŠÙˆ",
    "ØµÙˆØ±",
)

WEAK_FALLBACK_DOMAINS = {
    "lovecouplez.com",
    "taxheal.com",
    "jakkersbutikk.com",
    "hostdir.net",
    "completeaitraining.com",
    "frontiernews.ai",
    "htx.com",
    "patentlyze.com",
    "blockchain.news",
    "markets.financialcontent.com",
    "linkloot.io",
    "creati.ai",
    "cloud-captains.com",
    "pccentral.net",
    "xix.ai",
    "agentriot.com",
    "chatforest.com",
}


def _domain(url: str) -> str:
    return urlparse(str(url or "")).netloc.lower().replace("www.", "")


def _text(item: dict) -> str:
    return " ".join(
        str((item or {}).get(key) or "")
        for key in (
            "title",
            "content",
            "summary",
            "text",
            "snippet",
            "url",
            "source_domain",
            "bucket",
            "query",
        )
    ).lower()


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term and term.lower() in text for term in terms)


def _title_key(item: dict) -> str:
    title = str((item or {}).get("title") or "").lower()
    title = title.replace("|", " ").replace("·", " ").replace("-", " ")
    return " ".join(part for part in title.split() if part)


def _is_generic_update_index(item: dict) -> bool:
    title = _title_key(item)
    url_path = urlparse(str((item or {}).get("url") or "")).path.lower().rstrip("/")
    if title in GENERIC_UPDATE_INDEX_TITLES:
        return True
    if any(title.startswith(prefix) for prefix in GENERIC_UPDATE_TITLE_PREFIXES):
        return True
    if any(url_path == path or url_path.endswith(path) for path in GENERIC_UPDATE_INDEX_PATHS):
        return True
    return False


def _has_ai_product_signal(text: str) -> bool:
    return _has_any(text, AI_TERMS) or _has_any(text, KNOWN_AI_PRODUCT_TERMS)


def _has_explicit_old_year(item: dict) -> bool:
    text = _text(item)
    current_year = datetime.now(timezone.utc).year
    years = [int(match.group(0)) for match in re.finditer(r"\b20\d{2}\b", text)]
    return any(2018 <= year < current_year for year in years)


def _developer_term_hit(text: str, term: str) -> bool:
    if term in {"api", "sdk", "cli", "ide", "npm", "repo"}:
        return f" {term} " in f" {text} " or f"/{term}" in text or f"-{term}" in text
    return term in text


def is_saudi_official_source(url: str) -> bool:
    domain = _domain(url)
    return any(domain == root or domain.endswith(f".{root}") for root in SAUDI_OFFICIAL_DOMAINS)


def is_saudi_ai_candidate(item: dict) -> bool:
    text = _text(item)
    return (str((item or {}).get("bucket") or "") == "saudi_ai_news") or (
        _has_any(text, SAUDI_TERMS) and _has_any(text, AI_TERMS)
    )


def classify_saudi_ai_editorial_type(item: dict) -> str:
    text = _text(item)
    official = is_saudi_official_source(str((item or {}).get("url") or ""))
    if _has_any(text, TRAINING_TERMS):
        return "training_or_bootcamp"
    if _has_any(text, MARKET_REPORT_TERMS):
        return "market_report"
    if not _has_any(text, SAUDI_TERMS) or not _has_any(text, AI_TERMS):
        return "reject"
    if _has_any(text, POLICY_TERMS):
        return "official_ai_policy" if official or _has_any(text, ("sdaia", "سدايا", "ndmo", "mcit")) else "reject"
    if _has_any(text, PLATFORM_TERMS) and (official or _has_any(text, ("humain", "sdaia", "هيومين", "سدايا"))):
        return "official_ai_platform"
    if _has_any(text, GOVERNMENT_SERVICE_TERMS) and official:
        return "official_ai_government_service"
    if _has_any(text, SECTOR_TERMS) and (official or _has_any(text, ("ministry", "وزارة", "authority", "هيئة"))):
        return "official_ai_sector_adoption"
    if _has_any(text, PARTNERSHIP_TERMS):
        return "official_ai_sector_adoption" if official else "private_ai_partnership"
    return "reject"


def saudi_ai_editorial_fit_score(item: dict, editorial_type: str) -> int:
    text = _text(item)
    score = 0
    if is_saudi_official_source(str((item or {}).get("url") or "")):
        score += 5
    if _has_any(text, POLICY_TERMS):
        score += 4
    if _has_any(text, PLATFORM_TERMS):
        score += 4
    if _has_any(text, SECTOR_TERMS):
        score += 3
    if _has_any(text, ("استطلاع مرئيات", "سياسة", "إطار تنظيمي", "حوكمة", "public consultation", "policy", "governance")):
        score += 2
    if _has_any(text, TRAINING_TERMS):
        score -= 5
    if _has_any(text, MARKET_REPORT_TERMS):
        score -= 4
    if editorial_type == "private_ai_partnership":
        score -= 3
    if editorial_type == "reject":
        score -= 3
    if editorial_type not in ACCEPTED_SAUDI_AI_EDITORIAL_TYPES:
        score -= 3
    return score


def general_user_fit_score(item: dict) -> tuple[int, list[str]]:
    text = _text(item)
    reasons: list[str] = []
    score = 0
    developer_hits = [term.strip() for term in DEVELOPER_TOOL_TERMS if term and _developer_term_hit(text, term)]
    if developer_hits:
        score -= 8
        reasons.append(f"developer_tool:{','.join(developer_hits[:3])}")
    domain_hits = [term for term in GENERAL_USER_DOMAINS if term in text]
    if domain_hits:
        score += min(6, len(domain_hits) * 2)
        reasons.append(f"general_user_domain:{','.join(domain_hits[:4])}")
    value_hits = [term for term in USER_VALUE_TERMS if term in text]
    if value_hits:
        score += min(6, len(value_hits) * 3)
        reasons.append(f"user_value:{','.join(value_hits[:3])}")
    if "launch" in text or "now available" in text or "generally available" in text or "rolls out" in text:
        score += 2
        reasons.append("available_now_signal")
    if not domain_hits and not value_hits:
        score -= 4
        reasons.append("no_clear_nontechnical_user_value")
    return score, reasons


def annotate_news_candidate(item: dict) -> dict:
    annotations: dict = {}
    score, reasons = general_user_fit_score(item)
    annotations["general_user_fit_score"] = score
    annotations["audience_fit_reasons"] = reasons
    if is_saudi_ai_candidate(item):
        editorial_type = classify_saudi_ai_editorial_type(item)
        annotations["editorial_type"] = editorial_type
        annotations["editorial_fit_score"] = saudi_ai_editorial_fit_score(item, editorial_type)
    return annotations


def production_news_reject_reason(item: dict) -> str:
    item = item or {}
    text = _text(item)
    domain = _domain(str(item.get("url") or ""))
    lane = str(item.get("source_lane") or "").strip()
    query_mix = str(item.get("query_mix") or "").strip()
    date_confidence = str(item.get("date_confidence") or item.get("verified_date_confidence") or "").strip().lower()

    if _has_explicit_old_year(item):
        return "explicit_old_year"

    if _is_generic_update_index(item) and date_confidence in {"", "low"}:
        return "generic_update_index_without_verified_date"

    if _has_any(text, SIDE_STORY_TERMS):
        return "side_story_not_product_update"

    if _has_any(text, GAME_DEVELOPMENT_TERMS):
        return "game_development_or_gaming_excluded"

    if _has_any(text, GUIDE_OR_TUTORIAL_TERMS):
        return "guide_or_tutorial_not_news"

    if _has_any(text, LOW_VALUE_UI_CHANGE_TERMS) and not _has_any(text, STRONG_AI_CAPABILITY_TERMS):
        return "low_value_ui_or_navigation_change"

    if lane == "fallback_broad" and domain in WEAK_FALLBACK_DOMAINS:
        return "weak_fallback_domain"

    if query_mix in {"tool_name_update", "exa_product_update_broad", "trusted_media_tool_update"} and not _has_ai_product_signal(text):
        return "missing_ai_product_signal"

    if is_saudi_ai_candidate(item):
        editorial_type = str((item or {}).get("editorial_type") or classify_saudi_ai_editorial_type(item))
        score = int((item or {}).get("editorial_fit_score") or saudi_ai_editorial_fit_score(item, editorial_type))
        if editorial_type not in ACCEPTED_SAUDI_AI_EDITORIAL_TYPES or score <= 0:
            return "saudi_ai_editorial_fit_failed"

    fit_score = int((item or {}).get("general_user_fit_score") or 0)
    reasons = [str(reason) for reason in ((item or {}).get("audience_fit_reasons") or [])]
    developer_only = any(reason.startswith("developer_tool:") for reason in reasons)
    unclear_user_value = any(reason == "no_clear_nontechnical_user_value" for reason in reasons)
    if developer_only and (fit_score < 1 or unclear_user_value):
        return "developer_or_unclear_general_user_value"
    return ""
