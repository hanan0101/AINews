# This file is part of the AI newsletter system.
"""Model selection for supporting course and film cards."""

from __future__ import annotations

from backend.pipeline.modeling.selection import *  # Shared model helpers.

class SupportingCard(BaseModel):
    """Structured schema GPT must fill for course and movie support cards."""
    title: str = Field(description="Final display title from the provided source record")
    text: str = Field(description="Arabic factual summary based only on the provided source record")
    url: str = Field(description="Source URL from the provided candidate list")
    type: str = Field(description="course or movie")
    source: str = Field(default="", description="Source/platform name")
    provider: str = Field(default="", description="Course provider if available")
    platform: str = Field(default="", description="Course platform if available")
    level: str = Field(default="", description="Beginner, Intermediate, or Advanced for courses")
    duration: str | None = Field(default=None, description="Course duration if available")
    certificate: str = Field(default="", description="Course certificate information")
    poster: str = Field(default="", description="Movie poster URL")
    audience: str = Field(default="", description="employee, student, developer, general_public, or unclear for courses")
    employee_fit_score: int = Field(default=0, description="0-5 score for employee/work relevance")
    is_work_relevant: bool = Field(default=False, description="True when the course skill is useful in work")
    reason: str = Field(default="", description="Short audience-fit reason")
    newsletter_angle: str = Field(default="", description="Workplace newsletter angle for the course")


class SupportingReport(BaseModel):
    articles: list[SupportingCard] = Field(default=[])


# Performs the failure report helper step.

def compact_supporting_candidate(item: dict, content_type: str, index: int) -> dict:
    """Keep course/movie prompt input small and source-bound."""
    return {
        "article_index": index,
        "visible_pair_priority": item.get("_visible_pair_priority") or "",
        "title": clean_text(item.get("title") or "")[:220],
        "overview": clean_text(item.get("content") or item.get("summary") or item.get("text") or item.get("overview") or "")[:900],
        "url": item.get("url") or item.get("source_url") or "",
        "source": item.get("source") or item.get("platform") or item.get("provider") or source_domain(item.get("url") or ""),
        "platform": item.get("platform") or "",
        "provider": item.get("provider") or "",
        "level": item.get("level") or "",
        "duration": item.get("duration") or "",
        "certificate": item.get("certificate") or "",
        "date": item.get("published_date") or item.get("published") or item.get("date") or "",
        "source_query": item.get("source_query") or "",
        "workforce_signal": bool(item.get("workforce_signal")),
        "audience_review_required": bool(item.get("audience_review_required")),
        "audience_review_reason": item.get("audience_review_reason") or "",
        "poster": item.get("poster") or item.get("image") or "",
        "type": content_type,
    }



