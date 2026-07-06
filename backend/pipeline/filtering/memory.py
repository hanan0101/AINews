"""News filtering and semantic memory helpers."""

from __future__ import annotations

import hashlib
import math
import time
from collections import Counter, defaultdict
import re

from backend.config.settings import (
    AI_UPDATES_MEMORY_ENABLED,
    AI_UPDATES_MEMORY_EXACT_LIMIT,
    AI_UPDATES_QDRANT_COLLECTION,
    AI_UPDATES_REJECTED_DUPLICATE_SCORE,
    AI_UPDATES_SAME_RUN_SEMANTIC_SCORE,
    AI_UPDATES_SEMANTIC_DUPLICATE_SCORE,
    AI_UPDATES_SEMANTIC_MAX_CHECK,
    AI_UPDATES_SEMANTIC_MEMORY_ENABLED,
    AI_UPDATES_SINGLE_SEMANTIC_MAX_CHECK,
    AI_UPDATES_EMBED_INPUT_LIMIT,
    memory_url_key,
    normalized_text,
    source_domain,
    utc_now,
)
from backend.pipeline.modeling.openai_client import embed_texts
from backend.pipeline.fetching.sources import (
    candidate_owner_key,
    infer_sector,
    inferred_date_from_text,
    result_is_recent_enough,
)
from backend.pipeline.filtering.editorial_rules import production_news_reject_reason
from backend.vector_db.qdrant_memory import (
    close_qdrant_memory,
    open_qdrant_memory,
    point_struct_class,
    qdrant_type_filter,
    with_qdrant_lock,
)

PointStruct = point_struct_class()

TECH_OR_NEWS_DOMAINS = {
    "techcrunch.com",
    "theverge.com",
    "venturebeat.com",
    "wired.com",
    "zdnet.com",
    "technologyreview.com",
    "arstechnica.com",
    "thenextweb.com",
    "digitaltrends.com",
    "engadget.com",
    "cnet.com",
    "forbes.com",
    "businessinsider.com",
    "yahoo.com",
    "news.google.com",
}

SAME_STORY_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "that", "this", "your", "users", "user",
    "is", "are", "was", "were", "on", "via", "by", "to", "of",
    "new", "now", "available", "launch", "launches", "launched", "release", "released",
    "update", "updates", "feature", "features", "capability", "capabilities", "adds",
    "add", "ai", "artificial", "intelligence", "tool", "tools", "app", "product",
    "official", "announcement", "announces", "rolling", "rollout", "can", "use", "using",
    "inside", "platform", "model", "assistant", "technology",
    "الذكاء", "الاصطناعي", "ذكاء", "اصطناعي", "تحديث", "جديد", "ميزة", "إطلاق",
    "يطلق", "تطلق", "أطلقت", "أعلن", "أعلنت", "المستخدم", "المستخدمين", "داخل",
    "يمكن", "يتيح", "تتيح", "يسمح", "تسمح", "الأداة", "التطبيق", "المنتج",
}

STORY_TOKEN_ALIASES = {
    "citation": "source",
    "citations": "source",
    "cite": "source",
    "cites": "source",
    "cited": "source",
    "sources": "source",
    "conversation": "chat",
    "conversations": "chat",
    "chats": "chat",
    "images": "image",
    "photos": "image",
    "pictures": "image",
    "videos": "video",
    "clips": "video",
    "voices": "voice",
    "audio": "voice",
    "audios": "voice",
    "designs": "design",
    "designing": "design",
    "searches": "search",
    "searching": "search",
    "researching": "research",
    "researches": "research",
}

SAME_STORY_STRONG_TOKENS = {
    "agent",
    "archive",
    "browser",
    "canvas",
    "chat",
    "code",
    "coding",
    "design",
    "editing",
    "image",
    "research",
    "search",
    "source",
    "translation",
    "video",
    "voice",
    "web",
    "workspace",
}

