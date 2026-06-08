"""Logo/poster enrichment and final frontend/news.json assembly.

This file converts GPT-selected updates into the exact card schema expected by
the old UI. It also resolves transparent logos, refreshes supporting content,
and writes the diagnostic files used by the progress panel.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import (
    BACKUP_NEWS_COUNT,
    DISPLAY_COUNTS,
    NEWS_FETCH_STATE_FILE,
    NEWS_JSON_FILE,
    NEWS_SECTORS,
    SAVE_NEWS_BACKUP_FROM_SELECTION,
    SUPPORTING_COURSE_FETCH_POOL,
    SUPPORTING_MOVIE_FETCH_POOL,
    clean_text,
    load_json,
    memory_url_key,
    normalized_text,
    safe_write_json,
    source_domain,
    utc_now,
)
from .fetchers import fetch_course_candidates, fetch_movie_candidates
from .filters import filter_supporting_candidates, save_news_memory, save_supporting_memory
from .model import select_supporting_content_cards

# Known domains are used only for logo resolution, not for editorial selection.
# The model still decides which tools deserve coverage.
COMPANY_DOMAINS = {
    "openai": "openai.com",
    "chatgpt": "openai.com",
    "codex": "openai.com",
    "google": "google.com",
    "gemini": "gemini.google.com",
    "microsoft": "microsoft.com",
    "copilot": "copilot.microsoft.com",
    "anthropic": "anthropic.com",
    "claude": "anthropic.com",
    "adobe": "adobe.com",
    "firefly": "adobe.com",
    "canva": "canva.com",
    "figma": "figma.com",
    "runway": "runwayml.com",
    "elevenlabs": "elevenlabs.io",
    "descript": "descript.com",
    "stability ai": "stability.ai",
    "midjourney": "midjourney.com",
    "krea": "krea.ai",
    "ideogram": "ideogram.ai",
    "pika": "pika.art",
    "luma": "lumalabs.ai",
    "perplexity": "perplexity.ai",
    "notion": "notion.so",
    "amazon": "amazon.com",
    "aws": "aws.amazon.com",
    "nvidia": "nvidia.com",
    "zapier": "zapier.com",
    "n8n": "n8n.io",
    "intercom": "intercom.com",
    "wordpress": "wordpress.com",
    "jstor": "jstor.org",
}

NEWS_SOURCE_LOGO_KEYS = {
    "techcrunch",
    "the verge",
    "verge",
    "venturebeat",
    "zdnet",
    "wired",
    "bloomberg",
    "yahoo",
    "ground news",
    "digital trends",
    "tomsguide",
    "xda developers",
    "the decoder",
}

# Preferred transparent/vector logo provider. If unavailable, the card keeps a
# verified fallback candidate list instead of inventing text initials.
SIMPLE_ICON_SLUGS = {
    "openai": "openai",
    "chatgpt": "openai",
    "codex": "openai",
    "google": "google",
    "gemini": "googlegemini",
    "microsoft": "microsoft",
    "copilot": "githubcopilot",
    "anthropic": "anthropic",
    "claude": "claude",
    "adobe": "adobe",
    "firefly": "adobe",
    "canva": "canva",
    "figma": "figma",
    "runway": "runway",
    "elevenlabs": "elevenlabs",
    "descript": "descript",
    "stability ai": "stabilityai",
    "midjourney": "midjourney",
    "krea": "krea",
    "ideogram": "ideogram",
    "pika": "pika",
    "luma": "luma",
    "perplexity": "perplexity",
    "notion": "notion",
    "amazon": "amazon",
    "aws": "amazonaws",
    "nvidia": "nvidia",
    "zapier": "zapier",
    "n8n": "n8n",
    "intercom": "intercom",
    "wordpress": "wordpress",
    "jstor": "jstor",
}

def logo_name_key(value: str = "") -> str:
    key = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    key = re.sub(r"\b(inc|llc|ltd|corp|corporation|company|co)\b", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def domain_root(domain: str = "") -> str:
    clean = source_domain(domain if "://" in str(domain or "") else f"https://{domain}")
    parts = [part for part in clean.split(".") if part and part not in {"www"}]
    if len(parts) >= 3 and parts[-2] in {"co", "com", "net", "org"}:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


def company_matches_domain(company: str = "", domain: str = "") -> bool:
    key = logo_name_key(company)
    root = logo_name_key(domain_root(domain))
    if not key or not root:
        return False
    tokens = [token for token in key.split() if token not in {"ai", "app", "tool", "labs"}]
    return root in {key.replace(" ", ""), key.replace(" ", "-")} or root in tokens


def favicon_for_domain(domain: str = "") -> str:
    clean = re.sub(r"^https?://", "", str(domain or "").lower()).replace("www.", "").split("/")[0]
    if not clean or "." not in clean:
        return ""
    return f"https://www.google.com/s2/favicons?sz=128&domain={clean}"


def domain_label(url: str = "") -> str:
    """Return a readable source/provider label for any URL without whitelisting."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    domain = source_domain(raw if "://" in raw else f"https://{raw}")
    root = domain_root(domain)
    if not root:
        return ""
    return root.replace("-", " ").title()


