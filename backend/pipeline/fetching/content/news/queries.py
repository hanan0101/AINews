"""News discovery: query planning and rotation."""

from .common import *

def has_arabic_text(value: str = "") -> bool:
    return bool(re.search(r"[\u0600-\u06ff]", str(value or "")))


# Performs the unique full query rows helper step.
def unique_full_query_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for row in rows:
        query = clean_text(row.get("query") or "") if row.get("tool_query_required") else ensure_ai_scope(row.get("query") or "")
        if not query or has_arabic_text(query):
            continue
        key = re.sub(r"\s+", " ", query.lower())
        if row.get("tool_query_required") and row.get("sector"):
            key = f"{key}|sector:{row.get('sector')}"
        if key in seen:
            continue
        seen.add(key)
        new_row = dict(row)
        new_row["bucket"] = new_row.get("bucket") or "general"
        new_row["query"] = query
        unique.append(new_row)
    return unique


def root_site_token(site: str = "") -> str:
    value = str(site or "").strip().replace("https://", "").replace("http://", "").strip("/")
    if not value:
        return ""
    parsed = urlparse(f"https://{value}")
    return (parsed.netloc or value.split("/", 1)[0]).lower().removeprefix("www.")


def official_site_token(site: str = "") -> str:
    return canonical_official_site(site or "")


def trusted_media_exa_rows(tools: list[dict], *, single: bool = False) -> list[dict]:
    limit = TRUSTED_MEDIA_SINGLE_EXA_QUERY_LIMIT if single else TRUSTED_MEDIA_EXA_QUERY_LIMIT
    if limit <= 0:
        return []
    rows = []
    for tool in tools:
        tool_name = clean_text(tool.get("tool") or tool.get("company") or "")
        if not tool_name:
            continue
        for media in TRUSTED_MEDIA_SOURCES:
            trusted_domain = media["domain"]
            for template in TRUSTED_MEDIA_TOOL_QUERY_TEMPLATES:
                query = template.format(trusted_domain=trusted_domain, tool=tool_name)
                rows.append({
                    "query": query,
                    "bucket": "trusted_media_tool_update",
                    "query_mix": "trusted_media_tool_update",
                    "source_lane": "trusted_media_exa",
                    "source_type": "exa_trusted_media_tool_update",
                    "tool_query_variant": "trusted_media_tool_ai_update",
                    "tool": tool_name,
                    "company": clean_text(tool.get("company") or ""),
                    "trusted_media_name": media["name"],
                    "trusted_media_domain": trusted_domain,
                    "exa_num_results": 5 if single else 8,
                    "use_news_category": True,
                })
                if len(rows) >= limit:
                    return rows
    return rows


# Performs the next exa tool rotation offset helper step.
# Unlike SearXNG's tool-driven rows (see next_news_query_rotation), the Exa
# official-tool-update rows used to always take the same top-N tools by
# popularity_score every cycle and every run. This mirrors the same
# load/advance/persist pattern against NEWS_FETCH_STATE_FILE so each cycle
# covers a different slice of the pool once it grows past batch_size.
def next_tool_rotation_offset(pool_size: int, batch_size: int, *, state_key: str = "exa_tool_driven_rotation") -> int:
    if pool_size <= 0:
        return 0
    rotation = rotation_state(state_key)
    offset = int(rotation.get("next_offset") or 0) % pool_size
    _, next_offset = rotation_window(offset, pool_size, max(1, batch_size))
    save_rotation_state(state_key, {
        "updated_at": utc_now().isoformat(),
        "offset": offset,
        "pool_size": pool_size,
        "batch_size": batch_size,
        "next_offset": next_offset,
    })
    return offset