STORY_DISTRIBUTION_WORDS = {
    "github",
    "copilot",
    "aws",
    "bedrock",
    "amazon",
    "vercel",
    "gateway",
    "azure",
    "gcp",
    "googlecloud",
    "google",
    "cloud",
    "huggingface",
    "hugging",
    "face",
    "replicate",
    "openrouter",
    "ollama",
    "cursor",
    "langchain",
}

def item_title_key(item: dict) -> str:
    return normalized_text(item.get("title") or item.get("original_title") or "")

def story_owner_key(item: dict) -> str:
    return (
        item.get("owner_key")
        or candidate_owner_key(
            item,
            url=item.get("url") or item.get("official_url") or "",
            title=item.get("title") or item.get("original_title") or "",
            content=item.get("content") or item.get("summary") or item.get("text") or "",
        )
    )


# Performs the story product key helper step.

def story_product_key(item: dict) -> str:
    """Return the normalized product/tool identity used in the story key."""
    product = (
        item.get("tool_name")
        or item.get("tool")
        or item.get("product_name")
        or item.get("product_or_tool")
        or ""
    )
    words = [
        STORY_TOKEN_ALIASES.get(word, word)
        for word in normalized_text(product).split()
        if word and word not in SAME_STORY_STOPWORDS and word not in STORY_DISTRIBUTION_WORDS
    ]
    return " ".join(words[:4])


# Performs the story title tokens helper step.

def story_title_tokens(item: dict) -> list[str]:
    """Extract only core title tokens; body/domain text is intentionally ignored."""
    text = normalized_text(" ".join(
        str(item.get(key) or "")
        for key in (
            "title",
            "original_title",
            "source_title",
        )
    ))
    raw_tokens = [
        STORY_TOKEN_ALIASES.get(token, token)
        for token in re.findall(r"[\w\u0600-\u06ff]{1,}", text, flags=re.UNICODE)
    ]
    owner_tokens = set(str(story_owner_key(item) or "").replace("-", " ").split())
    product_tokens = set(story_product_key(item).split())

    # Performs the usable helper step.
    def usable(token: str) -> bool:
        return (
            bool(token)
            and token not in owner_tokens
            and token not in product_tokens
            and token not in STORY_DISTRIBUTION_WORDS
            and token not in SAME_STORY_STOPWORDS
            and (len(token) >= 3 or token.isdigit())
        )

    # Prefer the product-adjacent launch phrase: "Claude Fable 5 on AWS"
    # becomes ["fable", "5"] across GitHub/AWS/Amazon/Vercel variants.
    if product_tokens:
        for index, token in enumerate(raw_tokens):
            if token not in product_tokens:
                continue
            core = []
            for next_token in raw_tokens[index + 1:]:
                if next_token in SAME_STORY_STOPWORDS and core:
                    break
                if usable(next_token):
                    core.append(next_token)
                if len(core) >= 4:
                    break
            if core:
                return core

    seen = set()
    fallback = []
    for token in raw_tokens:
        if token in seen or not usable(token):
            continue
        seen.add(token)
        fallback.append(token)
        if len(fallback) >= 6:
            break
    return fallback


# Performs the story tokens helper step.

def story_tokens(item: dict) -> set[str]:
    return set(story_title_tokens(item))


# Performs the same story tokens helper step.

