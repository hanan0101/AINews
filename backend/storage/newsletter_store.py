# This file is part of the AI newsletter system.
"""Newsletter settings and news.json storage helpers for the HTTP server."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from backend.utils.debug_logging import trace
from backend.server.card_items import (
    dedupe_store_items,
    is_current_schema_item,
    looks_duplicate,
    normalize_item,
    order_news_for_visible_diversity,
    safe_replace_json,
    validate_replacement_candidate,
)
from backend.utils.text_normalization import cleanup_text_fields, repair_mojibake_text

ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR.parent / "frontend"
RUNTIME_DATA_DIR = ROOT_DIR.parent / "data" / "news" / "runtime"
NEWSLETTER_SETTINGS_FILE = RUNTIME_DATA_DIR / "newsletter_settings.json"
NEWS_FETCH_STATE_FILE = ROOT_DIR / "pipeline" / "fetching" / "news_fetch_state.json"
NEWS_SELECTION_AUDIT_FILE = ROOT_DIR / "news_selection_audit.json"

load_dotenv(ROOT_DIR / ".env", override=True)


# Performs the env path helper step.
def env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value) if value else default


NEWS_JSON_FILE = env_path("NEWS_JSON_PATH", RUNTIME_DATA_DIR / "news.json")
PUBLISHED_NEWS_JSON_FILE = env_path(
    "PUBLISHED_NEWS_JSON_PATH",
    NEWS_JSON_FILE.with_name("news_published.json"),
)
PREVIOUS_NEWS_JSON_FILE = env_path("PREVIOUS_NEWS_JSON_PATH", NEWS_JSON_FILE.with_name("news_previous.json"))

REQUIRED_COUNTS = {
    "items": 4,
    "movies": 2,
    "courses": 6,
}
DISPLAY_COUNTS = {
    "items": 4,
    "movies": 2,
    "courses": 6,
}
SECTION_TO_CONTENT_TYPE = {
    "items": "news",
    "movies": "movie",
    "courses": "course",
}
SECTION_LABELS = {
    "items": "news items",
    "movies": "movies",
    "courses": "courses",
}
MIN_ITEMS = REQUIRED_COUNTS["items"]
FEATURE_MODES = {"course", "movie"}
SECTION_KEYS = {"items", "movies", "courses"}
DEFAULT_TEMPLATE = {
    "newsletter_title": "نشرة أخبار \nالذكاء الاصطناعي",
}
DEFAULT_NEWSLETTER_SETTINGS = {
    "newsletter_title": "نشرة أخبار \nالذكاء الاصطناعي",
    "footer_prefix": "تطوير : إدارة المرصد الثقافي",
    "issue_number": 7,
    "month_year_override": "",
}
ARABIC_MONTHS = [
    "يناير",
    "فبراير",
    "مارس",
    "أبريل",
    "مايو",
    "يونيو",
    "يوليو",
    "أغسطس",
    "سبتمبر",
    "أكتوبر",
    "نوفمبر",
    "ديسمبر",
]

# Level-balanced newsletter change: keep 12 total news cards in the bank while
# the recommended/default view displays only 4 cards.
NEWS_BACKUP_COUNT = max(0, int(os.getenv("NEWS_BACKUP_COUNT", str(max(0, 12 - DISPLAY_COUNTS["items"]))) or "8"))
NEWS_PREVIOUS_SNAPSHOT_ENABLED = os.getenv("NEWS_PREVIOUS_SNAPSHOT_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
NEWS_FETCH_STATE_LOCK = threading.Lock()


# Returns whether is gpt accepted news item is true for the current input.
def is_gpt_accepted_news_item(item):
    if not isinstance(item, dict):
        return False
    return bool(item.get("simple_gpt_selected"))


# Performs the reorder positions helper step.
def reorder_positions(items):
    for index, item in enumerate(items, start=1):
        item["position"] = index
    return items


# Performs the safe int helper step.
def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


# Performs the arabic number to words helper step.
def arabic_number_to_words(value, *, ordinal=False):
    try:
        number = int(value or 0)
    except Exception:
        return ""
    cardinal = {
        0: "صفر", 1: "واحد", 2: "اثنان", 3: "ثلاثة", 4: "أربعة", 5: "خمسة",
        6: "ستة", 7: "سبعة", 8: "ثمانية", 9: "تسعة", 10: "عشرة",
        11: "أحد عشر", 12: "اثنا عشر", 13: "ثلاثة عشر", 14: "أربعة عشر",
        15: "خمسة عشر", 16: "ستة عشر", 17: "سبعة عشر", 18: "ثمانية عشر",
        19: "تسعة عشر", 20: "عشرون",
    }
    ordinal_words = {
        0: "الصفر", 1: "الأول", 2: "الثاني", 3: "الثالث", 4: "الرابع",
        5: "الخامس", 6: "السادس", 7: "السابع", 8: "الثامن", 9: "التاسع",
        10: "العاشر", 11: "الحادي عشر", 12: "الثاني عشر", 13: "الثالث عشر",
        14: "الرابع عشر", 15: "الخامس عشر", 16: "السادس عشر",
        17: "السابع عشر", 18: "الثامن عشر", 19: "التاسع عشر", 20: "العشرون",
    }
    clean_words = ordinal_words if ordinal else cardinal
    if number in clean_words:
        return clean_words[number]
    if number == 0:
        return "الصفر" if ordinal else "صفر"
    if number < 0:
        text = arabic_number_to_words(abs(number), ordinal=ordinal)
        return f"سالب {text}" if text else ""

    ones = {
        1: "واحد", 2: "اثنان", 3: "ثلاثة", 4: "أربعة", 5: "خمسة",
        6: "ستة", 7: "سبعة", 8: "ثمانية", 9: "تسعة",
    }
    ordinal_ones = {
        1: "الأول", 2: "الثاني", 3: "الثالث", 4: "الرابع", 5: "الخامس",
        6: "السادس", 7: "السابع", 8: "الثامن", 9: "التاسع",
    }
    ordinal_compound_ones = {
        1: "الحادي", 2: "الثاني", 3: "الثالث", 4: "الرابع", 5: "الخامس",
        6: "السادس", 7: "السابع", 8: "الثامن", 9: "التاسع",
    }
    tens = {
        10: "عشرة", 20: "عشرون", 30: "ثلاثون", 40: "أربعون", 50: "خمسون",
        60: "ستون", 70: "سبعون", 80: "ثمانون", 90: "تسعون",
    }
    ordinal_tens = {
        10: "العاشر", 20: "العشرون", 30: "الثلاثون", 40: "الأربعون",
        50: "الخمسون", 60: "الستون", 70: "السبعون", 80: "الثمانون", 90: "التسعون",
    }
    teens = {
        11: "أحد عشر", 12: "اثنا عشر", 13: "ثلاثة عشر", 14: "أربعة عشر",
        15: "خمسة عشر", 16: "ستة عشر", 17: "سبعة عشر", 18: "ثمانية عشر", 19: "تسعة عشر",
    }
    ordinal_teens = {
        11: "الحادي عشر", 12: "الثاني عشر", 13: "الثالث عشر", 14: "الرابع عشر",
        15: "الخامس عشر", 16: "السادس عشر", 17: "السابع عشر",
        18: "الثامن عشر", 19: "التاسع عشر",
    }
    hundreds = {
        1: "مئة", 2: "مئتان", 3: "ثلاثمئة", 4: "أربعمئة", 5: "خمسمئة",
        6: "ستمئة", 7: "سبعمئة", 8: "ثمانمئة", 9: "تسعمئة",
    }
    ordinal_hundreds = {
        1: "المئة", 2: "المئتان", 3: "الثلاثمئة", 4: "الأربعمئة", 5: "الخمسمئة",
        6: "الستمئة", 7: "السبعمئة", 8: "الثمانمئة", 9: "التسعمئة",
    }

    # Performs the under hundred helper step.
    def under_hundred(n, as_ordinal=False):
        if n < 10:
            return (ordinal_ones if as_ordinal else ones).get(n, "")
        if n == 10:
            return ordinal_tens[10] if as_ordinal else tens[10]
        if 11 <= n <= 19:
            return ordinal_teens[n] if as_ordinal else teens[n]
        unit = n % 10
        ten = n - unit
        if not unit:
            return ordinal_tens[ten] if as_ordinal else tens[ten]
        unit_text = (ordinal_compound_ones if as_ordinal else ones)[unit]
        ten_text = ordinal_tens[ten] if as_ordinal else tens[ten]
        return f"{unit_text} و{ten_text}"

    # Performs the under thousand helper step.
    def under_thousand(n, as_ordinal=False):
        if n < 100:
            return under_hundred(n, as_ordinal)
        hundred = n // 100
        remainder = n % 100
        prefix = ordinal_hundreds[hundred] if as_ordinal else hundreds[hundred]
        return f"{prefix} و{under_hundred(remainder, as_ordinal)}" if remainder else prefix

    if number >= 1000:
        return str(number)
    return under_thousand(number, ordinal)


# Returns whether issue label is true for the current input.
def issue_label(issue_number):
    number = safe_int(issue_number, DEFAULT_NEWSLETTER_SETTINGS["issue_number"])
    return arabic_number_to_words(number, ordinal=True) or str(number)


# Prepares clean setting text so downstream stages receive consistent data.
def clean_setting_text(value, default=""):
    value = repair_mojibake_text(str(value or default or ""))
    return value.strip()


# Reads current arabic month year from the current store or request context.
def current_arabic_month_year():
    now = datetime.now()
    month = ARABIC_MONTHS[now.month - 1]
    return f"{month} {now.year}"


# Prepares normalize newsletter settings so downstream stages receive consistent data.
def normalize_newsletter_settings(settings):
    raw = settings if isinstance(settings, dict) else {}
    normalized = dict(DEFAULT_NEWSLETTER_SETTINGS)
    for key in DEFAULT_NEWSLETTER_SETTINGS:
        if key in raw:
            normalized[key] = raw[key]
    normalized["newsletter_title"] = clean_setting_text(
        normalized.get("newsletter_title"),
        DEFAULT_NEWSLETTER_SETTINGS["newsletter_title"],
    )
    normalized["footer_prefix"] = clean_setting_text(
        normalized.get("footer_prefix"),
        DEFAULT_NEWSLETTER_SETTINGS["footer_prefix"],
    )
    if normalized["footer_prefix"] in {"المرصد الثقافي", "تطوير: إدارة المرصد الثقافي"}:
        normalized["footer_prefix"] = "تطوير : إدارة المرصد الثقافي"
    normalized["month_year_override"] = clean_setting_text(normalized.get("month_year_override"), "")
    normalized["issue_number"] = max(1, safe_int(normalized.get("issue_number"), DEFAULT_NEWSLETTER_SETTINGS["issue_number"]))
    return normalized


# Performs the format footer text helper step.
def format_footer_text(*parts):
    return "\t\t|\t\t".join(str(part).strip() for part in parts)


# Performs the newsletter template from settings helper step.
def newsletter_template_from_settings(settings):
    raw_settings = settings if isinstance(settings, dict) else {}
    settings = normalize_newsletter_settings(settings)
    stored_month_year = clean_setting_text(raw_settings.get("month_year"), "")
    month_year = settings["month_year_override"] or stored_month_year or current_arabic_month_year()
    footer_month_year = month_year if month_year.rstrip().endswith(" م") else f"{month_year} م"
    footer_text = format_footer_text(
        settings["footer_prefix"],
        "وكالة الإستراتيجيات والسياسات الثقافية",
        footer_month_year,
        f"الإصدار {issue_label(settings['issue_number'])}",
    )
    return {
        **DEFAULT_TEMPLATE,
        **settings,
        "month_year": month_year,
        "issue_label": issue_label(settings["issue_number"]),
        "footer_text": footer_text,
    }


# Reads load newsletter settings from the current store or request context.
def load_newsletter_settings():
    data = {}
    if NEWSLETTER_SETTINGS_FILE.exists():
        try:
            with open(NEWSLETTER_SETTINGS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    return normalize_newsletter_settings(data)


# Saves save newsletter settings to the configured output or state store.
def save_newsletter_settings(settings):
    normalized = normalize_newsletter_settings(settings)
    NEWSLETTER_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = NEWSLETTER_SETTINGS_FILE.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    safe_replace_json(temp_file, NEWSLETTER_SETTINGS_FILE)
    return normalized


# Performs the increment newsletter issue helper step.
def increment_newsletter_issue():
    settings = load_newsletter_settings()
    settings["issue_number"] = max(1, safe_int(settings.get("issue_number"), 0)) + 1
    return save_newsletter_settings(settings)


# Flattens a level-balanced bank ({"beginner": [...], ...}) into one list,
# in level order. Used as a fallback when a payload only carries the banked
# form (e.g. a hand-edited/manually curated newsletter JSON) instead of the
# flat items/backup_news/courses arrays the admin editor reads directly.
def flatten_level_bank(bank):
    if not isinstance(bank, dict):
        return []
    flattened = []
    for level_key in ("beginner", "intermediate", "advanced"):
        values = bank.get(level_key)
        if isinstance(values, list):
            flattened.extend(item for item in values if isinstance(item, dict))
    return flattened


# Performs the news items from payload helper step.
def news_items_from_payload(raw):
    if not isinstance(raw, dict):
        return []
    merged = []
    for key in ("items", "backup_news"):
        values = raw.get(key, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if is_current_schema_item(item, "news"):
                merged.append(item)
    if not merged:
        # Hit in production 2026-07-12: a manually-edited newsletter JSON
        # only had news_bank (no items/backup_news), so every card editor
        # request against it returned "News item not found" - the id existed
        # in news_bank but load_store() never looked there.
        for item in flatten_level_bank(raw.get("news_bank")):
            if is_current_schema_item(item, "news"):
                merged.append(item)
    return dedupe_store_items(merged)


# Same fallback as news_items_from_payload, for courses: reads the flat
# courses array first, and only flattens courses_bank if that's empty.
def courses_items_from_payload(raw):
    if not isinstance(raw, dict):
        return []
    values = raw.get("courses", [])
    courses = [item for item in values if is_current_schema_item(item, "course")] if isinstance(values, list) else []
    if not courses:
        courses = [
            item for item in flatten_level_bank(raw.get("courses_bank"))
            if is_current_schema_item(item, "course")
        ]
    return courses


# Build the single editable store shape used by generated, imported, and
# manually supplied newsletter JSON. Older manual versions may contain only
# level banks; the helpers above flatten those banks into editable card lists.
def store_from_payload(raw):
    raw = raw if isinstance(raw, dict) else {}
    manual_header = raw.get("newsletter") if isinstance(raw.get("newsletter"), dict) else {}
    if manual_header:
        raw = dict(raw)
        template = dict(raw.get("template") or {}) if isinstance(raw.get("template"), dict) else {}
        if manual_header.get("title"):
            template.setdefault("newsletter_title", manual_header.get("title"))
        if manual_header.get("issue_number") is not None:
            template.setdefault("issue_number", manual_header.get("issue_number"))
        if manual_header.get("date"):
            template.setdefault("month_year", manual_header.get("date"))
        raw["template"] = template
        metadata = dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {}
        metadata.setdefault("source", "manual_newsletter_json")
        for source_key, target_key in (
            ("publisher", "publisher"),
            ("period", "period"),
            ("source_pdf", "source_pdf"),
            ("issue_label", "original_issue_label"),
        ):
            if manual_header.get(source_key) and not metadata.get(target_key):
                metadata[target_key] = manual_header.get(source_key)
        raw["metadata"] = metadata
    raw_news_items = news_items_from_payload(raw)
    raw_template = raw.get("template") if isinstance(raw.get("template"), dict) else None
    store = {
        "items": [normalize_item(i, "news") for i in raw_news_items],
        "movies": [normalize_item(i, "movie") for i in raw.get("movies", []) if is_current_schema_item(i, "movie")],
        "courses": [normalize_item(i, "course") for i in courses_items_from_payload(raw)],
        "template": newsletter_template_from_settings(raw_template or load_newsletter_settings()),
        "feature_mode": raw.get("feature_mode", "course"),
        # Level-balanced newsletter fields are preserved separately from the
        # legacy visible lists so filters can switch views without regenerating.
        "news_bank": raw.get("news_bank") if isinstance(raw.get("news_bank"), dict) else {},
        "courses_bank": raw.get("courses_bank") if isinstance(raw.get("courses_bank"), dict) else {},
        "recommended_view": raw.get("recommended_view") if isinstance(raw.get("recommended_view"), dict) else {},
        "saved_views": raw.get("saved_views") if isinstance(raw.get("saved_views"), dict) else {},
        "default_view": raw.get("default_view") if isinstance(raw.get("default_view"), dict) else {},
        "selected_levels": raw.get("selected_levels") if isinstance(raw.get("selected_levels"), list) else ["all"],
        "news_display_count": 6 if int(raw.get("news_display_count") or 4) == 6 else 4,
        "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    }
    if store["feature_mode"] not in FEATURE_MODES:
        store["feature_mode"] = "course"
    store["items"] = reorder_positions(dedupe_store_items(store["items"]))
    store["movies"] = reorder_positions(dedupe_store_items(store["movies"]))
    store["courses"] = reorder_positions(dedupe_store_items(store["courses"]))
    return store


# Reads load store from the current store or request context.
def load_store():
    raw = {}
    if NEWS_JSON_FILE.exists():
        try:
            with open(NEWS_JSON_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    return store_from_payload(raw)


def save_published_store_memory(store: dict) -> dict:
    """Index every visible published card, including manually entered content."""
    counts = {"news": 0, "course": 0, "movie": 0}
    try:
        from backend.pipeline.filtering.memory import save_news_memory
        from backend.pipeline.filtering.supporting import save_supporting_memory

        def published_cards(section: str, limit: int) -> list[dict]:
            candidates = list(store.get(section) or [])[:limit]
            for mode_views in (store.get("saved_views") or {}).values():
                if not isinstance(mode_views, dict):
                    continue
                for view in mode_views.values():
                    if isinstance(view, dict):
                        candidates.extend(view.get(section) or [])
            output = []
            seen = set()
            expected_type = SECTION_TO_CONTENT_TYPE.get(section, "news")
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or expected_type).strip().lower()
                if item_type != expected_type:
                    continue
                key = str(item.get("url") or "").strip().lower() or str(item.get("title") or "").strip().casefold()
                if not key or key in seen:
                    continue
                seen.add(key)
                output.append(item)
            return output

        news_count = 6 if int(store.get("news_display_count") or 4) == 6 else DISPLAY_COUNTS["items"]
        news_items = published_cards("items", news_count)
        course_items = published_cards("courses", DISPLAY_COUNTS["courses"])
        movie_items = published_cards("movies", DISPLAY_COUNTS["movies"])
        counts["news"] = save_news_memory(news_items, {})
        counts["course"] = save_supporting_memory(course_items, "course") or 0
        counts["movie"] = save_supporting_memory(movie_items, "movie") or 0
        trace(
            "Published semantic memory saved: "
            f"news={counts['news']} courses={counts['course']} movies={counts['movie']}"
        )
    except Exception as exc:
        # Publishing remains durable even if the optional semantic service is
        # temporarily unavailable; the next publish retries the same stable IDs.
        trace(f"Published semantic memory skipped: {exc}")
    return counts


def ensure_published_store():
    """Seed the public newsletter once, before future generations become drafts."""
    if PUBLISHED_NEWS_JSON_FILE.exists() or not NEWS_JSON_FILE.exists():
        return False
    try:
        PUBLISHED_NEWS_JSON_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file = PUBLISHED_NEWS_JSON_FILE.with_suffix(".json.tmp")
        temp_file.write_bytes(NEWS_JSON_FILE.read_bytes())
        safe_replace_json(temp_file, PUBLISHED_NEWS_JSON_FILE)
        save_published_store_memory(load_store_from_file(PUBLISHED_NEWS_JSON_FILE))
        trace(f"Initialized published newsletter: {PUBLISHED_NEWS_JSON_FILE}")
        return True
    except Exception as exc:
        trace(f"Published newsletter initialization failed: {exc}")
        return False


def load_published_store():
    """Load the last explicitly saved newsletter shown to non-admin users."""
    return load_store_from_file(PUBLISHED_NEWS_JSON_FILE)


def publish_current_store():
    """Atomically promote the current admin draft to the public newsletter."""
    if not NEWS_JSON_FILE.exists():
        return False
    PUBLISHED_NEWS_JSON_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = PUBLISHED_NEWS_JSON_FILE.with_suffix(".json.tmp")
    temp_file.write_bytes(NEWS_JSON_FILE.read_bytes())
    safe_replace_json(temp_file, PUBLISHED_NEWS_JSON_FILE)
    save_published_store_memory(load_store_from_file(PUBLISHED_NEWS_JSON_FILE))
    trace(f"Published current newsletter: {PUBLISHED_NEWS_JSON_FILE}")
    return True


# Reads load store from file from the current store or request context.
def load_store_from_file(path):
    raw = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    return store_from_payload(raw)


# Performs the visible items helper step.
def visible_items(store, section):
    return store.get(section, [])[:DISPLAY_COUNTS.get(section, REQUIRED_COUNTS[section])]


# Performs the client visible items helper step.
def client_visible_items(store, section):
    """Return the card pool the UI may show/edit.

    The toolbar can show 4 or 6 news cards from the combined display+backup
    list, so news replacement must not be limited to the legacy 4-card
    default. Courses and movies keep their existing visible limits.
    """
    if section == "items":
        return list(store.get(section, []))
    return visible_items(store, section)


# Performs the previous generation counts helper step.
def previous_generation_counts():
    if not NEWS_PREVIOUS_SNAPSHOT_ENABLED:
        return {section: 0 for section in REQUIRED_COUNTS}
    previous = load_store_from_file(PREVIOUS_NEWS_JSON_FILE)
    return {section: len(visible_items(previous, section)) for section in REQUIRED_COUNTS}


# Saves save previous generation snapshot to the configured output or state store.
def save_previous_generation_snapshot():
    if not NEWS_PREVIOUS_SNAPSHOT_ENABLED:
        trace("Previous newsletter snapshot disabled")
        return False
    if not NEWS_JSON_FILE.exists():
        return False
    try:
        current = load_store()
        if not any(current.get(section) for section in REQUIRED_COUNTS):
            return False
        payload = {
            "items": visible_items(current, "items"),
            "news": visible_items(current, "items"),
            "movies": current.get("movies", []),
            "courses": current.get("courses", []),
            "template": current.get("template", {}),
            "feature_mode": current.get("feature_mode", "course"),
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        PREVIOUS_NEWS_JSON_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file = PREVIOUS_NEWS_JSON_FILE.with_suffix(".json.tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(cleanup_text_fields(payload), f, ensure_ascii=False, indent=2)
        safe_replace_json(temp_file, PREVIOUS_NEWS_JSON_FILE)
        trace(f"Saved previous newsletter snapshot: {PREVIOUS_NEWS_JSON_FILE}")
        return True
    except Exception as exc:
        trace(f"Previous newsletter snapshot skipped: {exc}")
        return False


# Performs the restore previous card at index helper step.
def restore_previous_card_at_index(store, section, index):
    previous = load_store_from_file(PREVIOUS_NEWS_JSON_FILE)
    previous_visible = visible_items(previous, section)
    if index < 0 or index >= len(previous_visible):
        return store, {
            "success": False,
            "index": index,
            "message": "No previous card is available for this position.",
        }
    current_visible = visible_items(store, section)
    candidate = previous_visible[index]
    current_without_target = [
        item for entry_index, item in enumerate(current_visible)
        if entry_index != index
    ]
    if looks_duplicate(candidate, current_without_target):
        return store, {
            "success": False,
            "index": index,
            "message": "Previous card already exists in the visible newsletter.",
        }
    item = update_card_at_index(store, section, index, candidate)
    save_store(store)
    return load_store(), {
        "success": True,
        "index": index,
        "item": item,
        "replacement_source": "previous_generation",
    }


# Saves save store to the configured output or state store.
def save_store(store, *, rebalance_news=False, existing_payload=None):
    existing = existing_payload if isinstance(existing_payload, dict) else {}
    if existing_payload is None and NEWS_JSON_FILE.exists():
        try:
            with open(NEWS_JSON_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    existing = existing if isinstance(existing, dict) else {}
    payload = {
        "items": [],
        "backup_news": [],
        "movies": [],
        "courses": [],
        "template": newsletter_template_from_settings(load_newsletter_settings()),
        "feature_mode": existing.get("feature_mode") or "course",
        "metadata": store.get("metadata") if isinstance(store.get("metadata"), dict) else (existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}),
        # Level-balanced newsletter fields: preserve the full generated bank
        # while normal edit/save operations continue using legacy lists.
        "news_bank": store.get("news_bank") if isinstance(store.get("news_bank"), dict) else existing.get("news_bank", {}),
        "courses_bank": store.get("courses_bank") if isinstance(store.get("courses_bank"), dict) else existing.get("courses_bank", {}),
        "recommended_view": store.get("recommended_view") if isinstance(store.get("recommended_view"), dict) else existing.get("recommended_view", {}),
        "saved_views": store.get("saved_views") if isinstance(store.get("saved_views"), dict) else existing.get("saved_views", {}),
        "default_view": store.get("default_view") if isinstance(store.get("default_view"), dict) else existing.get("default_view", {}),
        "selected_levels": store.get("selected_levels") if isinstance(store.get("selected_levels"), list) else existing.get("selected_levels", ["all"]),
        "news_display_count": 6 if int(store.get("news_display_count") or existing.get("news_display_count") or 4) == 6 else 4,
    }
    for key, default_type in (("items", "news"), ("movies", "movie"), ("courses", "course")):
        if key in store:
            normalized_items = dedupe_store_items([normalize_item(i, default_type) for i in store.get(key, [])])
            if key == "items":
                visible_count = 6 if payload.get("news_display_count") == 6 else DISPLAY_COUNTS.get("items", REQUIRED_COUNTS["items"])
                # Level-balanced newsletter change: when a generated news_bank
                # exists, preserve its recommended first view instead of running
                # the older visible-diversity reorder pass.
                if rebalance_news and not payload.get("news_bank"):
                    normalized_items = order_news_for_visible_diversity(normalized_items, visible_count)
                visible_news = normalized_items[:visible_count]
                hidden_news = [
                    item for item in normalized_items[visible_count:]
                    if not looks_duplicate(item, visible_news)
                    and (
                        not rebalance_news
                        or (
                            is_gpt_accepted_news_item(item)
                            and str(item.get("story_key") or "").strip()
                        )
                    )
                ]
                for index, item in enumerate(visible_news, start=1):
                    item["status"] = "display"
                    item["position"] = index
                hidden_candidates = []
                for hidden_item in dedupe_store_items(hidden_news):
                    hidden_candidates.append(hidden_item)
                    if rebalance_news and len(hidden_candidates) >= NEWS_BACKUP_COUNT:
                        break
                for index, item in enumerate(hidden_candidates, start=1):
                    item["status"] = "backup"
                    item["position"] = index
                combined_payload = []
                for index, item in enumerate(visible_news + hidden_candidates, start=1):
                    item["status"] = "display" if index <= visible_count else "backup"
                    item["position"] = index
                    combined_payload.append(item)
                visible_payload = combined_payload[:visible_count]
                hidden_payload = combined_payload[visible_count:]
                payload[key] = visible_payload
                payload["backup_news"] = hidden_payload
                metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
                metadata["display_count"] = len(visible_payload)
                metadata["backup_count"] = len(hidden_payload)
                metadata["news_total_count"] = len(combined_payload)
                metadata["story_fields_preserved"] = sum(1 for item in combined_payload if item.get("story_key"))
                payload["metadata"] = metadata
                trace(
                    "server_story_fields_preserved "
                    f"{metadata['story_fields_preserved']}/{len(combined_payload)}"
                )
                continue
            payload[key] = reorder_positions(dedupe_store_items(normalized_items))
        else:
            values = existing.get(key, [])
            payload[key] = values if isinstance(values, list) else []

    if "template" in store:
        payload["template"] = newsletter_template_from_settings(store.get("template") or {})

    if "feature_mode" in store:
        payload["feature_mode"] = store.get("feature_mode", "course")

    payload = cleanup_text_fields(payload)
    NEWS_JSON_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = NEWS_JSON_FILE.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    safe_replace_json(temp_file, NEWS_JSON_FILE)


def canonical_newsletter_payload(raw):
    """Convert any supported manual/generated JSON into the news.json shape.

    This is intentionally lossless for editable cards: all cards beyond the
    selected 4/6 display count remain in ``backup_news`` instead of being
    discarded merely because they came from a manual JSON file.
    """
    store = store_from_payload(raw)
    display_count = 6 if store.get("news_display_count") == 6 else 4
    all_news = [dict(item) for item in store.get("items", [])]
    visible_news = all_news[:display_count]
    backup_news = all_news[display_count:]
    for index, item in enumerate(visible_news, start=1):
        item["status"] = "display"
        item["position"] = index
    for index, item in enumerate(backup_news, start=display_count + 1):
        item["status"] = "backup"
        item["position"] = index
    metadata = dict(store.get("metadata") or {})
    metadata.update({
        "display_count": len(visible_news),
        "backup_count": len(backup_news),
        "news_total_count": len(all_news),
    })
    return cleanup_text_fields({
        "items": visible_news,
        "backup_news": backup_news,
        "movies": store.get("movies", []),
        "courses": store.get("courses", []),
        "template": store.get("template", {}),
        "feature_mode": store.get("feature_mode", "course"),
        "metadata": metadata,
        "news_bank": store.get("news_bank", {}),
        "courses_bank": store.get("courses_bank", {}),
        "recommended_view": store.get("recommended_view", {}),
        "saved_views": store.get("saved_views", {}),
        "default_view": store.get("default_view", {}),
        "selected_levels": store.get("selected_levels", ["all"]),
        "news_display_count": display_count,
    })


# Reads load news fetch state server from the current store or request context.
def load_news_fetch_state_server():
    if not NEWS_FETCH_STATE_FILE.exists():
        return {}
    try:
        with open(NEWS_FETCH_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# Saves save news fetch state server to the configured output or state store.
def save_news_fetch_state_server(state):
    NEWS_FETCH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = NEWS_FETCH_STATE_FILE.with_name(
        f"{NEWS_FETCH_STATE_FILE.stem}.{os.getpid()}.{threading.get_ident()}.{int(time.time() * 1000)}.tmp"
    )
    with NEWS_FETCH_STATE_LOCK:
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(state or {}, f, ensure_ascii=False, indent=2)
            safe_replace_json(temp_file, NEWS_FETCH_STATE_FILE)
        finally:
            try:
                temp_file.unlink(missing_ok=True)
            except Exception:
                pass


# Reads find item from the current store or request context.
def find_item(items, item_id):
    return next((i for i in items if i.get("id") == item_id), None)


# Performs the missing sections helper step.
def missing_sections(store):
    return [
        section
        for section, required_count in REQUIRED_COUNTS.items()
        if len(store.get(section, [])) < required_count
    ]


# Performs the missing display sections helper step.
def missing_display_sections(store):
    return [
        section
        for section, display_count in DISPLAY_COUNTS.items()
        if len(store.get(section, [])) < display_count
    ]


# Performs the section feedback helper step.
def section_feedback(section):
    return f"The number of {SECTION_LABELS[section]} is less than required. Fetching more content..."


# Performs the section visible index helper step.
def section_visible_index(store, section, item_id):
    # News can be replaced from the 6-card toolbar view, so resolve the index
    # against the client-visible news pool instead of only the default 4 cards.
    visible = client_visible_items(store, section)
    for index, item in enumerate(visible):
        if item.get("id") == item_id:
            return index
    return -1


# Performs the update card at index helper step.
def update_card_at_index(store, section, index, new_item):
    items = list(store.get(section, []))
    # News replacements may target card 5 or 6 when the toolbar is set to the
    # larger view. Clamp news to the stored display+backup pool, while keeping
    # the old limits for courses and movies.
    client_limit = len(items) if section == "items" and items else DISPLAY_COUNTS.get(section, REQUIRED_COUNTS[section])
    index = max(0, min(index, max(0, client_limit - 1)))
    normalized = normalize_item(new_item, SECTION_TO_CONTENT_TYPE.get(section, "news"))
    if index < len(items):
        items[index] = normalized
    else:
        while len(items) < index:
            items.append(normalize_item({"title": "", "url": "#"}, SECTION_TO_CONTENT_TYPE.get(section, "news")))
        items.insert(index, normalized)
    store[section] = reorder_positions(dedupe_store_items(items))
    return store[section][index] if index < len(store[section]) else normalized


# Reads get feature item from the current store or request context.
def get_feature_item(store):
    section = "movies" if store.get("feature_mode") == "movie" else "courses"
    items = store.get(section, [])
    if items:
        return items[0]
    return {"id": "", "title": "", "text": "", "url": "#", "type": store.get("feature_mode", "course")}


# Performs the update card from client helper step.
def update_card_from_client(store, section, index, item, target_id=None, visible_items=None):
    if section not in SECTION_KEYS:
        return store, {"success": False, "error": "Invalid section"}
    # Accept news indexes from the active toolbar view, including backup cards
    # rendered as cards 5/6. Previously the server rejected those as invalid
    # because it only knew about the legacy 4-card default view.
    client_pool = client_visible_items(store, section)
    client_count = len(client_pool) if section == "items" and client_pool else DISPLAY_COUNTS.get(section, REQUIRED_COUNTS[section])
    requested_index = index
    if requested_index < 0 or requested_index >= client_count:
        return store, {"success": False, "error": "Invalid card index"}

    # A level-filtered UI index is not necessarily the same as the index in the
    # full saved pool. Resolve the actual target by id when the client provides
    # it, while retaining index-only compatibility for older clients.
    target_index = requested_index
    target_id = str(target_id or "").strip()
    if target_id:
        resolved_index = next(
            (i for i, entry in enumerate(client_pool) if str(entry.get("id") or "") == target_id),
            -1,
        )
        if resolved_index >= 0:
            target_index = resolved_index

    normalized = normalize_item(item or {}, SECTION_TO_CONTENT_TYPE.get(section, "news"))
    candidate_id = str(normalized.get("id") or "").strip()
    candidate_url = str(normalized.get("url") or "").strip().lower().rstrip("/")
    candidate_index = next(
        (
            i for i, entry in enumerate(client_pool)
            if i != target_index and (
                (candidate_id and str(entry.get("id") or "").strip() == candidate_id)
                or (
                    candidate_url
                    and str(entry.get("url") or "").strip().lower().rstrip("/") == candidate_url
                )
            )
        ),
        -1,
    )
    if isinstance(visible_items, list):
        current_items = []
        for visible_index, entry in enumerate(visible_items):
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("id") or "").strip()
            entry_url = str(entry.get("url") or "").strip().lower().rstrip("/")
            if target_id and entry_id == target_id:
                continue
            # Older/stale clients may send their optimistic target slot, where
            # the candidate is already rendered. That occurrence is not a
            # duplicate; the same candidate in any other slot still is.
            if visible_index == requested_index and (
                (candidate_id and entry_id == candidate_id)
                or (candidate_url and entry_url == candidate_url)
            ):
                continue
            current_items.append(entry)
    else:
        current_items = [
            entry for i, entry in enumerate(client_pool)
            if i not in {target_index, candidate_index}
        ]
    valid, reason = validate_replacement_candidate(
        normalized,
        section,
        current_items,
        # This endpoint receives a card the UI selected from the already saved
        # JSON banks. Manual versions can contain legitimate course/movie URLs
        # outside the live-fetch allowlist; rejecting those made card flipping
        # fail only for archived newsletters. Duplicate and display-safety
        # checks still run inside validate_replacement_candidate.
        allow_curated_json=True,
    )
    if not valid:
        return store, {"success": False, "error": "Invalid card item", "reject_reason": reason}
    target_item = client_pool[target_index] if target_index < len(client_pool) else None

    # Prepared alternatives often already exist as extra cards in the full
    # pool. Remove that old occurrence first, then move it into the filtered
    # card's slot; otherwise deduplication keeps the old occurrence and makes
    # the visible replacement appear to fail.
    if candidate_index >= 0:
        items = list(store.get(section, []))
        items.pop(candidate_index)
        if candidate_index < target_index:
            target_index -= 1
        store[section] = items

    saved_item = update_card_at_index(store, section, target_index, normalized)
    if target_item and target_item.get("id") != saved_item.get("id"):
        archived_target = normalize_item(dict(target_item), SECTION_TO_CONTENT_TYPE.get(section, "news"))
        archived_target["status"] = "replaced_archive"
        store[section] = reorder_positions(dedupe_store_items(list(store.get(section, [])) + [archived_target]))
    save_store(store)
    return load_store(), {
        "success": True,
        "index": requested_index,
        "stored_index": target_index,
        "item": saved_item,
    }