# Builds merge supporting cards for the next pipeline or API step.
def merge_supporting_cards(
    articles: list[dict],
    source_pool: list[dict],
    content_type: str,
    target_count: int,
) -> list[dict]:
    """Attach GPT writing to the original source records and drop anything not source-bound."""
    source_by_url = {
        result_url_key(item.get("url") or item.get("source_url") or ""): item
        for item in source_pool or []
        if item.get("url") or item.get("source_url")
    }
    selected = []
    seen_urls = set()


    for article in articles or []:
        url_key = result_url_key(article.get("url") or "")
        source_item = source_by_url.get(url_key)
        if not source_item or url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        merged = dict(source_item)
        title = clean_text(article.get("title") or "")
        if content_type != "course" and not title:
            title = clean_text(source_item.get("title") or "")
        article_text = clean_text(article.get("text") or "")
        text = article_text
        if content_type != "course" and not text:
            text = clean_text(source_item.get("text") or source_item.get("summary") or "")
        if not title or not text:
            continue
        merged["title"] = title
        merged["text"] = text
        merged["summary"] = text
        merged["url"] = source_item.get("url") or article.get("url") or ""
        merged["source_url"] = merged["url"]
        merged["type"] = content_type
        merged["source"] = clean_text(article.get("source") or source_item.get("source") or source_domain(merged["url"]))
        if content_type == "course":
            audience = clean_text(article.get("audience") or source_item.get("audience") or "").lower()
            try:
                employee_fit_score = int(article.get("employee_fit_score") or source_item.get("employee_fit_score") or 0)
            except Exception:
                employee_fit_score = 0
            is_work_relevant = bool(article.get("is_work_relevant") or source_item.get("is_work_relevant"))
            if audience in {"student", "developer"} or employee_fit_score < 3 or not is_work_relevant:
                continue
            # Level-balanced newsletter change: preserve only an explicit
            # platform/model level. Do not infer or default the course level.
            level = clean_text(article.get("level") or source_item.get("level") or "")
            if level not in {"Beginner", "Intermediate", "Advanced"}:
                level = ""
            merged["level"] = level
            merged["level_source"] = "platform" if source_item.get("level") else ("model" if article.get("level") else "missing")
            merged["platform"] = clean_text(article.get("platform") or source_item.get("platform") or merged["source"])
            merged["provider"] = clean_text(article.get("provider") or source_item.get("provider") or merged["platform"])
            merged["certificate"] = clean_text(article.get("certificate") or source_item.get("certificate") or "not specified")
            merged["duration"] = article.get("duration") or source_item.get("duration")
            merged["audience"] = audience
            merged["employee_fit_score"] = employee_fit_score
            merged["is_work_relevant"] = is_work_relevant
            merged["reason"] = clean_text(article.get("reason") or source_item.get("reason") or "")
            merged["newsletter_angle"] = clean_text(article.get("newsletter_angle") or source_item.get("newsletter_angle") or "")
        if content_type == "movie":
            # Film selection is independent from the news/course level filter.
            for field in ("level", "course_level", "difficulty", "level_source"):
                merged.pop(field, None)
            poster = article.get("poster") or source_item.get("poster") or source_item.get("image") or ""
            if not poster:
                continue
            merged["poster"] = poster
        if not merged.get("id"):
            id_seed = f"{title}|{merged.get('url') or ''}"
            merged["id"] = f"{content_type}-{hashlib.sha1(id_seed.encode('utf-8', errors='ignore')).hexdigest()[:16]}"
        selected.append(merged)
        if len(selected) >= target_count:
            break
    return selected


# Performs the course topic key helper step.
def course_topic_key(item: dict) -> str:
    """Classify course topics just enough to avoid two identical visible cards."""
    text = normalized_text(
        " ".join(str(item.get(key) or "") for key in ("title", "text", "summary", "content"))
    )
    topic_terms = [
        ("prompting", ("prompt", "prompting")),
        ("generative_ai", ("generative", "chatgpt", "llm", "model")),
        ("productivity", ("productivity", "work", "office", "copilot")),
        ("creative", ("creative", "design", "image", "video", "canva", "adobe")),
        ("data", ("data", "analytics", "analysis")),
        ("responsible_ai", ("responsible", "ethics", "safety")),
        ("basics", ("beginner", "basics", "fundamentals", "introduction", "intro")),
    ]
    for topic, terms in topic_terms:
        if any(term in text for term in terms):
            return topic
    words = [word for word in text.split() if len(word) > 3]
    return words[0] if words else "general"


# Performs the course platform key helper step.
def course_platform_key(item: dict) -> str:
    return normalized_text(item.get("platform") or item.get("provider") or item.get("source") or source_domain(item.get("url") or ""))


def is_major_course_platform(item: dict) -> bool:
    return course_platform_key(item) in COURSE_MAJOR_PLATFORM_KEYS


# Performs the course item key helper step.
def course_item_key(item: dict) -> str:
    return normalized_text(item.get("url") or item.get("source_url") or item.get("title") or str(id(item)))


def course_platform_label(item: dict) -> str:
    return clean_text(item.get("platform") or item.get("provider") or item.get("source") or source_domain(item.get("url") or ""))


def course_level_label(item: dict) -> str:
    level = normalize_level(item.get("level") or "")
    return {
        "beginner": "Beginner",
        "intermediate": "Intermediate",
        "advanced": "Advanced",
    }.get(normalized_text(level), level or "Unspecified")


def course_platform_level_pair(item: dict) -> tuple[str, str]:
    return (normalized_text(course_platform_label(item)), normalized_text(course_level_label(item)))