def exa_tool_update_script_rows(*, single: bool = False, cycle: int = 1) -> tuple[list[dict], list[dict]]:
    limit = AI_UPDATES_SINGLE_EXA_QUERY_LIMIT if single else AI_UPDATES_EXA_QUERY_LIMIT
    tool_limit = 6 if single else max(limit, AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT)
    if single:
        tools = load_monthly_tool_records(limit=tool_limit)
        cycle_tool_limit = 6
    else:
        # Pull a pool larger than one cycle's query budget so there is
        # something real to rotate through; falls back gracefully to the
        # same static top-N behavior while the registry stays small.
        pool = load_monthly_tool_records(limit=max(tool_limit * 4, 160))
        # CHANGE: while the tool registry is smaller than the configured
        # rotation batch (AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT, default 48),
        # every cycle took tools[:48] = the whole pool regardless of the
        # rotation offset, so cycle 1 and cycle 2 of the same run fetched
        # ~the same candidates twice (hit in production 2026-07-11: 41-tool
        # registry, 229 vs 215 nearly-identical unique results per cycle).
        # Splitting the CURRENT pool across this run's cycles makes each
        # cycle query a genuinely different slice; the cap at
        # AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT still applies once the
        # registry grows large enough that a 48-tool slice no longer risks
        # cross-cycle overlap.
        cycles_per_run = max(1, min(2, env_int("AI_UPDATES_NEWS_FETCH_CYCLES", "2")))
        cycle_tool_limit = min(AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT, max(1, math.ceil(len(pool) / cycles_per_run))) if pool else AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT
        offset = next_tool_rotation_offset(
            len(pool),
            cycle_tool_limit,
            state_key="exa_tool_driven_rotation",
        )
        tools = rotate_list(pool, offset)
    rows = []
    official_tools = tools[:cycle_tool_limit]
    for tool in official_tools:
        tool_name = clean_text(tool.get("tool") or tool.get("company") or "")
        if not tool_name:
            continue
        official_site = official_site_token(tool.get("official_site") or "")
        official_domain = root_site_token(tool.get("official_site") or "")
        # CHANGE: the single word "update" biases Exa's neural ranking toward
        # help-center "Release Notes" index pages (which list dozens of small
        # changes and get correctly rejected downstream as roundup/aggregator
        # pages) and away from genuine flagship launch posts that use
        # different language ("Introducing...", "GPT-5.6: Frontier
        # intelligence...") - verified live 2026-07-11: this narrow query
        # missed OpenAI's actual GPT-5.6 launch post entirely, while adding
        # launch-style verbs and excluding the help subdomain surfaced it
        # (and xAI's "Introducing Grok 4.5", Cursor's dedicated changelog
        # entries) directly. -site: is Exa-supported query syntax, same as
        # site:.
        help_exclusion = f' -site:help.{official_domain} -site:support.{official_domain}' if official_domain else ""
        query = (
            f'site:{official_domain}{help_exclusion} "{tool_name}" '
            f'(update OR launch OR launches OR introducing OR unveils OR announces OR "now available")'
            if official_domain else
            f'"{tool_name}" (update OR launch OR launches OR introducing OR unveils OR announces OR "now available")'
        )
        rows.append({
            "query": query,
            "bucket": "official_tool_update",
            "query_mix": "verified_exa_recent_tool_update",
            "source_lane": "official_exa",
            "source_type": "exa_recent_tool_updates_style",
            "tool_query_variant": "tool_name_update_verified_site_search",
            "tool": tool_name,
            "company": clean_text(tool.get("company") or ""),
            "official_site": official_site,
            "official_domain": official_domain,
            "exa_script_style": True,
            "exa_num_results": 5 if single else 8,
            "exa_keep_results": 3 if single else 4,
        })
    rows.extend(trusted_media_exa_rows(tools, single=single))
    # CHANGE: these 9 queries carry no per-tool/per-cycle variable (unlike
    # the tool-rotation and trusted-media rows above), so re-running them on
    # cycle 2+ of the same run returns byte-identical results to cycle 1 -
    # verified live 2026-07-11 (same 4 URLs, same order, for the same query
    # string in both cycles). That wastes half of cycle 2's Exa query budget
    # on zero new information. Only run them on the first cycle of a run;
    # rotated tool coverage already grows on later cycles.
    broad_queries = list(EXA_PRODUCT_UPDATE_BROAD_QUERIES[:3] if single else EXA_PRODUCT_UPDATE_BROAD_QUERIES) if cycle <= 1 else []
    for query in broad_queries:
        rows.append({
            "query": query,
            "bucket": "general_update",
            "query_mix": "exa_product_update_broad",
            "source_lane": "fallback_broad",
            "source_type": "exa_product_update_broad",
            "tool_query_variant": "product_update_broad",
            "exa_num_results": 6 if single else 12,
            "use_news_category": False,
        })
    return rows, tools