def favicon_for_url(url: str = "") -> str:
    """Resolve a generic favicon URL from any source URL."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    domain = source_domain(raw if "://" in raw else f"https://{raw}")
    return favicon_for_domain(domain)


def simple_icon_candidates(name: str = "") -> list[str]:
    key = logo_name_key(name)
    mapped = SIMPLE_ICON_SLUGS.get(key, "")
    stems = [mapped, re.sub(r"[^a-z0-9]+", "", key), re.sub(r"[^a-z0-9]+", "-", key).strip("-")]
    urls = []
    for stem in stems:
        if len(stem) < 3:
            continue
        urls.append(f"https://cdn.simpleicons.org/{stem}")
    return list(dict.fromkeys(urls))


def company_logo_candidates(company: str = "", source_url: str = "") -> list[str]:
    """Return verified logo candidates ordered from most brand-specific to fallback."""
    candidates = []

    def add(url: str):
        clean = str(url or "").strip()
        if clean and clean not in candidates:
            candidates.append(clean)

    key = logo_name_key(company)
    mapped_domain = COMPANY_DOMAINS.get(key, "")
    for url in simple_icon_candidates(company):
        add(url)
    if mapped_domain:
        add(f"https://logo.clearbit.com/{mapped_domain}")
        add(f"https://icons.duckduckgo.com/ip3/{mapped_domain}.ico")
        add(favicon_for_domain(mapped_domain))
    source_domain_name = source_domain(source_url)
    if source_domain_name and company_matches_domain(company, source_domain_name):
        add(f"https://logo.clearbit.com/{source_domain_name}")
        add(f"https://icons.duckduckgo.com/ip3/{source_domain_name}.ico")
        add(favicon_for_domain(source_domain_name))
    return candidates


def logo_label_from_card_title(item: dict | None) -> str:
    text = " ".join(
        str((item or {}).get(key) or "")
        for key in ("title", "original_title", "source_title")
    ).strip()
    for match in re.findall(r"\(([A-Za-z][A-Za-z0-9 .+\-&]{1,48})\)", text):
        label = re.sub(r"\s+", " ", match).strip()
        if logo_name_key(label) not in {"ai", "api", "llm", "ml"}:
            return label
    match = re.match(r"\s*([A-Z][A-Za-z0-9.+&-]{2,}(?:\s+[A-Z][A-Za-z0-9.+&-]{2,}){0,2})\b", text)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def card_logo_company(item: dict | None, content_type: str = "news") -> str:
    item = item or {}
    source_url = item.get("source_url") or item.get("url") or ""
    if content_type == "course":
        return (
            clean_text(item.get("provider"))
            or clean_text(item.get("platform"))
            or clean_text(item.get("company"))
            or domain_label(source_url)
            or "AI Course"
        )
    if content_type == "movie":
        return (
            clean_text(item.get("provider"))
            or clean_text(item.get("platform"))
            or clean_text(item.get("company"))
            or clean_text(item.get("source"))
            or domain_label(source_url)
            or "Movie"
        )

    names = (
        item.get("company"),
        item.get("company_name"),
        item.get("main_company"),
        item.get("detected_company"),
        item.get("update_owner"),
        item.get("tool_name"),
        item.get("product_name"),
        item.get("product_or_tool"),
        item.get("provider_name"),
        item.get("provider"),
        item.get("platform"),
    )
    source_key = logo_name_key(item.get("source") or item.get("original_source") or "")
    generic = {"api", "app", "apps", "model", "platform", "feature", "tool", "assistant"}
    for raw_name in names:
        clean = clean_text(raw_name)
        key = logo_name_key(clean)
        if not clean or key in generic or key in NEWS_SOURCE_LOGO_KEYS or "." in clean.lower():
            continue
        if source_key and key == source_key and not item.get("is_official_company_source"):
            continue
        return clean

    label = logo_label_from_card_title(item)
    if label and logo_name_key(label) not in NEWS_SOURCE_LOGO_KEYS:
        return label
    return domain_label(source_url) or "AI"


def enrich_card_visual_identity(item: dict | None, content_type: str = "news") -> dict:
    """Resolve logos for any old-UI card shape through the enrichment pipeline."""
    item = dict(item or {})
    source_url = item.get("source_url") or item.get("url") or ""
    company = card_logo_company(item, content_type)
    candidates = []

    for url in company_logo_candidates(company, source_url):
        if url and url not in candidates:
            candidates.append(url)

    logo = candidates[0] if candidates else ""
    result = {
        "company": company,
        "company_name": item.get("company_name") or company,
        "main_company": item.get("main_company") or company,
        "logo_company": item.get("logo_company") or company,
        "logo": logo,
        "logo_candidates": list(dict.fromkeys(candidates)),
        "logo_resolution_reason": "enrichment_logo_candidate" if logo else "no_verified_company_logo_candidate",
        "logo_detection_reason": "enrichment_logo_candidate" if logo else "no_verified_company_logo_candidate",
        "source_logo": item.get("source_logo") or favicon_for_url(source_url),
    }
    if content_type == "course":
        result.update({
            "provider": item.get("provider") or company,
            "platform": item.get("platform") or company,
            "provider_name": item.get("provider_name") or company,
            "provider_logo": item.get("provider_logo") or logo,
            "source_logo": item.get("source_logo") or logo or favicon_for_url(source_url),
        })
    return result


def stable_update_id(update: dict, source_item: dict | None = None) -> str:
    """Create a stable card id from the selected story identity."""
    source_item = source_item or {}
    raw = "|".join(str(value or "").strip() for value in (update.get("official_url"), update.get("title"), update.get("tool_name"), source_item.get("title")))
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]


def update_company_name(update: dict, source_item: dict | None = None) -> str:
    source_item = source_item or {}
    for value in (update.get("company_name"), update.get("company"), update.get("tool_name")):
        clean = re.sub(r"\s+", " ", str(value or "")).strip()
        key = logo_name_key(clean)
        if clean and key not in {"ai", "app", "tool", "platform", "assistant"} and key not in NEWS_SOURCE_LOGO_KEYS:
            return clean
    domain = source_domain(source_item.get("url") or update.get("official_url") or "")
    return (domain.split(".")[-2].replace("-", " ").title() if "." in domain else domain.title()) or "AI"


def sector_to_track(sector: str = "", bucket: str = "") -> tuple[str, str]:
    """Map English sectors back to the old UI's track/topic fields."""
    text = f"{sector} {bucket}".lower()
    if sector in {"museums", "heritage", "libraries"}:
        return "culture", "culture_research_documents"
    if sector in {"films", "music", "literature", "theater"}:
        return "culture", "culture_language_audio"
    if sector in {"fashion", "visual_arts", "architecture", "cooking"}:
        return "culture", "culture_design_visual"
    if sector in {"mental_health", "physical_health", "ai_education_training_daily_tasks"}:
        return "daily_life", "daily_personal_organization"
    if sector == "work_productivity":
        return "work_life", "work_automation_projects"
    if "daily" in text or "shopping" in text or "travel" in text:
        return "daily_life", "daily_personal_organization"
    if "design" in text or "visual" in text or "fashion" in text:
        return "culture", "culture_design_visual"
    if "workflow" in text or "automation" in text:
        return "work_life", "work_automation_projects"
    return "work_life", "work_documents_reports"