def save_last_course_platforms(courses: list[dict]) -> None:
    platforms = []
    seen = set()
    for item in courses or []:
        platform = course_platform_label(item)
        key = normalized_text(platform)
        if not platform or key in seen:
            continue
        seen.add(key)
        platforms.append(platform)
    state = load_json(NEWS_FETCH_STATE_FILE, {})
    state["last_course_platforms"] = platforms
    state["last_course_platforms_updated_at"] = utc_now().isoformat()
    safe_write_json(NEWS_FETCH_STATE_FILE, state)
    print(f"[AI Updates] Final platforms saved: {', '.join(platforms) if platforms else 'none'}", flush=True)
    log_event("courses.final_platforms_saved", platforms=platforms)


def enforce_course_platform_level_pairs(selected: list[dict], source_pool: list[dict], target_count: int) -> list[dict]:
    output = []
    used_pairs = set()
    used_items = set()
    duplicates = []
    for item in selected or []:
        pair = course_platform_level_pair(item)
        key = course_item_key(item)
        if pair[0] and pair in used_pairs:
            duplicates.append(item)
            continue
        output.append(item)
        used_pairs.add(pair)
        used_items.add(key)

    replacement_pool = [item for item in source_pool or [] if isinstance(item, dict)]
    for duplicate in duplicates:
        replacement = None
        for candidate in replacement_pool:
            key = course_item_key(candidate)
            pair = course_platform_level_pair(candidate)
            if key in used_items or not pair[0] or pair in used_pairs:
                continue
            replacement = dict(candidate)
            break
        if replacement is None:
            continue
        old_platform = course_platform_label(duplicate)
        old_level = course_level_label(duplicate)
        new_platform = course_platform_label(replacement)
        new_level = course_level_label(replacement)
        print(
            f"[AI Updates] Replaced duplicate ({old_platform}, {old_level}) with ({new_platform}, {new_level})",
            flush=True,
        )
        log_event(
            "courses.platform_level_duplicate_replaced",
            old_platform=old_platform,
            old_level=old_level,
            new_platform=new_platform,
            new_level=new_level,
        )
        output.append(replacement)
        used_pairs.add(course_platform_level_pair(replacement))
        used_items.add(course_item_key(replacement))
        if len(output) >= target_count:
            break

    for candidate in replacement_pool:
        if len(output) >= target_count:
            break
        key = course_item_key(candidate)
        pair = course_platform_level_pair(candidate)
        if key in used_items or not pair[0] or pair in used_pairs:
            continue
        output.append(dict(candidate))
        used_items.add(key)
        used_pairs.add(pair)

    return output[:target_count]


def enforce_course_alternative_platforms(selected: list[dict], source_pool: list[dict], target_count: int) -> list[dict]:
    alternative_pool = [
        dict(item)
        for item in source_pool or []
        if isinstance(item, dict) and not is_major_course_platform(item)
    ]
    if not alternative_pool:
        return selected[:target_count]

    used_items = {course_item_key(item) for item in selected or [] if not is_major_course_platform(item)}
    used_pairs = {course_platform_level_pair(item) for item in selected or [] if not is_major_course_platform(item)}
    output = []
    postponed_major = []

    for item in selected or []:
        if is_major_course_platform(item):
            postponed_major.append(item)
            continue
        output.append(item)

    def replacement_for(major_item: dict) -> dict | None:
        major_level = course_level_label(major_item)
        for same_level_only in (True, False):
            for candidate in alternative_pool:
                key = course_item_key(candidate)
                pair = course_platform_level_pair(candidate)
                if key in used_items or not pair[0] or pair in used_pairs:
                    continue
                if same_level_only and course_level_label(candidate) != major_level:
                    continue
                return dict(candidate)
        return None

    for major_item in postponed_major:
        replacement = replacement_for(major_item)
        if replacement is None:
            output.append(major_item)
            continue
        old_platform = course_platform_label(major_item)
        old_level = course_level_label(major_item)
        new_platform = course_platform_label(replacement)
        new_level = course_level_label(replacement)
        print(
            f"[AI Updates] Replaced major course platform ({old_platform}, {old_level}) with ({new_platform}, {new_level})",
            flush=True,
        )
        log_event(
            "courses.major_platform_replaced",
            old_platform=old_platform,
            old_level=old_level,
            new_platform=new_platform,
            new_level=new_level,
        )
        output.append(replacement)
        used_items.add(course_item_key(replacement))
        used_pairs.add(course_platform_level_pair(replacement))

    for candidate in alternative_pool:
        if len(output) >= target_count:
            break
        key = course_item_key(candidate)
        pair = course_platform_level_pair(candidate)
        if key in used_items or pair in used_pairs:
            continue
        output.append(dict(candidate))
        used_items.add(key)
        used_pairs.add(pair)

    return output[:target_count]


