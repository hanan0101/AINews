# This file is part of the AI newsletter system.
"""Persistent course bank and weekly course rotation."""

from __future__ import annotations

import hashlib
import random
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

from backend.config.settings import (
    AI_UPDATES_RUN_REPORT_FILE,
    clean_text,
    load_json,
    normalized_text,
    safe_write_json,
    source_domain,
    utc_now,
)

COURSE_BANK_FILE = AI_UPDATES_RUN_REPORT_FILE.with_name("course_bank.json")
COURSE_SELECTION_HISTORY_FILE = AI_UPDATES_RUN_REPORT_FILE.with_name("course_selection_history.json")
COURSE_WEEKLY_SELECTION_REPORT_FILE = AI_UPDATES_RUN_REPORT_FILE.with_name("course_weekly_selection_report.json")

COURSE_LEVELS = ("beginner", "intermediate", "advanced")
COURSE_WEEKLY_TARGET_PER_LEVEL = 2
COURSE_WEEKLY_TARGET_COUNT = 6
COURSE_REPEAT_BLOCK_DAYS = 180

ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
COURSE_SUMMARY_MAX_CHARS = 900

LANDING_COURSE_PATHS = {
    "",
    "/",
    "/index.html",
    "/learn",
    "/learning",
    "/academy",
    "/courses",
    "/course",
    "/training",
    "/programs",
    "/pages/courses",
}

COURSE_DIRECT_PATH_HINTS = (
    "/course/",
    "/courses/",
    "/public/courses/",
    "/course_templates/",
    "/training/paths/",
    "/training/modules/",
    "/learn/course/",
    "/academy/courses/",
    "/paths/",
)

LANDING_TITLE_TERMS = (
    "home",
    "homepage",
    "الرئيسية",
    "resources & guides",
    "learning resources",
    "academy",
    "learn",
    "معهد تقنية المعلومات",
)

NAVIGATION_JUNK_TERMS = (
    "skip navigation",
    "search sign in",
    "powered by",
    "هل استفدت من المعلومات",
    "إرسال التعليق",
)

BEGINNER_TERMS = (
    "beginner", "beginners", "foundation", "foundations", "fundamental", "fundamentals",
    "intro", "introduction", "basics", "essential", "essentials", "getting started",
    "start", "for everyone", "non technical", "non-technical", "no-code", "no code",
    "مبتدئ", "مبتدئين", "أساسيات", "مقدمة", "تمهيدي",
)
ADVANCED_TERMS = (
    "advanced", "expert", "professional certificate", "specialization", "architecture",
    "mlops", "deployment", "deep learning", "machine learning engineering", "fine-tuning",
    "api", "sdk", "developer", "developers", "security", "cloud", "agentic",
    "متقدم", "احترافي", "هندسة", "أمني", "الأمن",
)
INTERMEDIATE_TERMS = (
    "intermediate", "applied", "hands-on", "hands on", "practical", "project",
    "workflow", "workflows", "automation", "productivity", "business", "marketing",
    "sales", "prompt engineering", "use cases", "build", "create",
    "تطبيقي", "عملي", "الأعمال", "الإنتاجية", "التسويق", "الأتمتة",
)

FREE_TERMS = ("free", "no cost", "complimentary", "مجاني", "مجانية")
PAID_TERMS = ("paid", "subscription", "pricing", "fee", "مدفوع", "رسوم")
WORK_TERMS = (
    "employee", "employees", "professional", "professionals", "workplace", "productivity",
    "business", "marketing", "sales", "management", "customer", "workflow", "automation",
    "team", "teams", "upskill", "upskilling", "موظف", "موظفين", "مهني", "مهنيين",
    "الأعمال", "العمل", "الإنتاجية", "التسويق", "المبيعات", "الأتمتة",
)
TECHNICAL_TERMS = (
    "api", "sdk", "developer", "developers", "python", "javascript", "cloud", "mlops",
    "deployment", "fine-tuning", "notebook", "github", "kubernetes", "docker",
)
STUDENT_TERMS = (
    "k-12", "kids", "children", "homework", "scholarship", "university students",
    "طلاب", "طالبات", "مدارس", "واجبات", "منح",
)
TOPIC_RULES = (
    ("prompting", ("prompt", "prompting", "هندسة الأوامر")),
    ("productivity", ("productivity", "office", "copilot", "notion", "asana", "airtable", "miro")),
    ("automation", ("automation", "workflow", "zapier", "make", "orchestrator", "agent")),
    ("marketing_sales", ("marketing", "sales", "hubspot", "semrush", "content")),
    ("creative", ("creative", "design", "image", "video", "canva", "adobe", "figma", "synthesia")),
    ("data_ai", ("data", "analytics", "machine learning", "deep learning", "model", "kaggle", "datacamp")),
    ("responsible_ai", ("responsible", "ethics", "governance", "safety")),
    ("ai_basics", ("foundation", "fundamentals", "introduction", "basics", "essentials")),
)