def news_item_from_update(update: dict, index: int) -> dict:
    """Convert one GPT-selected update into the compact UI card schema."""
    source_item = update.get("source_item") if isinstance(update.get("source_item"), dict) else {}
    source_url = update.get("official_url") or source_item.get("url") or "#"
    source_domain_name = source_item.get("source_domain") or source_domain(source_url)
    company = update_company_name(update, source_item)
    logo_candidates = company_logo_candidates(company, source_url)
    logo_for_card = logo_candidates[0] if logo_candidates else ""
    title = clean_text(update.get("title") or update.get("tool_name") or source_item.get("title") or "")
    text = clean_text(update.get("whats_new") or source_item.get("content") or "")
    source_title = clean_text(update.get("source_title") or source_item.get("title") or title)
    sector = update.get("sector") if update.get("sector") in NEWS_SECTORS else source_item.get("sector") or "ai_education_training_daily_tasks"
    field_primary, use_case_bucket = sector_to_track(sector, update.get("source_bucket") or source_item.get("bucket") or "")
    item_id = stable_update_id(update, source_item)
    story_key = hashlib.sha1(f"{company}|{update.get('tool_name')}|{source_title}".lower().encode("utf-8", errors="ignore")).hexdigest()[:24]
    return {
        "id": item_id,
        "title": title,
        "text": text,
        "url": source_url,
        "source": source_domain_name or source_item.get("source") or "Live Search",
        "published": update.get("published_date") or source_item.get("published_date") or source_item.get("published_raw") or "",
        "company": company,
        "logo": logo_for_card,
        "logo_size": 30,
        "logo_candidates": list(dict.fromkeys(str(url or "").strip() for url in logo_candidates if str(url or "").strip()))[:3],
        "tool_name": clean_text(update.get("tool_name") or ""),
        "field_primary": field_primary,
        "use_case_bucket": use_case_bucket,
        "topic_family": use_case_bucket,
        "sector": sector,
        "is_highlight": bool(update.get("is_highlight")),
        "highlight_reason": clean_text(update.get("highlight_reason") or ""),
        "simple_gpt_selected": True,
        "story_key": story_key,
        "type": "news",
        "status": "display" if index <= DISPLAY_COUNTS["items"] else "backup",
        "position": index,
    }