# Performs the prepare course prompt pool helper step.
def prepare_course_prompt_pool(items: list[dict], visible_count: int) -> list[dict]:
    """Put a diverse visible course pair first so GPT sees the intended choice."""
    items = [dict(item) for item in items or []]
    if visible_count < 2 or len(items) < 2:
        return items

    indexed = list(enumerate(items))
    beginners = [(idx, item) for idx, item in indexed if item.get("level") == "Beginner"]
    intermediates = [(idx, item) for idx, item in indexed if item.get("level") == "Intermediate"]

    # Performs the pair rank helper step.
    def pair_rank(first: tuple[int, dict], second: tuple[int, dict]) -> tuple[int, int, int, int]:
        first_idx, first_item = first
        second_idx, second_item = second
        platform_diff = int(bool(course_platform_key(first_item)) and course_platform_key(first_item) != course_platform_key(second_item))
        topic_diff = int(bool(course_topic_key(first_item)) and course_topic_key(first_item) != course_topic_key(second_item))
        original_order = -(first_idx + second_idx)
        return (platform_diff, topic_diff, original_order)

    chosen: list[tuple[int, dict]] = []
    if beginners and intermediates:
        chosen = list(max(
            ((beginner, intermediate) for beginner in beginners for intermediate in intermediates),
            key=lambda pair: pair_rank(pair[0], pair[1]),
        ))

    if not chosen:
        best_pair = None
        best_rank = None
        for first_pos, first_item in indexed:
            for second_pos, second_item in indexed:
                if second_pos == first_pos:
                    continue
                rank = pair_rank((first_pos, first_item), (second_pos, second_item))
                if best_rank is None or rank > best_rank:
                    best_rank = rank
                    best_pair = [(first_pos, first_item), (second_pos, second_item)]
        chosen = best_pair or []

    if not chosen:
        return items

    chosen_ids = {id(item) for _, item in chosen}
    ordered = []
    for priority, (_, item) in enumerate(chosen[:2], start=1):
        copy_item = dict(item)
        copy_item["_visible_pair_priority"] = priority
        ordered.append(copy_item)

    ordered.extend(item for item in items if id(item) not in chosen_ids)
    return ordered


