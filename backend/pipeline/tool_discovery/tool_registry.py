# This file is part of the AI newsletter system.
"""Single-file tool registry helpers.

The active registry is backend/pipeline/tool_discovery/monthly_tools-site.json. It stores tool records,
popularity, sector metadata, and official update/news sites in one place.
"""

from __future__ import annotations

from backend.config.settings import MONTHLY_TOOLS_FILE, load_json, normalized_text, safe_write_json, utc_now


REGISTRY_SCHEMA = "monthly_tools_site_v1"


# Performs the tool key helper step.
def tool_key(item: dict | str) -> str:
    if isinstance(item, str):
        return normalized_text(item)
    if not isinstance(item, dict):
        return ""
    return normalized_text(item.get("tool") or item.get("company") or "")


# Reads load registry from the current store or request context.
def load_registry() -> dict:
    return load_json(MONTHLY_TOOLS_FILE, {"schema": REGISTRY_SCHEMA, "tools": [], "tool_records": []})


# Reads load registry records from the current store or request context.
def load_registry_records() -> list[dict]:
    payload = load_registry()
    records = payload.get("tool_records") or []
    if isinstance(records, dict):
        records = list(records.values())
    output = [dict(item) for item in records if isinstance(item, dict)]
    if output:
        return output
    return [
        {"tool": item}
        for item in (payload.get("tools") or [])
        if isinstance(item, str) and item.strip()
    ]


# Saves save registry records to the configured output or state store.
def save_registry_records(records: list[dict], *, extra: dict | None = None) -> None:
    today = utc_now().date().isoformat()
    output = [dict(item) for item in records or [] if isinstance(item, dict)]
    payload = {
        **(extra or {}),
        "schema": REGISTRY_SCHEMA,
        "updated": today,
        "tools": [item.get("tool") for item in output if item.get("tool")],
        "tool_records": output,
    }
    safe_write_json(MONTHLY_TOOLS_FILE, payload)


# Performs the official site map helper step.
def official_site_map() -> dict[str, dict]:
    sites = {}
    for item in load_registry_records():
        key = tool_key(item)
        if key and item.get("official_site"):
            sites[key] = dict(item)
    return sites