def news_items_from_updates(updates: list[dict]) -> list[dict]:
    """Convert all selected updates and keep only valid UI cards."""
    return [news_item_from_update(update, index) for index, update in enumerate(updates or [], start=1)]


def dedupe_news_items(items: list[dict]) -> tuple[list[dict], int]:
    """Remove literal duplicate cards before writing frontend/news.json."""
    seen_urls = set()
    seen_titles = set()
    seen_stories = set()
    unique = []
    removed = 0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url_key = memory_url_key(item.get("url") or item.get("original_url") or item.get("source_url") or "")
        title_key = normalized_text(item.get("title") or item.get("original_title") or "")
        story_key = str(item.get("story_key") or item.get("story_signature") or "").strip().lower()
        if (url_key and url_key in seen_urls) or (title_key and title_key in seen_titles) or (story_key and story_key in seen_stories):
            removed += 1
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        if story_key:
            seen_stories.add(story_key)
        unique.append(item)

    for index, item in enumerate(unique, start=1):
        item["position"] = index
        item["status"] = "display" if index <= DISPLAY_COUNTS["items"] else "backup"
    return unique, removed


def write_news_fetch_state(performance: dict, items: list[dict]) -> None:
    """Save lightweight fetch diagnostics for the next UI/status read."""
    """Persist timing and diversity diagnostics for the UI progress panel."""
    state = load_json(NEWS_FETCH_STATE_FILE, {})
    visible = items[:DISPLAY_COUNTS["items"]]
    state["last_run_performance"] = {
        "generated_at": utc_now().isoformat(),
        "source": "ai_update_pipeline",
        "performance": performance,
        "diversity": {
            "domain_counts": dict(Counter(item.get("field_primary") or "unknown" for item in visible)),
            "sector_counts": dict(Counter(item.get("sector") or item.get("news_sector") or "unknown" for item in visible)),
            "highlight": next(({
                "title": item.get("title"),
                "sector": item.get("sector") or item.get("news_sector"),
                "reason": item.get("highlight_reason"),
            } for item in visible if item.get("is_highlight")), {}),
            "target_counts": {
                "visible": DISPLAY_COUNTS["items"],
                "backup": len(items[DISPLAY_COUNTS["items"]:]),
                "total": len(items),
            },
        },
    }
    safe_write_json(NEWS_FETCH_STATE_FILE, state)