def canonical_course_url(url: str = "") -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.netloc:
        return str(url or "").strip().rstrip("/")
    clean = parsed._replace(netloc=parsed.netloc.lower().replace("www.", ""), query="", fragment="")
    return urlunparse(clean).rstrip("/")


def course_key(url: str = "", title: str = "") -> str:
    value = canonical_course_url(url) or normalized_text(title)
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16] if value else ""


def load_course_bank() -> dict:
    return load_json(COURSE_BANK_FILE, {"courses": {}, "updated_at": "", "schema": "course_bank_v1"})


def save_course_bank(bank: dict) -> None:
    bank["updated_at"] = utc_now().isoformat()
    bank["schema"] = "course_bank_v1"
    safe_write_json(COURSE_BANK_FILE, bank)


def load_course_history() -> dict:
    return load_json(COURSE_SELECTION_HISTORY_FILE, {"selections": [], "updated_at": "", "schema": "course_selection_history_v1"})


def save_course_history(history: dict) -> None:
    history["updated_at"] = utc_now().isoformat()
    history["schema"] = "course_selection_history_v1"
    safe_write_json(COURSE_SELECTION_HISTORY_FILE, history)


def parse_dt(value: str = "") -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def normalize_level(value: str = "", evidence: str = "") -> str:
    text = normalized_text(f"{value} {evidence}")
    if "beginner" in text:
        return "beginner"
    if "intermediate" in text:
        return "intermediate"
    if "advanced" in text:
        return "advanced"
    if any(term in text for term in ADVANCED_TERMS):
        return "advanced"
    if any(term in text for term in BEGINNER_TERMS):
        return "beginner"
    if any(term in text for term in INTERMEDIATE_TERMS):
        return "intermediate"
    return "intermediate"


def infer_topic(evidence: str = "") -> str:
    text = normalized_text(evidence)
    for topic, terms in TOPIC_RULES:
        if any(term in text for term in terms):
            return topic
    words = [word for word in text.split() if len(word) > 3]
    return words[0] if words else "general_ai"


def infer_language(evidence: str = "") -> str:
    return "ar" if ARABIC_RE.search(str(evidence or "")) else "en"


def infer_free_status(evidence: str = "") -> str:
    text = normalized_text(evidence)
    if any(term in text for term in FREE_TERMS):
        return "free"
    if any(term in text for term in PAID_TERMS):
        return "paid"
    return "unknown"


def infer_audience(evidence: str = "", employee_fit_score: int = 0) -> str:
    text = normalized_text(evidence)
    if any(term in text for term in STUDENT_TERMS):
        return "student"
    technical = any(term in text for term in TECHNICAL_TERMS)
    work = any(term in text for term in WORK_TERMS)
    if technical and work:
        return "technical_employee"
    if technical and employee_fit_score < 3:
        return "developer"
    if work or employee_fit_score >= 4:
        return "employee"
    return "general"


def infer_employee_fit_score(evidence: str = "", existing: int | None = None) -> int:
    if existing is not None and int(existing or 0) > 0:
        return max(0, min(5, int(existing)))
    text = normalized_text(evidence)
    score = 2
    if any(term in text for term in WORK_TERMS):
        score += 2
    if any(term in text for term in ("course", "training", "certificate", "academy", "learn", "learning", "دورة", "تدريب")):
        score += 1
    if any(term in text for term in STUDENT_TERMS):
        score -= 2
    if any(term in text for term in TECHNICAL_TERMS) and not any(term in text for term in WORK_TERMS):
        score -= 1
    return max(0, min(5, score))


def platform_label(item: dict) -> str:
    return clean_text(item.get("platform") or item.get("provider") or item.get("source") or source_domain(item.get("url") or ""))


def compact_course_text(text: str = "", title: str = "", platform: str = "") -> str:
    cleaned = clean_text(text or "")
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cleaned)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    title_clean = clean_text(title or "")
    if title_clean and cleaned.lower().startswith(title_clean.lower()):
        cleaned = cleaned[len(title_clean):].strip(" -|#")
    if not cleaned:
        return f"Course from {platform} focused on practical AI skills."
    if len(cleaned) > COURSE_SUMMARY_MAX_CHARS:
        cut = cleaned[:COURSE_SUMMARY_MAX_CHARS].rsplit(" ", 1)[0].strip()
        cleaned = f"{cut}..."
    return cleaned