def same_story_tokens(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    overlap = len(left & right)
    if overlap < 4:
        if overlap < 3 or not (left & right & SAME_STORY_STRONG_TOKENS):
            return False
    smaller = min(len(left), len(right)) or 1
    union = len(left | right) or 1
    return (
        overlap >= 5
        or (overlap / smaller) >= 0.65
        or (overlap / union) >= 0.42
        or (overlap >= 3 and (overlap / smaller) >= 0.38 and (left & right & SAME_STORY_STRONG_TOKENS))
    )


# Returns whether items same story is true for the current input.

def items_same_story(left: dict, right: dict) -> bool:
    """Return True when two candidates describe the same update/story."""
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    left_story = str(left.get("story_key") or item_story_key(left) or "").strip()
    right_story = str(right.get("story_key") or item_story_key(right) or "").strip()
    if left_story and right_story and left_story == right_story:
        return True
    return False


# Performs the item story key helper step.

def item_story_key(item: dict) -> str:
    owner = normalized_text(story_owner_key(item))
    product = story_product_key(item)
    words = story_title_tokens(item)
    key_text = f"{owner}|{product}|{' '.join(words)}"
    return hashlib.sha1(key_text.encode("utf-8")).hexdigest()[:24]


# Prepares rank candidates so downstream stages receive consistent data.

def rank_candidates(items: list[dict]) -> list[dict]:
    """Order candidates before memory checks so high-signal items survive caps."""
    """Add lightweight market/source signals without deciding the final story order."""
    owner_counts = Counter(item.get("owner_key") or source_domain(item.get("url") or "") for item in items or [])
    owner_sources = defaultdict(set)
    for item in items or []:
        owner = item.get("owner_key") or source_domain(item.get("url") or "")
        if owner:
            owner_sources[owner].add(source_domain(item.get("url") or ""))

    for item in items or []:
        item["sector"] = item.get("sector") or infer_sector(item.get("title") or "", item.get("content") or "", item.get("bucket") or "")
        item["story_key"] = item_story_key(item)
        item["story_signature"] = item["story_key"]
        owner = item.get("owner_key") or source_domain(item.get("url") or "")
        domain = source_domain(item.get("url") or "")
        item["market_signals"] = {
            "repeat_mentions": int(owner_counts.get(owner, 0)),
            "multi_source": len(owner_sources.get(owner, set())) > 1,
            "source_type": "tech_media" if any(domain == root or domain.endswith(f".{root}") for root in TECH_OR_NEWS_DOMAINS) else "product_or_official_site",
        }
    return list(items or [])


# Performs the news candidate is recent helper step.

def news_candidate_is_recent(item: dict) -> bool:
    """Return false only when a candidate has clear old-date evidence."""
    published = str(
        (item or {}).get("published_date")
        or (item or {}).get("published_raw")
        or (item or {}).get("date")
        or ""
    ).strip()
    if published:
        return result_is_recent_enough(published)
    inferred = inferred_date_from_text(
        " ".join(
            str((item or {}).get(key) or "")
            for key in ("title", "url", "source_url", "official_url")
        )
    )
    if inferred:
        return result_is_recent_enough(inferred)
    text = " ".join(
        str((item or {}).get(key) or "")
        for key in ("title", "url", "source_url", "official_url")
    ).lower()
    current_year = utc_now().year
    for year in range(2018, current_year):
        if f"/{year}/" in text or f" {year} " in f" {text} " or f"-{year}-" in text:
            return False
    return True


# Performs the semantic text helper step.

def semantic_text(item: dict) -> str:
    return " ".join([
        str(item.get("title") or ""),
        str(item.get("original_title") or ""),
        str(item.get("content") or item.get("text") or item.get("summary") or ""),
        str(item.get("company") or item.get("company_name") or item.get("tool_name") or ""),
        str(item.get("sector") or ""),
        str(item.get("bucket") or item.get("source_bucket") or ""),
        source_domain(item.get("url") or item.get("official_url") or ""),
    ])[:AI_UPDATES_EMBED_INPUT_LIMIT]


# Performs the cosine similarity helper step.

def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


# Reads load exact memory from the current store or request context.

def load_exact_memory(diagnostics: dict, *, content_type: str = "news") -> dict:
    """Load URL/title/story keys for fast exact duplicate blocking."""
    entries = {"urls": set(), "titles": set(), "stories": set()}
    diagnostics["memory_enabled"] = bool(AI_UPDATES_MEMORY_ENABLED)
    diagnostics["semantic_memory_enabled"] = bool(AI_UPDATES_SEMANTIC_MEMORY_ENABLED)
    diagnostics["memory_content_type"] = content_type
    if not AI_UPDATES_MEMORY_ENABLED:
        diagnostics["memory_exact_available"] = False
        diagnostics["memory_status"] = "disabled"
        return entries
    started = time.time()

    # Reads exact memory while holding the shared vector database lock.
    def read_memory_entries() -> None:
        qdrant = open_qdrant_memory()
        if qdrant is None:
            diagnostics["memory_exact_available"] = False
            diagnostics["memory_status"] = "qdrant_unavailable"
            return
        try:
            diagnostics["memory_exact_available"] = True
            records, _ = qdrant.scroll(
                collection_name=AI_UPDATES_QDRANT_COLLECTION,
                scroll_filter=qdrant_type_filter(content_type),
                limit=AI_UPDATES_MEMORY_EXACT_LIMIT,
                with_payload=True,
                with_vectors=False,
            )
            for record in records:
                payload = getattr(record, "payload", {}) or {}
                url = memory_url_key(payload.get("url") or "")
                title = normalized_text(payload.get("title") or "")
                story = str(payload.get("story_key") or payload.get("story_signature") or "").strip()
                if url:
                    entries["urls"].add(url)
                if title:
                    entries["titles"].add(title)
                if story:
                    entries["stories"].add(story)
            diagnostics["memory_exact_entries"] = len(entries["urls"]) + len(entries["titles"]) + len(entries["stories"])
            diagnostics["memory_status"] = "exact_loaded"
        except Exception as exc:
            diagnostics["memory_exact_error"] = str(exc)
            diagnostics["memory_status"] = "exact_error"
        finally:
            close_qdrant_memory(qdrant)

    with_qdrant_lock(read_memory_entries)
    diagnostics["memory_exact_seconds"] = round(time.time() - started, 2)
    return entries


# Performs the semantic duplicate helper step.

def semantic_duplicate(qdrant, item: dict, vector: list[float], *, content_type: str = "news") -> tuple[bool, str]:
    """Check Qdrant cosine similarity against previous visible selections."""
    """Check one candidate vector against final and rejected memory records."""
    if qdrant is None or not vector:
        return False, ""
    try:
        result = qdrant.query_points(
            collection_name=AI_UPDATES_QDRANT_COLLECTION,
            query=vector,
            limit=3,
            query_filter=qdrant_type_filter(content_type),
        )
        points = list(getattr(result, "points", []) or [])
    except Exception as exc:
        return False, f"qdrant_query_error:{exc}"
    item_story = str(item.get("story_key") or item_story_key(item))
    item_url = memory_url_key(item.get("url") or "")
    sorted_points = sorted(points, key=lambda p: float(getattr(p, "score", 0) or 0), reverse=True)
    top_score = float(getattr(sorted_points[0], "score", 0) or 0) if sorted_points else 0
    print(
        f"[AI Updates] semantic debug title={str(item.get('title') or '')[:120]!r} "
        f"top_score={top_score:.4f} matches={len(sorted_points)}",
        flush=True,
    )
    for point in sorted_points:
        score = float(getattr(point, "score", 0) or 0)
        payload = getattr(point, "payload", {}) or {}
        stage = str(payload.get("memory_stage") or "")
        threshold = AI_UPDATES_REJECTED_DUPLICATE_SCORE if stage == "rejected" else AI_UPDATES_SEMANTIC_DUPLICATE_SCORE
        if score < threshold:
            continue
        if item_url and item_url == memory_url_key(payload.get("url") or ""):
            return True, "semantic_same_url_memory_duplicate"
        if item_story and item_story == str(payload.get("story_key") or payload.get("story_signature") or ""):
            return True, "semantic_same_story_memory_duplicate"
        return True, "semantic_rejected_memory_duplicate" if stage == "rejected" else "semantic_memory_duplicate"
    return False, ""


# Prepares filter candidates so downstream stages receive consistent data.

def filter_candidates(items: list[dict], diagnostics: dict, *, semantic_limit: int, content_type: str = "news") -> list[dict]:
    """Run exact memory and bounded semantic memory over normalized candidates."""
    """Run exact memory, same-run dedupe, and a capped semantic duplicate pass."""
    if not items:
        return []
    started = time.time()
    if content_type == "news":
        editorial_kept = []
        editorial_rejected = Counter()
        for item in items or []:
            reason = production_news_reject_reason(item)
            if reason:
                editorial_rejected[reason] += 1
                continue
            editorial_kept.append(item)
        diagnostics["editorial_rule_rejected"] = dict(editorial_rejected)
        items = editorial_kept
        if not items:
            diagnostics["memory_filter_seconds"] = round(time.time() - started, 2)
            diagnostics["memory_filter_status"] = "editorial_rules_empty"
            return []
    # News freshness filter: fetchers.py is intentionally permissive and only
    # normalizes raw source hits. Remove clearly old news here before dedupe and
    # semantic memory, while allowing missing-date candidates to reach the model.
    if content_type == "news":
        recent_items = []
        old_skipped = 0
        for item in items or []:
            if news_candidate_is_recent(item):
                recent_items.append(item)
            else:
                old_skipped += 1
        diagnostics["old_news_skipped"] = old_skipped
        items = recent_items
        if not items:
            diagnostics["memory_filter_seconds"] = round(time.time() - started, 2)
            diagnostics["memory_filter_status"] = "freshness_empty"
            return []
    ranked = rank_candidates(items)
    memory = load_exact_memory(diagnostics, content_type=content_type)
    exact_kept = []
    seen_urls = set()
    seen_titles = set()
    seen_stories = set()
    exact_skipped = 0
    same_run_skipped = 0
    same_run_story_skipped = 0
    story_key_skipped = 0
    for item in ranked:
        url = memory_url_key(item.get("url") or "")
        title = item_title_key(item)
        story = item_story_key(item)
        item["story_key"] = story
        item["story_signature"] = story

        # Layer 1: cheap exact dedupe by URL/title, across memory and this run.
        if (url and url in memory["urls"]) or (title and title in memory["titles"]):
            exact_skipped += 1
            continue
        if (url and url in seen_urls) or (title and title in seen_titles):
            exact_skipped += 1
            same_run_skipped += 1
            continue

        # Layer 2: smart story_key dedupe by owner + product + core launch words.
        if story and story in memory["stories"]:
            story_key_skipped += 1
            continue
        if story and story in seen_stories:
            story_key_skipped += 1
            same_run_story_skipped += 1
            continue

        seen_urls.add(url)
        seen_titles.add(title)
        seen_stories.add(story)
        exact_kept.append(item)

    diagnostics["memory_exact_skipped"] = exact_skipped
    diagnostics["story_key_skipped"] = story_key_skipped
    diagnostics["same_run_duplicates_skipped"] = same_run_skipped
    diagnostics["same_run_story_duplicates_skipped"] = same_run_story_skipped
    diagnostics["same_run_semantic_skipped"] = 0
    if not AI_UPDATES_SEMANTIC_MEMORY_ENABLED or not exact_kept:
        diagnostics["semantic_memory_available"] = False if not AI_UPDATES_SEMANTIC_MEMORY_ENABLED else diagnostics.get("memory_exact_available", False)
        diagnostics["semantic_memory_checked"] = 0
        diagnostics["semantic_memory_skipped"] = 0
        diagnostics["memory_filter_seconds"] = round(time.time() - started, 2)
        diagnostics["memory_filter_status"] = "exact_only"
        return exact_kept

    checked = exact_kept[: max(0, semantic_limit)]
    unchecked = exact_kept[len(checked):]
    diagnostics["semantic_memory_requested"] = len(checked)
    vectors = embed_texts([semantic_text(item) for item in checked])
    if len(vectors) != len(checked):
        diagnostics["semantic_memory_checked"] = 0
        diagnostics["semantic_memory_available"] = False
        diagnostics["memory_filter_status"] = "embedding_failed"
        diagnostics["memory_filter_seconds"] = round(time.time() - started, 2)
        return exact_kept

    same_run_semantic_items = []
    same_run_semantic_vectors = []
    same_run_semantic_skipped = 0
    near_threshold = max(0.0, AI_UPDATES_SAME_RUN_SEMANTIC_SCORE - 0.05)
    # Layer 3: same-run semantic dedupe reuses the vectors already computed.
    for item, vector in zip(checked, vectors):
        best_score = 0.0
        best_item = None
        for kept_item, kept_vector in zip(same_run_semantic_items, same_run_semantic_vectors):
            score = cosine_similarity(vector, kept_vector)
            if score > best_score:
                best_score = score
                best_item = kept_item
        if best_item is not None and best_score >= near_threshold:
            print(
                f"[AI Updates] same-run dup title={str(item.get('title') or '')[:120]!r} "
                f"score={best_score:.4f} kept_title={str(best_item.get('title') or '')[:120]!r}",
                flush=True,
            )
        if best_item is not None and best_score >= AI_UPDATES_SAME_RUN_SEMANTIC_SCORE:
            same_run_semantic_skipped += 1
            continue
        same_run_semantic_items.append(item)
        same_run_semantic_vectors.append(vector)
    diagnostics["same_run_semantic_skipped"] = same_run_semantic_skipped

    semantic_kept = []
    semantic_skipped = 0
    # Layer 4: cross-run semantic dedupe against previous Qdrant memory.
    def check_semantic_memory() -> list[dict] | None:
        nonlocal semantic_skipped
        qdrant = open_qdrant_memory()
        if qdrant is None:
            diagnostics["semantic_memory_available"] = False
            diagnostics["memory_filter_status"] = "qdrant_unavailable"
            diagnostics["memory_filter_seconds"] = round(time.time() - started, 2)
            result = rank_candidates(same_run_semantic_items + unchecked)
            diagnostics["semantic_memory_checked"] = 0
            diagnostics["semantic_memory_skipped"] = 0
            print(
                f"[AI Updates] memory filter kept={len(result)}/{len(items)} "
                f"exact={exact_skipped} story_key={story_key_skipped} "
                f"same_run_semantic={same_run_semantic_skipped} semantic=0 "
                f"status={diagnostics['memory_filter_status']} time={diagnostics['memory_filter_seconds']}s",
                flush=True,
            )
            return result
        try:
            diagnostics["semantic_memory_available"] = True
            for item, vector in zip(same_run_semantic_items, same_run_semantic_vectors):
                duplicate, reason = semantic_duplicate(qdrant, item, vector, content_type=content_type)
                if duplicate:
                    semantic_skipped += 1
                    continue
                if reason.startswith("qdrant_query_error"):
                    diagnostics.setdefault("semantic_memory_errors", []).append(reason[:180])
                semantic_kept.append(item)
        finally:
            close_qdrant_memory(qdrant)

        return None

    unavailable_result = with_qdrant_lock(check_semantic_memory)
    if unavailable_result is not None:
        return unavailable_result

    result = rank_candidates(semantic_kept + unchecked)
    diagnostics["semantic_memory_checked"] = len(checked)
    diagnostics["semantic_memory_skipped"] = semantic_skipped
    diagnostics["memory_filter_seconds"] = round(time.time() - started, 2)
    diagnostics["memory_filter_status"] = "semantic_checked"
    print(
        f"[AI Updates] memory filter kept={len(result)}/{len(items)} "
        f"exact={exact_skipped} story_key={story_key_skipped} "
        f"same_run_semantic={same_run_semantic_skipped} semantic={semantic_skipped} "
        f"status={diagnostics['memory_filter_status']} time={diagnostics['memory_filter_seconds']}s",
        flush=True,
    )
    return result


# Prepares filter news candidates so downstream stages receive consistent data.

def filter_news_candidates(candidates: list[dict], diagnostics: dict, *, single: bool = False) -> list[dict]:
    """Filter news candidates before the large-scan shortlist is built."""
    """News-specific wrapper that uses a smaller semantic window for single refill."""
    semantic_limit = AI_UPDATES_SINGLE_SEMANTIC_MAX_CHECK if single else AI_UPDATES_SEMANTIC_MAX_CHECK
    diagnostics["valid_before_memory"] = len(candidates or [])
    filtered = filter_candidates(candidates or [], diagnostics, semantic_limit=semantic_limit, content_type="news")
    diagnostics["unique_results"] = len(filtered)
    return filtered


# Returns whether domain matches is true for the current input.

def save_memory(items: list[dict], content_type: str, diagnostics: dict | None = None) -> int:
    """Persist visible selections into exact and semantic memory."""
    """Persist final selected items in Qdrant so future runs avoid repetition."""
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    diagnostics["memory_save_requested"] = len(items or [])
    diagnostics["memory_save_content_type"] = content_type
    diagnostics["memory_save_enabled"] = bool(AI_UPDATES_MEMORY_ENABLED)
    if not AI_UPDATES_MEMORY_ENABLED or not items or PointStruct is None:
        diagnostics["memory_save_status"] = "disabled_or_empty"
        return 0
    vectors = embed_texts([semantic_text(item) for item in items])
    diagnostics["memory_save_embedding_count"] = len(vectors)
    if len(vectors) != len(items):
        diagnostics["memory_save_error"] = "embedding_failed"
        diagnostics["memory_save_status"] = "embedding_failed"
        return 0
    now = utc_now().isoformat()
    points = []
    for item, vector in zip(items, vectors):
        url = item.get("url") or item.get("official_url") or ""
        title = item.get("title") or item.get("original_title") or ""
        story = item.get("story_key") or item_story_key(item)
        uid = hashlib.md5(f"{content_type}|final|{title}|{url}".encode("utf-8", errors="ignore")).hexdigest()
        points.append(PointStruct(
            id=uid,
            vector=vector,
            payload={
                "title": title,
                "url": url,
                "type": content_type,
                "memory_stage": "final",
                "saved_at": now,
                "story_key": story,
                "story_signature": story,
                "source_domain": source_domain(url),
                "company": item.get("company") or item.get("company_name") or "",
            },
        ))
    # Saves semantic memory while holding the shared vector database lock.
    def write_memory_points() -> int:
        qdrant = open_qdrant_memory()
        if qdrant is None:
            diagnostics["memory_save_error"] = "qdrant_unavailable"
            diagnostics["memory_save_status"] = "qdrant_unavailable"
            print(f"[AI Updates] semantic memory save failed: qdrant_unavailable type={content_type}", flush=True)
            return 0
        try:
            qdrant.upsert(collection_name=AI_UPDATES_QDRANT_COLLECTION, points=points)
            diagnostics["memory_save_status"] = "saved"
            return len(points)
        except Exception as exc:
            diagnostics["memory_save_error"] = str(exc)
            diagnostics["memory_save_status"] = "upsert_failed"
            return 0
        finally:
            close_qdrant_memory(qdrant)

    saved = with_qdrant_lock(write_memory_points)
    diagnostics["memory_save_count"] = saved
    if saved:
        print(f"[AI Updates] saved semantic memory item(s): {saved} type={content_type}", flush=True)
    else:
        print(
            f"[AI Updates] semantic memory save failed: "
            f"{diagnostics.get('memory_save_error') or diagnostics.get('memory_save_status')} type={content_type}",
            flush=True,
        )
    return saved


# Saves save news memory to the configured output or state store.

def save_news_memory(items: list[dict], diagnostics: dict | None = None) -> int:
    return save_memory(items or [], "news", diagnostics)


# Saves save supporting memory to the configured output or state store.

__all__ = [
    "filter_candidates",
    "filter_news_candidates",
    "item_story_key",
    "items_same_story",
    "save_memory",
    "save_news_memory",
    "semantic_text",
    "story_owner_key",
]