def save_news_report(report: dict, performance: dict) -> bool:
    """Save the run report that explains what happened during Generate."""
    """Save selected news plus backups to frontend/news.json and Qdrant memory."""
    backup_target = BACKUP_NEWS_COUNT if SAVE_NEWS_BACKUP_FROM_SELECTION else 0
    required_total = DISPLAY_COUNTS["items"] + backup_target
    minimum_save_total = DISPLAY_COUNTS["items"]
    updates = list(report.get("latest_updates") or [])[:required_total]
    items = news_items_from_updates(updates)
    items, removed_duplicates = dedupe_news_items(items)
    if removed_duplicates:
        performance["news_duplicates_removed_before_save"] = removed_duplicates
        print(f"[AI Updates] removed duplicate selected news before save: {removed_duplicates}", flush=True)
    existing = load_json(NEWS_JSON_FILE, {})
    if len(items) < minimum_save_total:
        print(f"[AI Updates] news.json skipped: selected={len(items)} minimum={minimum_save_total}", flush=True)
        return False
    if len(items) < required_total:
        performance["partial_news_save"] = True
        performance["partial_news_selected"] = len(items)
        performance["partial_news_required"] = required_total
        print(
            f"[AI Updates] news.json partial save: selected={len(items)} "
            f"visible={DISPLAY_COUNTS['items']} backup={max(0, len(items) - DISPLAY_COUNTS['items'])} "
            f"target={required_total}",
            flush=True,
        )
    hidden = items[DISPLAY_COUNTS["items"]:]
    metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
    metadata.update({
        "source": "ai_update_pipeline",
        "generated_at": utc_now().isoformat(),
        "display_count": DISPLAY_COUNTS["items"],
        "backup_count": len(hidden),
        "backup_from_large_scan_enabled": bool(SAVE_NEWS_BACKUP_FROM_SELECTION),
        "news_total_count": len(items),
        "ai_updates_performance": performance,
    })
    payload = {
        "items": items[:DISPLAY_COUNTS["items"]],
        "backup_news": hidden,
        "movies": existing.get("movies", []) if isinstance(existing.get("movies", []), list) else [],
        "courses": existing.get("courses", []) if isinstance(existing.get("courses", []), list) else [],
        "feature_mode": existing.get("feature_mode") or "course",
        "template": existing.get("template") or {},
        "metadata": {
            "source": metadata.get("source"),
            "generated_at": metadata.get("generated_at"),
            "display_count": metadata.get("display_count"),
            "backup_count": metadata.get("backup_count"),
            "backup_from_large_scan_enabled": metadata.get("backup_from_large_scan_enabled"),
            "news_total_count": metadata.get("news_total_count"),
        },
    }
    safe_write_json(NEWS_JSON_FILE, payload)
    performance["semantic_memory_saved"] = save_news_memory(items, performance)
    write_news_fetch_state(performance, items)
    print(f"[AI Updates] Saved news.json visible={DISPLAY_COUNTS['items']} backup={len(hidden)} total={len(items)}", flush=True)
    return True