def course_is_direct_learning_page(url: str = "", title: str = "", text: str = "") -> bool:
    parsed = urlparse(canonical_course_url(url))
    path = (parsed.path or "/").lower().rstrip("/") or "/"
    title_norm = normalized_text(title)
    evidence = normalized_text(f"{title} {text} {path}")
    if path in LANDING_COURSE_PATHS:
        return False
    if parsed.netloc.endswith("sdaia.gov.sa") and "/sectors/buildingcapacity/it-institute/" in path:
        return False
    if parsed.netloc.endswith("anthropic.com") and path in {"/learn", "/"}:
        return False
    if any(term in title_norm for term in LANDING_TITLE_TERMS) and not any(hint.strip("/") in path for hint in COURSE_DIRECT_PATH_HINTS):
        return False
    if any(term in normalized_text(text) for term in NAVIGATION_JUNK_TERMS) and not any(hint in path for hint in COURSE_DIRECT_PATH_HINTS):
        return False
    if any(hint in path for hint in COURSE_DIRECT_PATH_HINTS):
        return any(term in evidence for term in ("course", "training", "certificate", "learn", "learning", "دورة", "تدريب", "مسار"))
    return False


def normalize_bank_course(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    title = clean_text(item.get("title") or "")
    url = canonical_course_url(item.get("url") or item.get("source_url") or "")
    if not title or not url:
        return None
    platform = platform_label(item)
    raw_text = clean_text(item.get("text") or item.get("summary") or item.get("content") or "")
    if not course_is_direct_learning_page(url, title, raw_text):
        return None
    text = compact_course_text(raw_text, title=title, platform=platform)
    domain = source_domain(url)
    evidence = f"{title} {text} {item.get('source_query') or ''} {url}"
    employee_score = infer_employee_fit_score(evidence, item.get("employee_fit_score"))
    audience = clean_text(item.get("audience") or "") or infer_audience(evidence, employee_score)
    level = normalize_level(item.get("level") or "", evidence)
    key = course_key(url, title)
    now = utc_now().isoformat()
    return {
        **item,
        "id": item.get("id") or f"course-{key}",
        "course_key": key,
        "title": title,
        "text": text or f"Course from {platform} focused on practical AI skills.",
        "summary": text,
        "content": text,
        "url": url,
        "source_url": url,
        "platform": platform,
        "provider": platform,
        "source": platform,
        "domain": domain,
        "level": level,
        "audience": audience,
        "employee_fit_score": employee_score,
        "is_work_relevant": bool(employee_score >= 3 and audience not in {"student", "developer"}),
        "topic": clean_text(item.get("topic") or item.get("topic_group") or "") or infer_topic(evidence),
        "topic_group": clean_text(item.get("topic_group") or "") or infer_topic(evidence),
        "language": clean_text(item.get("language") or "") or infer_language(evidence),
        "free_status": clean_text(item.get("free_status") or "") or infer_free_status(evidence),
        "last_verified_at": item.get("last_verified_at") or now,
        "first_seen_at": item.get("first_seen_at") or now,
        "selected_count": int(item.get("selected_count") or 0),
        "type": "course",
    }


def upsert_course_bank(courses: list[dict]) -> dict:
    bank = load_course_bank()
    existing = bank.setdefault("courses", {})
    added = 0
    updated = 0
    for item in courses or []:
        normalized = normalize_bank_course(item)
        if not normalized:
            continue
        key = normalized["course_key"]
        current = existing.get(key) if isinstance(existing.get(key), dict) else {}
        selected_count = int(current.get("selected_count") or normalized.get("selected_count") or 0)
        first_seen_at = current.get("first_seen_at") or normalized.get("first_seen_at")
        merged = {**current, **normalized}
        merged["selected_count"] = selected_count
        merged["first_seen_at"] = first_seen_at
        existing[key] = merged
        if current:
            updated += 1
        else:
            added += 1
    save_course_bank(bank)
    return {"added": added, "updated": updated, "total": len(existing)}


def active_bank_courses() -> list[dict]:
    courses = list((load_course_bank().get("courses") or {}).values())
    output = []
    for item in courses:
        normalized = normalize_bank_course(item)
        if not normalized:
            continue
        if normalized.get("audience") in {"student", "developer"}:
            continue
        if int(normalized.get("employee_fit_score") or 0) < 3:
            continue
        output.append(normalized)
    return output


def month_buckets(platforms: list[str], issue_date: datetime) -> dict[str, list[str]]:
    seed = f"{issue_date.year}-{issue_date.month:02d}"
    shuffled = sorted(set(platforms))
    random.Random(seed).shuffle(shuffled)
    buckets = {f"bucket_{idx}": [] for idx in range(1, 5)}
    for index, platform in enumerate(shuffled):
        buckets[f"bucket_{(index % 4) + 1}"].append(platform)
    return buckets


def week_bucket_name(issue_date: datetime) -> str:
    week = min(4, max(1, ((issue_date.day - 1) // 7) + 1))
    return f"bucket_{week}"


def issue_identity(issue_date: datetime | None = None, issue_id: str = "") -> tuple[str, datetime]:
    date = issue_date or utc_now()
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return issue_id or f"{date.year}-W{date.isocalendar().week:02d}", date


def recent_history(history: dict, issue_id: str, issue_date: datetime) -> tuple[set[str], set[str]]:
    cutoff = issue_date - timedelta(days=COURSE_REPEAT_BLOCK_DAYS)
    repeated_urls = set()
    previous_platforms = set()
    previous_issue_date = None
    for row in history.get("selections") or []:
        if row.get("issue_id") == issue_id:
            continue
        row_date = parse_dt(row.get("issue_date") or "")
        if row_date and row_date >= cutoff:
            repeated_urls.add(canonical_course_url(row.get("course_url") or ""))
        if row_date and row_date < issue_date and (previous_issue_date is None or row_date > previous_issue_date):
            previous_issue_date = row_date
            previous_platforms = {normalized_text(item.get("platform") or "") for item in history.get("selections") or [] if item.get("issue_date") == row.get("issue_date")}
    return repeated_urls, previous_platforms


def next_platform_rotation(history: dict, platforms: list[str], issue_date: datetime, count: int) -> dict:
    active = sorted({normalized_text(platform) for platform in platforms if normalized_text(platform)})
    rotation = history.get("platform_rotation") if isinstance(history.get("platform_rotation"), dict) else {}
    remaining = [platform for platform in rotation.get("remaining_platforms") or [] if platform in active]
    cycle = int(rotation.get("cycle") or 0)
    if len(remaining) < min(count, len(active)):
        cycle += 1
        remaining = list(active)
        random.Random(f"{issue_date.date().isoformat()}-{cycle}-{len(active)}").shuffle(remaining)
    selected = remaining[: min(count, len(remaining))]
    remaining = remaining[len(selected):]
    return {
        "cycle": cycle,
        "selected_platforms": selected,
        "remaining_platforms": remaining,
        "active_platform_count": len(active),
        "target_platform_count": count,
        "reshuffled": len(rotation.get("remaining_platforms") or []) < min(count, len(active)),
    }


def candidate_score(item: dict, current_bucket: set[str], previous_platforms: set[str]) -> tuple:
    platform = normalized_text(item.get("platform") or "")
    verified = parse_dt(item.get("last_verified_at") or "") or datetime(1970, 1, 1, tzinfo=timezone.utc)
    age_days = max(0, (utc_now() - verified).days)
    return (
        int(platform in current_bucket),
        int(int(item.get("selected_count") or 0) == 0),
        int(item.get("free_status") == "free"),
        int(item.get("employee_fit_score") or 0),
        int(item.get("language") == "ar"),
        -age_days,
        -int(item.get("selected_count") or 0),
        -int(platform in previous_platforms),
        normalized_text(item.get("title") or ""),
    )


def selection_report(courses: list[dict], selected: list[dict], diagnostics: dict) -> dict:
    by_level = Counter(item.get("level") or "unknown" for item in courses)
    active_platforms = sorted({item.get("platform") for item in courses if item.get("platform")})
    return {
        "generated_at": utc_now().isoformat(),
        "bank_counts_by_level": dict(by_level),
        "active_platform_count": len(active_platforms),
        "used_platforms": [item.get("platform") for item in selected],
        "fallback_used": bool(diagnostics.get("fallback_used")),
        "shortages": diagnostics.get("shortages") or {},
        "bucket": diagnostics.get("bucket"),
        "bucket_platforms": diagnostics.get("bucket_platforms") or [],
        "platform_rotation": diagnostics.get("platform_rotation") or {},
        "selected_count": len(selected),
        "selected_by_level": dict(Counter(item.get("level") or "unknown" for item in selected)),
    }


def select_weekly_courses(target_count: int = COURSE_WEEKLY_TARGET_COUNT, issue_id: str = "", issue_date: datetime | None = None) -> tuple[list[dict], dict]:
    issue_id, date = issue_identity(issue_date, issue_id)
    courses = active_bank_courses()
    history = load_course_history()
    repeated_urls, previous_platforms = recent_history(history, issue_id, date)
    buckets = month_buckets([normalized_text(item.get("platform") or "") for item in courses], date)
    bucket_name = week_bucket_name(date)
    platform_rotation = next_platform_rotation(
        history,
        [item.get("platform") or "" for item in courses],
        date,
        target_count,
    )
    current_bucket = set(platform_rotation.get("selected_platforms") or [])
    selected = []
    used_platforms = set()
    used_urls = set()
    diagnostics = {
        "issue_id": issue_id,
        "issue_date": date.date().isoformat(),
        "bucket": bucket_name,
        "bucket_platforms": sorted(current_bucket),
        "platform_rotation": platform_rotation,
        "fallback_used": False,
        "shortages": {},
    }

    def eligible_for_level(level: str) -> list[dict]:
        candidates = [
            item for item in courses
            if item.get("level") == level
            and canonical_course_url(item.get("url") or "") not in repeated_urls
            and canonical_course_url(item.get("url") or "") not in used_urls
            and normalized_text(item.get("platform") or "") not in used_platforms
        ]
        return sorted(candidates, key=lambda item: candidate_score(item, current_bucket, previous_platforms), reverse=True)

    for level in COURSE_LEVELS:
        level_selected = 0
        for item in eligible_for_level(level):
            selected.append(dict(item))
            used_urls.add(canonical_course_url(item.get("url") or ""))
            used_platforms.add(normalized_text(item.get("platform") or ""))
            level_selected += 1
            if level_selected >= COURSE_WEEKLY_TARGET_PER_LEVEL:
                break
        if level_selected < COURSE_WEEKLY_TARGET_PER_LEVEL:
            diagnostics["fallback_used"] = True
            diagnostics["shortages"][level] = {
                "needed": COURSE_WEEKLY_TARGET_PER_LEVEL,
                "selected": level_selected,
                "reason": "not_enough_unique_platforms_or_recent_repeat_block",
            }

    if len(selected) < target_count:
        diagnostics["fallback_used"] = True
        fallback_pool = [
            item for item in courses
            if canonical_course_url(item.get("url") or "") not in repeated_urls
            and canonical_course_url(item.get("url") or "") not in used_urls
            and normalized_text(item.get("platform") or "") not in used_platforms
        ]
        fallback_pool = sorted(fallback_pool, key=lambda item: candidate_score(item, current_bucket, previous_platforms), reverse=True)
        for item in fallback_pool:
            selected.append(dict(item))
            used_urls.add(canonical_course_url(item.get("url") or ""))
            used_platforms.add(normalized_text(item.get("platform") or ""))
            if len(selected) >= target_count:
                break

    selected = selected[:target_count]
    bank = load_course_bank()
    bank_courses = bank.setdefault("courses", {})
    for item in selected:
        key = item.get("course_key") or course_key(item.get("url") or "", item.get("title") or "")
        if key in bank_courses:
            bank_courses[key]["selected_count"] = int(bank_courses[key].get("selected_count") or 0) + 1
            bank_courses[key]["last_selected_at"] = date.isoformat()
    save_course_bank(bank)

    history_rows = [row for row in history.get("selections") or [] if row.get("issue_id") != issue_id]
    for item in selected:
        history_rows.append({
            "issue_id": issue_id,
            "issue_date": date.isoformat(),
            "course_url": canonical_course_url(item.get("url") or ""),
            "platform": item.get("platform") or "",
            "level": item.get("level") or "",
        })
    history["selections"] = history_rows[-1000:]
    history["platform_rotation"] = {
        **platform_rotation,
        "updated_at": utc_now().isoformat(),
        "last_issue_id": issue_id,
        "last_issue_date": date.isoformat(),
    }
    save_course_history(history)

    for item in selected:
        item["level"] = item.get("level", "").title()
        item["status"] = item.get("status") or ""
        item["selection_source"] = "course_bank_weekly_rotation"
        item["issue_id"] = issue_id

    report = selection_report(courses, selected, diagnostics)
    safe_write_json(COURSE_WEEKLY_SELECTION_REPORT_FILE, report)
    print(
        "[AI Updates] weekly course selection "
        f"bank_levels={report['bank_counts_by_level']} active_platforms={report['active_platform_count']} "
        f"used_platforms={', '.join(report['used_platforms'])} fallback={report['fallback_used']} "
        f"shortages={report['shortages']}",
        flush=True,
    )
    return selected, report