# Builds compose query mix rows for the next pipeline or API step.
def compose_query_mix_rows(
    tool_rows: list[dict],
    specialized_rows: list[dict],
    broad_rows: list[dict],
    limit: int,
    *,
    fixed_budgets: dict[str, int] | None = None,
) -> tuple[list[dict], dict]:
    """Apply the intended 50/30/20 query mix without making it a result quota."""
    limit = max(1, int(limit or 1))
    if fixed_budgets:
        requested = {
            "tool_driven": max(0, int(fixed_budgets.get("tool_driven") or 0)),
            "specialized": max(0, int(fixed_budgets.get("specialized") or 0)),
            "broad": max(0, int(fixed_budgets.get("broad") or 0)),
        }
        budgets = {"tool_driven": 0, "specialized": 0, "broad": 0}
        remaining = limit
        for key in ("tool_driven", "specialized", "broad"):
            budgets[key] = min(requested[key], remaining)
            remaining -= budgets[key]
    else:
        budgets = {
            "tool_driven": round(limit * 0.45),
            "specialized": round(limit * 0.4),
            "broad": 0,
        }
        budgets["broad"] = max(0, limit - budgets["tool_driven"] - budgets["specialized"])
        if limit >= 3 and budgets["broad"] < 1:
            budgets["broad"] = 1
            if budgets["specialized"] > 0:
                budgets["specialized"] -= 1
            else:
                budgets["tool_driven"] = max(1, budgets["tool_driven"] - 1)
    parts = [
        ("tool_driven", tool_rows, budgets["tool_driven"]),
        ("specialized", specialized_rows, budgets["specialized"]),
        ("broad", broad_rows, budgets["broad"]),
    ]
    rows = []
    for mix, source_rows, count in parts:
        for row in unique_full_query_rows(source_rows)[:count]:
            rows.append({**row, "query_mix": mix})
    if len(rows) < limit:
        seen = {re.sub(r"\s+", " ", row.get("query", "").lower()) for row in rows}
        for row in unique_full_query_rows([*(tool_rows or []), *(specialized_rows or []), *(broad_rows or [])]):
            key = re.sub(r"\s+", " ", row.get("query", "").lower())
            if key in seen:
                continue
            rows.append({**row, "query_mix": row.get("query_mix") or "fill"})
            seen.add(key)
            if len(rows) >= limit:
                break
    return rows[:limit], {"budgets": budgets}


SECTOR_HINT_TO_SECTOR = {
    "image_design": "visual_arts",
    "design": "visual_arts",
    "video_creation": "films",
    "audio_voice": "music",
    "music_voice": "music",
    "fashion_try_on": "fashion",
    "writing_storytelling": "literature",
    "translation": "literature",
    "archives_research": "libraries",
    "learning": "ai_education_training_daily_tasks",
    "daily_assistant": "ai_education_training_daily_tasks",
    "architecture": "architecture",
}

SECTOR_QUERY_TERMS = {
    "films": "film video editing creative work",
    "visual_arts": "design image visual creative work",
    "music": "audio voice music narration",
    "fashion": "fashion style try on",
    "literature": "writing translation storytelling",
    "libraries": "research archives knowledge",
    "ai_education_training_daily_tasks": "learning productivity daily tasks assistant",
    "work_productivity": "productivity documents meetings workflow",
}


LAST_DISCOVERY_META: dict[str, dict] = {}