def build_supporting_content(pre_run_payload: dict | None = None) -> dict:
    """Fetch, filter, and rewrite course/movie cards without saving news.json."""
    """Build course/movie cards without writing frontend/news.json.

    This lets the main pipeline prepare supporting content in parallel with
    news fetching/GPT selection, then apply the cards only after the current
    news run has been safely saved.
    """
    started = time.time()
    result = {
        "enabled": True,
        "courses": 0,
        "movies": 0,
        "seconds": 0.0,
        "kept_existing": [],
        "_cards": {"courses": [], "movies": []},
    }

    course_limit = max(DISPLAY_COUNTS["courses"], 1) + 3
    movie_limit = max(DISPLAY_COUNTS["movies"], 1) + 3

    def build_one(section: str) -> dict:
        section_started = time.time()
        fetch_seconds = 0.0
        filter_seconds = 0.0
        gpt_seconds = 0.0
        if section == "courses":
            content_type = "course"
            display_count = DISPLAY_COUNTS["courses"]
            target_limit = course_limit
            fetch_started = time.time()
            candidates = fetch_course_candidates(
                max_results=max(SUPPORTING_COURSE_FETCH_POOL, target_limit + 3)
            )
            fetch_seconds = time.time() - fetch_started
        else:
            content_type = "movie"
            display_count = DISPLAY_COUNTS["movies"]
            target_limit = movie_limit
            fetch_started = time.time()
            candidates = fetch_movie_candidates(
                target_count=max(SUPPORTING_MOVIE_FETCH_POOL, target_limit + 8)
            )
            fetch_seconds = time.time() - fetch_started
        visible_items = []
        if isinstance(pre_run_payload, dict) and isinstance(pre_run_payload.get(section), list):
            visible_items = pre_run_payload.get(section) or []
        filter_started = time.time()
        filtered_cards = filter_supporting_candidates(
            candidates,
            content_type,
            target_limit,
            visible_items=visible_items,
        )
        filter_seconds = time.time() - filter_started
        gpt_started = time.time()
        gpt_cards = select_supporting_content_cards(
            filtered_cards,
            content_type,
            min(target_limit, len(filtered_cards) or target_limit),
            visible_count=display_count,
        )
        gpt_seconds = time.time() - gpt_started
        selector = "supporting_prompt_gpt"
        timings = {
            "fetch_seconds": round(fetch_seconds, 2),
            "filter_seconds": round(filter_seconds, 2),
            "gpt_seconds": round(gpt_seconds, 2),
            "total_seconds": round(time.time() - section_started, 2),
        }
        if len(gpt_cards) >= display_count:
            return {
                "section": section,
                "cards": gpt_cards,
                "selector": selector,
                "prompt_selected": len(gpt_cards),
                "filtered_candidates": len(filtered_cards),
                "raw_candidates": len(candidates or []),
                "timings": timings,
            }
        return {
            "section": section,
            "cards": [],
            "selector": "supporting_prompt_no_selection",
            "prompt_selected": len(gpt_cards or []),
            "filtered_candidates": len(filtered_cards),
            "raw_candidates": len(candidates or []),
            "timings": timings,
            "kept_existing": {
                "section": section,
                "reason": f"not_enough_cards:{len(gpt_cards or [])}/{display_count}",
            },
        }

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(build_one, "courses"), executor.submit(build_one, "movies")]
        for future in as_completed(futures):
            try:
                section_result = future.result()
            except Exception as exc:
                result["kept_existing"].append({"section": "supporting", "reason": f"build_failed:{exc}"})
                continue
            section = section_result.get("section")
            cards = section_result.get("cards") or []
            result["_cards"][section] = cards
            result[section] = len(cards)
            result[f"{section[:-1]}_selector"] = section_result.get("selector")
            result[f"{section[:-1]}_prompt_selected"] = section_result.get("prompt_selected", 0)
            result[f"{section[:-1]}_raw_candidates"] = section_result.get("raw_candidates", 0)
            result[f"{section[:-1]}_filtered_candidates"] = section_result.get("filtered_candidates", 0)
            timings = section_result.get("timings") if isinstance(section_result.get("timings"), dict) else {}
            result[f"{section}_fetch_seconds"] = timings.get("fetch_seconds", 0.0)
            result[f"{section}_filter_seconds"] = timings.get("filter_seconds", 0.0)
            result[f"{section}_gpt_seconds"] = timings.get("gpt_seconds", 0.0)
            result[f"{section}_total_seconds"] = timings.get("total_seconds", 0.0)
            if section_result.get("kept_existing"):
                result["kept_existing"].append(section_result["kept_existing"])

    result["seconds"] = round(time.time() - started, 2)
    return result