# Prepares balance course levels so downstream stages receive consistent data.
def balance_course_levels(items: list[dict], target_count: int) -> list[dict]:
    """Build the course bank by level while preserving visible diversity.

    For the new level-balanced newsletter, a full course bank should contain
    2 Beginner, 2 Intermediate, and 2 Advanced courses when target_count is 6.
    Smaller requests keep the old visible behavior: Beginner + Intermediate
    first, then diverse extras.
    """
    items = list(items or [])
    if target_count < 2:
        return items[:target_count]

    if target_count >= 6:
        output = []
        seen_keys = set()

        # Performs the add for level helper step.
        def add_for_level(level: str, count: int) -> None:
            topic_counts = Counter()
            fallback = []
            for item in items:
                if item.get("level") != level or course_item_key(item) in seen_keys:
                    continue
                topic = course_topic_key(item)
                if topic_counts[topic] >= 2:
                    fallback.append(item)
                    continue
                output.append(item)
                seen_keys.add(course_item_key(item))
                topic_counts[topic] += 1
                if sum(1 for selected in output if selected.get("level") == level) >= count:
                    return
            for item in fallback:
                if sum(1 for selected in output if selected.get("level") == level) >= count:
                    return
                if course_item_key(item) in seen_keys:
                    continue
                output.append(item)
                seen_keys.add(course_item_key(item))

        for level in ("Beginner", "Intermediate", "Advanced"):
            add_for_level(level, 2)

        for item in items:
            if len(output) >= target_count:
                break
            if course_item_key(item) in seen_keys:
                continue
            copied = dict(item)
            copied["level_bank_fallback"] = True
            output.append(copied)
            seen_keys.add(course_item_key(item))
        print(
            f"[AI Updates] course bank levels {dict(Counter(item.get('level') or 'unknown' for item in output[:target_count]))}",
            flush=True,
        )
        return output[:target_count]

    output = []
    seen_keys = set()
    used_platforms = set()
    used_topics = set()

    # Performs the add helper step.
    def add(item: dict | None) -> None:
        key = course_item_key(item or {})
        if item is None or (key and key in seen_keys):
            return
        output.append(item)
        if key:
            seen_keys.add(key)
        platform = course_platform_key(item)
        topic = course_topic_key(item)
        if platform:
            used_platforms.add(platform)
        if topic:
            used_topics.add(topic)

    beginner = next((item for item in items if item.get("level") == "Beginner"), None)
    add(beginner)

    # Performs the different from visible helper step.
    def different_from_visible(item: dict) -> bool:
        platform = course_platform_key(item)
        topic = course_topic_key(item)
        return bool(platform and platform not in used_platforms and topic and topic not in used_topics)

    # Performs the different platform helper step.
    def different_platform(item: dict) -> bool:
        platform = course_platform_key(item)
        return bool(platform and platform not in used_platforms)

    intermediate = next(
        (item for item in items if item.get("level") == "Intermediate" and course_item_key(item) not in seen_keys and different_from_visible(item)),
        None,
    )
    if intermediate is None:
        intermediate = next(
            (item for item in items if item.get("level") == "Intermediate" and course_item_key(item) not in seen_keys and different_platform(item)),
            None,
        )
    if intermediate is None:
        intermediate = next((item for item in items if item.get("level") == "Intermediate" and course_item_key(item) not in seen_keys), None)
    add(intermediate)

    for item in items:
        if len(output) >= target_count:
            break
        if course_item_key(item) in seen_keys:
            continue
        if different_from_visible(item):
            add(item)

    for item in items:
        if len(output) >= target_count:
            break
        if course_item_key(item) in seen_keys:
            continue
        if different_platform(item):
            add(item)

    for item in items:
        if len(output) >= target_count:
            break
        add(item)

    if output:
        visible = output[:min(2, target_count)]
        diagnostics = {
            "levels": [item.get("level") for item in visible],
            "platforms": [course_platform_key(item) for item in visible],
            "topics": [course_topic_key(item) for item in visible],
        }
        print(f"[AI Updates] course visible diversity {diagnostics}", flush=True)
    return output[:target_count]


