"""Newsletter settings and news.json storage helpers for the HTTP server."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from debugging import trace
from server_items import (
    dedupe_store_items,
    is_current_schema_item,
    looks_duplicate,
    normalize_item,
    order_news_for_visible_diversity,
    safe_replace_json,
    validate_replacement_candidate,
)
from text_cleanup import cleanup_text_fields, repair_mojibake_text

ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT_DIR.parent / "frontend"
NEWS_JSON_FILE = FRONTEND_DIR / "news.json"
PREVIOUS_NEWS_JSON_FILE = FRONTEND_DIR / "news_previous.json"
NEWSLETTER_SETTINGS_FILE = ROOT_DIR / "newsletter_settings.json"
NEWS_FETCH_STATE_FILE = ROOT_DIR / "news_fetch_state.json"
NEWS_SELECTION_AUDIT_FILE = ROOT_DIR / "news_selection_audit.json"

load_dotenv(ROOT_DIR / ".env", override=True)

REQUIRED_COUNTS = {
    "items": 6,
    "movies": 3,
    "courses": 4,
}
DISPLAY_COUNTS = {
    "items": 6,
    "movies": 1,
    "courses": 2,
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
    "newsletter_title": "نشرة \nوالذكاء الاصطناعي",
}
DEFAULT_NEWSLETTER_SETTINGS = {
    "newsletter_title": "نشرة  \nوالذكاء الاصطناعي",
    "footer_prefix": "المرصد الثقافي",
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

NEWS_BACKUP_COUNT = max(0, int(os.getenv("NEWS_BACKUP_COUNT", str(max(0, 12 - DISPLAY_COUNTS["items"]))) or "6"))
NEWS_PREVIOUS_SNAPSHOT_ENABLED = os.getenv("NEWS_PREVIOUS_SNAPSHOT_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
NEWS_FETCH_STATE_LOCK = threading.Lock()


def is_gpt_accepted_news_item(item):
    if not isinstance(item, dict):
        return False
    return bool(item.get("simple_gpt_selected"))


def reorder_positions(items):
    for index, item in enumerate(items, start=1):
        item["position"] = index
    return items


def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def arabic_number_to_words(value, *, ordinal=False):
    try:
        number = int(value or 0)
    except Exception:
        return ""
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


def issue_label(issue_number):
    number = safe_int(issue_number, DEFAULT_NEWSLETTER_SETTINGS["issue_number"])
    return arabic_number_to_words(number, ordinal=True) or str(number)


def clean_setting_text(value, default=""):
    value = repair_mojibake_text(str(value or default or ""))
    return value.strip()


def current_arabic_month_year():
    now = datetime.now()
    month = ARABIC_MONTHS[now.month - 1]
    return f"{month} {now.year}"


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
    normalized["month_year_override"] = clean_setting_text(normalized.get("month_year_override"), "")
    normalized["issue_number"] = max(1, safe_int(normalized.get("issue_number"), DEFAULT_NEWSLETTER_SETTINGS["issue_number"]))
    return normalized


def format_footer_text(*parts):
    return "\t\t|\t\t".join(str(part).strip() for part in parts)


def newsletter_template_from_settings(settings):
    settings = normalize_newsletter_settings(settings)
    month_year = settings["month_year_override"] or current_arabic_month_year()
    footer_text = format_footer_text(
        settings["footer_prefix"],
        month_year,
        f"الإصدار {issue_label(settings['issue_number'])}",
    )
    return {
        **DEFAULT_TEMPLATE,
        **settings,
        "month_year": month_year,
        "issue_label": issue_label(settings["issue_number"]),
        "footer_text": footer_text,
    }


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


def save_newsletter_settings(settings):
    normalized = normalize_newsletter_settings(settings)
    NEWSLETTER_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = NEWSLETTER_SETTINGS_FILE.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    safe_replace_json(temp_file, NEWSLETTER_SETTINGS_FILE)
    return normalized


def increment_newsletter_issue():
    settings = load_newsletter_settings()
    settings["issue_number"] = max(1, safe_int(settings.get("issue_number"), 0)) + 1
    return save_newsletter_settings(settings)


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
    return dedupe_store_items(merged)


def load_store():
    raw = {}
    if NEWS_JSON_FILE.exists():
        try:
            with open(NEWS_JSON_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    raw_news_items = news_items_from_payload(raw)
    store = {
        "items": [normalize_item(i, "news") for i in raw_news_items],
        "movies": [normalize_item(i, "movie") for i in raw.get("movies", []) if is_current_schema_item(i, "movie")],
        "courses": [normalize_item(i, "course") for i in raw.get("courses", []) if is_current_schema_item(i, "course")],
        "template": newsletter_template_from_settings(load_newsletter_settings()),
        "feature_mode": raw.get("feature_mode", "course"),
    }
    if store["feature_mode"] not in FEATURE_MODES:
        store["feature_mode"] = "course"
    store["items"] = reorder_positions(dedupe_store_items(store["items"]))
    store["movies"] = reorder_positions(dedupe_store_items(store["movies"]))
    store["courses"] = reorder_positions(dedupe_store_items(store["courses"]))
    return store


def load_store_from_file(path):
    raw = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw_news_items = news_items_from_payload(raw)
    store = {
        "items": [normalize_item(i, "news") for i in raw_news_items],
        "movies": [normalize_item(i, "movie") for i in raw.get("movies", []) if is_current_schema_item(i, "movie")],
        "courses": [normalize_item(i, "course") for i in raw.get("courses", []) if is_current_schema_item(i, "course")],
        "template": newsletter_template_from_settings(load_newsletter_settings()),
        "feature_mode": raw.get("feature_mode", "course"),
    }
    if store["feature_mode"] not in FEATURE_MODES:
        store["feature_mode"] = "course"
    store["items"] = reorder_positions(dedupe_store_items(store["items"]))
    store["movies"] = reorder_positions(dedupe_store_items(store["movies"]))
    store["courses"] = reorder_positions(dedupe_store_items(store["courses"]))
    return store


def visible_items(store, section):
    return store.get(section, [])[:DISPLAY_COUNTS.get(section, REQUIRED_COUNTS[section])]


def previous_generation_counts():
    if not NEWS_PREVIOUS_SNAPSHOT_ENABLED:
        return {section: 0 for section in REQUIRED_COUNTS}
    previous = load_store_from_file(PREVIOUS_NEWS_JSON_FILE)
    return {section: len(visible_items(previous, section)) for section in REQUIRED_COUNTS}


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


def save_store(store, *, rebalance_news=False):
    existing = {}
    if NEWS_JSON_FILE.exists():
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
        "metadata": existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {},
    }
    for key, default_type in (("items", "news"), ("movies", "movie"), ("courses", "course")):
        if key in store:
            normalized_items = dedupe_store_items([normalize_item(i, default_type) for i in store.get(key, [])])
            if key == "items":
                visible_count = DISPLAY_COUNTS.get("items", REQUIRED_COUNTS["items"])
                if rebalance_news:
                    normalized_items = order_news_for_visible_diversity(normalized_items, visible_count)
                visible_news = normalized_items[:visible_count]
                hidden_news = [
                    item for item in normalized_items[visible_count:]
                    if (
                        is_gpt_accepted_news_item(item)
                        and str(item.get("story_key") or "").strip()
                        and not looks_duplicate(item, visible_news)
                    )
                ]
                for index, item in enumerate(visible_news, start=1):
                    item["status"] = "display"
                    item["position"] = index
                hidden_candidates = []
                for hidden_item in dedupe_store_items(hidden_news):
                    hidden_candidates.append(hidden_item)
                    if len(hidden_candidates) >= NEWS_BACKUP_COUNT:
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
        settings = save_newsletter_settings(store.get("template") or {})
        payload["template"] = newsletter_template_from_settings(settings)

    if "feature_mode" in store:
        payload["feature_mode"] = store.get("feature_mode", "course")

    payload = cleanup_text_fields(payload)
    NEWS_JSON_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = NEWS_JSON_FILE.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    safe_replace_json(temp_file, NEWS_JSON_FILE)


def load_news_fetch_state_server():
    if not NEWS_FETCH_STATE_FILE.exists():
        return {}
    try:
        with open(NEWS_FETCH_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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


def find_item(items, item_id):
    return next((i for i in items if i.get("id") == item_id), None)


def missing_sections(store):
    return [
        section
        for section, required_count in REQUIRED_COUNTS.items()
        if len(store.get(section, [])) < required_count
    ]


def missing_display_sections(store):
    return [
        section
        for section, display_count in DISPLAY_COUNTS.items()
        if len(store.get(section, [])) < display_count
    ]


def section_feedback(section):
    return f"The number of {SECTION_LABELS[section]} is less than required. Fetching more content..."


def section_visible_index(store, section, item_id):
    visible = visible_items(store, section)
    for index, item in enumerate(visible):
        if item.get("id") == item_id:
            return index
    return -1


def update_card_at_index(store, section, index, new_item):
    items = list(store.get(section, []))
    visible_count = DISPLAY_COUNTS.get(section, REQUIRED_COUNTS[section])
    index = max(0, min(index, visible_count - 1))
    normalized = normalize_item(new_item, SECTION_TO_CONTENT_TYPE.get(section, "news"))
    if index < len(items):
        items[index] = normalized
    else:
        while len(items) < index:
            items.append(normalize_item({"title": "", "url": "#"}, SECTION_TO_CONTENT_TYPE.get(section, "news")))
        items.insert(index, normalized)
    store[section] = reorder_positions(dedupe_store_items(items))
    return store[section][index] if index < len(store[section]) else normalized


def get_feature_item(store):
    section = "movies" if store.get("feature_mode") == "movie" else "courses"
    items = store.get(section, [])
    if items:
        return items[0]
    return {"id": "", "title": "", "text": "", "url": "#", "type": store.get("feature_mode", "course")}


def update_card_from_client(store, section, index, item):
    if section not in SECTION_KEYS:
        return store, {"success": False, "error": "Invalid section"}
    visible_count = DISPLAY_COUNTS.get(section, REQUIRED_COUNTS[section])
    if index < 0 or index >= visible_count:
        return store, {"success": False, "error": "Invalid card index"}
    current_items = [
        entry for i, entry in enumerate(visible_items(store, section))
        if i != index
    ]
    normalized = normalize_item(item or {}, SECTION_TO_CONTENT_TYPE.get(section, "news"))
    valid, reason = validate_replacement_candidate(
        normalized,
        section,
        current_items,
        allow_curated_json=(section == "items"),
    )
    if not valid:
        return store, {"success": False, "error": "Invalid card item", "reject_reason": reason}
    target_item = visible_items(store, section)[index] if index < len(visible_items(store, section)) else None
    saved_item = update_card_at_index(store, section, index, normalized)
    if target_item and target_item.get("id") != saved_item.get("id"):
        archived_target = normalize_item(dict(target_item), SECTION_TO_CONTENT_TYPE.get(section, "news"))
        archived_target["status"] = "replaced_archive"
        store[section] = reorder_positions(dedupe_store_items(list(store.get(section, [])) + [archived_target]))
    save_store(store)
    return load_store(), {"success": True, "index": index, "item": saved_item}