NEWS_QUERY_ANGLE_PROFILES = [
    {
        "name": "official_tool_updates",
        "keywords": ("release", "changelog", "official", "product", "general_market"),
        "budgets": {"tool_driven": 24, "specialized": 10, "broad": 3},
    },
    {
        "name": "culture_creative",
        "keywords": (
            "culture", "creative", "music", "audio", "voice", "film", "video",
            "design", "visual", "fashion", "writing", "literature", "archive",
            "heritage", "museum", "library",
        ),
        "budgets": {"tool_driven": 16, "specialized": 16, "broad": 5},
    },
    {
        "name": "daily_work_learning",
        "keywords": (
            "daily", "assistant", "shopping", "travel", "mobile", "personal",
            "work", "workflow", "productivity", "meeting", "document", "learning",
            "education", "health", "wellness", "cooking",
        ),
        "budgets": {"tool_driven": 16, "specialized": 14, "broad": 7},
    },
    {
        "name": "broad_market_scan",
        "keywords": ("impact", "market", "launch", "available", "rollout", "new ai"),
        "budgets": {"tool_driven": 14, "specialized": 8, "broad": 15},
    },
]


# Performs the rotate list helper step.
def rotate_list(items: list[dict], offset: int = 0) -> list[dict]:
    if not items:
        return []
    offset = int(offset or 0) % len(items)
    return list(items[offset:]) + list(items[:offset])


# Performs the row matches keywords helper step.
def row_matches_keywords(row: dict, keywords: tuple[str, ...]) -> bool:
    haystack = normalized_text(" ".join(str(row.get(key) or "") for key in (
        "bucket",
        "query",
        "tool",
        "company",
        "source_type",
        "tool_type",
        "sector",
        "sector_hint",
    )))
    return any(normalized_text(keyword) in haystack for keyword in keywords)


# Performs the prioritize angle rows helper step.
def prioritize_angle_rows(rows: list[dict], keywords: tuple[str, ...]) -> list[dict]:
    rows = list(rows or [])
    if not keywords:
        return rows
    matching = [row for row in rows if row_matches_keywords(row, keywords)]
    rest = [row for row in rows if not row_matches_keywords(row, keywords)]
    return matching + rest


# Performs the next news query rotation helper step.
def next_news_query_rotation(source: str, totals: dict[str, int]) -> tuple[dict, dict]:
    """Rotate full-generation search angles so consecutive runs explore different pools."""
    state = load_json(NEWS_FETCH_STATE_FILE, {})
    all_rotation = state.get("news_query_rotation") if isinstance(state.get("news_query_rotation"), dict) else {}
    previous = all_rotation.get(source) if isinstance(all_rotation.get(source), dict) else {}
    angle_index = int(previous.get("next_angle_index") or 0) % len(NEWS_QUERY_ANGLE_PROFILES)
    profile = NEWS_QUERY_ANGLE_PROFILES[angle_index]

    offsets = {
        "tool_driven": int(previous.get("next_tool_offset") or 0),
        "specialized": int(previous.get("next_specialized_offset") or 0),
        "broad": int(previous.get("next_broad_offset") or 0),
    }
    budgets = profile.get("budgets") or {}
    next_record = {
        "updated_at": utc_now().isoformat(),
        "source": source,
        "angle": profile.get("name") or "",
        "angle_index": angle_index,
        "next_angle_index": (angle_index + 1) % len(NEWS_QUERY_ANGLE_PROFILES),
        "tool_offset": offsets["tool_driven"],
        "specialized_offset": offsets["specialized"],
        "broad_offset": offsets["broad"],
        "next_tool_offset": (offsets["tool_driven"] + max(1, int(budgets.get("tool_driven") or 1))) % max(1, int(totals.get("tool_driven") or 1)),
        "next_specialized_offset": (offsets["specialized"] + max(1, int(budgets.get("specialized") or 1))) % max(1, int(totals.get("specialized") or 1)),
        "next_broad_offset": (offsets["broad"] + max(1, int(budgets.get("broad") or 1))) % max(1, int(totals.get("broad") or 1)),
        "totals": totals,
        "budgets": budgets,
    }
    all_rotation[source] = next_record
    state["news_query_rotation"] = all_rotation
    safe_write_json(NEWS_FETCH_STATE_FILE, state)
    return profile, next_record