def apply_supporting_content(built: dict, pre_run_payload: dict | None = None) -> dict:
    """Merge refreshed courses/movies into the current newsletter payload."""
    """Apply prebuilt supporting cards to the current JSON without touching news."""
    started = time.time()
    result = dict(built or {})
    result.setdefault("enabled", True)
    result.setdefault("courses", 0)
    result.setdefault("movies", 0)
    result.setdefault("kept_existing", [])
    cards_by_section = result.get("_cards") if isinstance(result.get("_cards"), dict) else {}

    payload = load_json(NEWS_JSON_FILE, {})
    changed = False
    course_cards = cards_by_section.get("courses") if isinstance(cards_by_section.get("courses"), list) else []
    movie_cards = cards_by_section.get("movies") if isinstance(cards_by_section.get("movies"), list) else []

    if len(course_cards) >= DISPLAY_COUNTS["courses"]:
        payload["courses"] = course_cards
        result["courses"] = len(course_cards)
        visible_course_cards = course_cards[:DISPLAY_COUNTS["courses"]]
        save_supporting_memory(visible_course_cards, "course")
        result["course_memory_saved_visible_only"] = len(visible_course_cards)
        result["course_source"] = "ai_update_pipeline_exa_tavily"
        changed = True
    else:
        if not any(item.get("section") == "courses" for item in result["kept_existing"] if isinstance(item, dict)):
            result["kept_existing"].append({"section": "courses", "reason": f"not_enough_cards:{len(course_cards)}/{DISPLAY_COUNTS['courses']}"})

    if len(movie_cards) >= DISPLAY_COUNTS["movies"]:
        payload["movies"] = movie_cards
        result["movies"] = len(movie_cards)
        visible_movie_cards = movie_cards[:DISPLAY_COUNTS["movies"]]
        save_supporting_memory(visible_movie_cards, "movie")
        result["movie_memory_saved_visible_only"] = len(visible_movie_cards)
        result["movie_source"] = "ai_update_pipeline_tmdb"
        changed = True
    else:
        if not any(item.get("section") == "movies" for item in result["kept_existing"] if isinstance(item, dict)):
            result["kept_existing"].append({"section": "movies", "reason": f"not_enough_cards:{len(movie_cards)}/{DISPLAY_COUNTS['movies']}"})

    if changed:
        safe_write_json(NEWS_JSON_FILE, payload)
    result["apply_seconds"] = round(time.time() - started, 2)
    result.pop("_cards", None)
    return result


def refresh_supporting_content(pre_run_payload: dict | None = None) -> dict:
    """Refresh courses and movies through the modular AI update pipeline."""
    built = build_supporting_content(pre_run_payload)
    return apply_supporting_content(built, pre_run_payload)