# Performs the select supporting content cards helper step.
def select_supporting_content_cards(
    candidates: list[dict],
    content_type: str,
    target_count: int,
    *,
    visible_count: int | None = None,
    use_course_bank: bool = True,
) -> list[dict]:
    """Select and rewrite course/movie cards in the modular path only."""
    target_count = max(1, int(target_count or 1))
    visible_count = max(1, min(target_count, int(visible_count or target_count)))
    pool = [item for item in candidates or [] if isinstance(item, dict)]
    if use_course_bank and content_type == "course" and target_count >= COURSE_WEEKLY_TARGET_COUNT:
        bank_stats = upsert_course_bank(pool)
        selected, weekly_report = select_weekly_courses(target_count=COURSE_WEEKLY_TARGET_COUNT)
        if selected:
            save_last_course_platforms(selected)
        print(
            f"[AI Updates] course weekly bank selector selected={len(selected)} "
            f"bank_total={bank_stats.get('total')} fallback={weekly_report.get('fallback_used')}",
            flush=True,
        )
        log_event(
            "courses.weekly_bank_selection_finished",
            selected=len(selected),
            bank_total=bank_stats.get("total"),
            fallback_used=weekly_report.get("fallback_used"),
            shortages=weekly_report.get("shortages"),
            used_platforms=weekly_report.get("used_platforms"),
            bank_counts_by_level=weekly_report.get("bank_counts_by_level"),
        )
        pool = selected
    if not pool or not model_available():
        return []
    selection_limit = target_count
    if content_type == "course" and target_count >= 2:
        selection_limit = min(len(pool), target_count if len(pool) <= target_count else max(target_count + 8, target_count * 4))
        pool = prepare_course_prompt_pool(pool, visible_count)
    compact = [compact_supporting_candidate(item, content_type, index) for index, item in enumerate(pool, start=1)]
    print(
        f"[AI Updates] GPT supporting {content_type} selection started: "
        f"pool={len(compact)} target={target_count} selection_limit={selection_limit}",
        flush=True,
    )
    try:
        prompt_started = time.time()
        initial_model = MODEL_FLASH_MODEL
        initial_provider = MODEL_PROVIDER
        log_event(
            "prompt.supporting_selection.started",
            content_type=content_type,
            model=initial_model,
            provider=initial_provider,
            prompt_name="supporting_prompt",
            payload_candidates=len(compact),
            target_count=target_count,
            selection_limit=selection_limit,
            visible_count=visible_count,
            candidate_sample=summarize_items(pool, limit=8),
        )
        selected_model = initial_model
        selected_provider = initial_provider
        prompt_text = build_supporting_prompt(content_type, selection_limit, visible_count=visible_count)
        estimate = estimate_prompt_tokens(prompt_text, compact)
        log_event(
            "model.token_estimate",
            stage=f"supporting_{content_type}",
            model=selected_model,
            provider=selected_provider,
            payload_candidates=len(compact),
            **estimate,
        )
        try:
            parsed_data = generate_json(prompt_text, compact, model=MODEL_FLASH_MODEL)
        except Exception as model_exc:
            details = model_failure_details(model_exc)
            record_model_failure(
                f"supporting_{content_type}",
                MODEL_FLASH_MODEL,
                MODEL_PROVIDER,
                details,
                {"payload_candidates": len(compact)},
            )
            log_event(
                "prompt.supporting_selection.model_failed",
                content_type=content_type,
                model=MODEL_FLASH_MODEL,
                provider=MODEL_PROVIDER,
                **{key: value for key, value in details.items() if key not in {"provider", "model"}},
            )
            print(
                f"[AI Updates] {MODEL_PROVIDER} supporting {content_type} failed "
                f"category={details.get('category', 'unknown')} error={details.get('error', str(model_exc))}",
                flush=True,
            )
            raise
        if isinstance(parsed_data, list):
            parsed_data = {"articles": parsed_data}
        if not isinstance(parsed_data, dict):
            raise RuntimeError(f"model_prompt_format_incompatible:{type(parsed_data).__name__}")
        usage = parsed_data.pop("__model_usage", None) if isinstance(parsed_data, dict) else None
        log_token_usage(f"supporting_{content_type}", selected_model, selected_provider, usage, estimate, payload_candidates=len(compact))
        merged = merge_supporting_cards(
            list(parsed_data.get("articles") or [])[:selection_limit],
            pool,
            content_type,
            selection_limit,
        )
        if content_type == "course":
            merged = balance_course_levels(merged, target_count)
            merged = enforce_course_platform_level_pairs(merged, pool, target_count)
            merged = enforce_course_alternative_platforms(merged, pool, target_count)
            save_last_course_platforms(merged)
        else:
            merged = merged[:target_count]
        print(f"[AI Updates] GPT supporting {content_type} selected {len(merged)}", flush=True)
        log_event(
            "prompt.supporting_selection.finished",
            content_type=content_type,
            model=selected_model,
            provider=selected_provider,
            seconds=round(time.time() - prompt_started, 2),
            selected=len(merged),
            selected_sample=summarize_items(merged, limit=8),
        )
        return merged
    except Exception as exc:
        details = model_failure_details(exc)
        record_model_failure(f"supporting_{content_type}", selected_model if "selected_model" in locals() else MODEL_FLASH_MODEL, selected_provider if "selected_provider" in locals() else MODEL_PROVIDER, details)
        print(f"[AI Updates] {MODEL_PROVIDER} supporting {content_type} failed: {details.get('category', 'unknown')} - {details.get('error', str(exc))}", flush=True)
        log_event(
            "prompt.supporting_selection.failed",
            content_type=content_type,
            model=MODEL_FLASH_MODEL,
            provider=MODEL_PROVIDER,
            **{key: value for key, value in details.items() if key not in {"provider", "model"}},
        )
        return []

__all__ = sorted(name for name in globals() if not name.startswith("_"))