# Performs the discovery rows helper step.
def discovery_rows(source: str, *, single: bool = False, target_hint: str = "", cycle: int = 1) -> list[dict]:
    """Return the final query rows for one provider.

    Full generation uses a larger query budget. Single refill uses the same
    discovery strategy with smaller limits and a target hint from the card.
    """
    if source == "searxng":
        limit = AI_UPDATES_SINGLE_SEARXNG_QUERY_LIMIT if single else AI_UPDATES_SEARXNG_QUERY_LIMIT
        searxng_limit = min(limit, 6 if single else AI_UPDATES_SEARXNG_TOOL_QUERY_LIMIT)
        if single:
            tools = load_monthly_tool_records(limit=searxng_limit)
        else:
            # CHANGE: SearXNG used to always take the same top-N tools by
            # popularity_score every run (no rotation), unlike Exa which
            # already rotates through the registry - so 35+ of the 41
            # registered tools never got a SearXNG query at all. Mirror
            # Exa's rotation here with its own offset/state key so the two
            # sources don't have to move in lockstep.
            pool = load_monthly_tool_records(limit=max(searxng_limit * 4, 160))
            offset = next_tool_rotation_offset(len(pool), searxng_limit, state_key="searxng_tool_driven_rotation")
            tools = rotate_list(pool, offset)
        rows = []
        for tool in tools[:searxng_limit]:
            tool_name = clean_text(tool.get("tool") or tool.get("company") or "")
            if not tool_name:
                continue
            # REVERTED 2026-07-11: tried mirroring Exa's site:+exclusions+OR
            # query here, but live results showed 23/24 SearXNG queries
            # returning raw_count=0 (including the one with no site:
            # restriction at all) - SearXNG scrapes Google's HTML rather
            # than using an official API, and a long, unusual boolean query
            # is much more likely to trip Google's bot detection into
            # serving an empty/challenge page than a real API would notice.
            # Back to the simple query that was actually verified to return
            # results (3-6 accepted per run).
            official_domain = root_site_token(tool.get("official_site") or "")
            query = f'"{tool_name}" update'
            rows.append({
                "query": query,
                "bucket": "searxng_url_discovery",
                "query_mix": "tool_name_update",
                "source_lane": "tool_searxng",
                "source_type": "searxng_url_discovery",
                "tool": tool_name,
                "company": clean_text(tool.get("company") or ""),
                "official_site": clean_text(tool.get("official_site") or ""),
                "official_domain": official_domain,
                "searxng_url_discovery_only": True,
            })
        LAST_DISCOVERY_META[source] = {
            "tool_count": len(tools),
            "official_tool_query_limit": AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT,
            "searxng_tool_query_limit": searxng_limit,
            "tool_names": [tool.get("tool") for tool in tools],
            "query_mix": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
            "tool_query_variant_rows": {"tool_name_update": sum(1 for row in rows if row.get("query_mix") == "tool_name_update")},
            "query_mix_budgets": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
            "query_angle": "searxng_tool_name_update",
            "single": bool(single),
        }
        return rows

    if source == "exa":
        rows, tools = exa_tool_update_script_rows(single=single, cycle=cycle)
        LAST_DISCOVERY_META[source] = {
            "tool_count": len(tools),
            "official_tool_query_limit": AI_UPDATES_OFFICIAL_TOOL_QUERY_LIMIT,
            "tool_names": [tool.get("tool") for tool in tools],
            "tool_group_counts": dict(Counter(tool_group(tool) for tool in tools)),
            "query_mix": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
            "tool_query_variant_rows": dict(Counter(row.get("tool_query_variant") or "none" for row in rows)),
            "query_mix_budgets": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
            "trusted_media_sources": [source["domain"] for source in TRUSTED_MEDIA_SOURCES],
            "query_angle": "exa_recent_tool_updates_style",
            "single": bool(single),
        }
        return rows

    # CHANGE: Keep Exa on the original neural-friendly broad query bank, but
    # switch only SearXNG to strict AND-condition broad queries because SearXNG
    # is literal keyword search and needs tighter AI/action/product constraints.
    general_update_rows = SEARXNG_STRICT_GENERAL_AI_UPDATE_ROWS if source == "searxng" else GENERAL_AI_UPDATE_ROWS

    if single:
        base_rows = list(SINGLE_ROWS)
        hint = target_hint.lower()
        if any(term in hint for term in ("design", "image", "visual", "fashion", "culture", "audio", "video")):
            priority = ("culture", "audio", "daily", "learning", "video", "design", "fashion")
        elif any(term in hint for term in ("daily", "shopping", "travel", "mobile", "personal")):
            priority = ("daily", "shopping", "travel", "mobile", "personal", "assistant", "audio", "culture")
        else:
            priority = ("impact", "market", "general", "daily", "work", "assistant", "learning", "culture", "audio", "design", "video")
        broad = BROAD_EXA_ROWS if source == "exa" else BROAD_SEARXNG_ROWS
        source_rows = [*broad, *base_rows] if source == "searxng" else [*base_rows, *broad]
        base_rows = sorted(source_rows, key=lambda row: 0 if any(p in str(row.get("bucket") or "") for p in priority) else 1)
        limit = AI_UPDATES_SINGLE_EXA_QUERY_LIMIT if source == "exa" else AI_UPDATES_SINGLE_SEARXNG_QUERY_LIMIT
        tools = load_monthly_tool_records(limit=6)
        tool_queries = build_tool_queries(tools).get(source, [])
        rows, mix_meta = compose_query_mix_rows(
            tool_queries,
            base_rows,
            [MOTHER_QUERY_ROW, *general_update_rows, *broad],
            limit,
        )
        LAST_DISCOVERY_META[source] = {
            "tool_count": len(tools),
            "tool_names": [tool.get("tool") for tool in tools],
            "query_mix": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
            "tool_query_variant_rows": dict(Counter(row.get("tool_query_variant") or "none" for row in rows)),
            "query_mix_budgets": mix_meta.get("budgets", {}),
            "single": True,
        }
        return rows
    broad = BROAD_EXA_ROWS if source == "exa" else BROAD_SEARXNG_ROWS
    limit = AI_UPDATES_EXA_QUERY_LIMIT if source == "exa" else AI_UPDATES_SEARXNG_QUERY_LIMIT
    tools = load_monthly_tool_records(limit=max(24, AI_UPDATES_TOOL_QUERY_ROTATION_POOL))
    tool_queries = build_tool_queries(tools).get(source, [])
    full_query_budget = min(limit, 37)
    profile, rotation = next_news_query_rotation(
        source,
        {
            "tool_driven": len(tool_queries),
            "specialized": len(DEFAULT_QUERY_ROWS),
            "broad": len([MOTHER_QUERY_ROW, *general_update_rows, *broad]),
        },
    )
    keywords = tuple(profile.get("keywords") or ())
    tool_queries = rotate_list(prioritize_angle_rows(tool_queries, keywords), rotation.get("tool_offset"))
    specialized_rows = rotate_list(
        prioritize_angle_rows(DEFAULT_QUERY_ROWS, keywords),
        rotation.get("specialized_offset"),
    )
    broad_rows = rotate_list(
        prioritize_angle_rows([MOTHER_QUERY_ROW, *general_update_rows, *broad], keywords),
        rotation.get("broad_offset"),
    )
    rows, mix_meta = compose_query_mix_rows(
        tool_queries,
        specialized_rows,
        broad_rows,
        full_query_budget,
        fixed_budgets=profile.get("budgets") or {"tool_driven": 24, "specialized": 10, "broad": 3},
    )
    LAST_DISCOVERY_META[source] = {
        "tool_count": len(tools),
        "tool_names": [tool.get("tool") for tool in tools],
        "tool_group_counts": dict(Counter(tool_group(tool) for tool in tools)),
        "query_mix": dict(Counter(row.get("query_mix") or "unknown" for row in rows)),
        "tool_query_variant_rows": dict(Counter(row.get("tool_query_variant") or "none" for row in rows)),
        "query_mix_budgets": mix_meta.get("budgets", {}),
        "query_angle": profile.get("name") or "",
        "query_rotation": rotation,
        "single": False,
    }
    return rows


# Performs the freshness query helper step.

__all__ = [name for name in globals() if not name.startswith("__")]
