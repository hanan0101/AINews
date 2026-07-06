# This file is part of the AI newsletter system.
"""Official-site registry and discovery helpers for AI tools.

This file owns the official-site part of tool awareness. Tool discovery can
ask it for cached sites, default seeds, or best-effort web detection.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

from backend.config.settings import (
    AI_UPDATES_EXA_TIMEOUT,
    EXA_API_KEY,
    MONTHLY_TOOLS_FILE,
    clean_text,
    env_int,
    load_json,
    normalized_text,
    safe_write_json,
    utc_now,
)
from backend.logging.pipeline_logging import file_status, log_event


AI_UPDATES_TOOL_SITE_DISCOVERY_LIMIT = env_int("AI_UPDATES_TOOL_SITE_DISCOVERY_LIMIT", "24")


# WHAT: Known official update/news sites for common tools.
# HOW: Local JSON-like seed map used before web discovery.
# INPUT: Normalized tool/company names.
# OUTPUT: Canonical official-site path strings.
DEFAULT_OFFICIAL_TOOL_SITES = {
    "chatgpt": "help.openai.com/en/articles/6825453-chatgpt-release-notes",
    "openai": "openai.com/products/release-notes",
    "claude": "anthropic.com/news",
    "anthropic": "anthropic.com/news",
    "google gemini": "blog.google/products/gemini",
    "gemini": "blog.google/products/gemini",
    "microsoft copilot": "microsoft.com/en-us/microsoft-365/blog",
    "microsoft 365 copilot": "microsoft.com/en-us/microsoft-365/blog",
    "adobe firefly": "blog.adobe.com",
    "canva": "canva.com/newsroom",
    "canva ai": "canva.com/newsroom",
    "figma ai": "figma.com/blog",
    "runway": "runwayml.com/research",
    "elevenlabs": "elevenlabs.io/blog",
    "perplexity": "perplexity.ai/hub/blog",
    "suno": "suno.com/blog",
    "midjourney": "docs.midjourney.com",
    "luma": "lumalabs.ai/news",
    "heygen": "heygen.com/blog",
    "krea": "krea.ai/blog",
    "grammarly": "grammarly.com/blog/company",
    "notebooklm": "blog.google/technology/ai",
    "grok": "x.ai/news",
    "deepseek": "deepseek.com",
    "poe": "quorablog.quora.com",
    "udio": "udio.com/blog",
    "gamma": "gamma.app/blog",
    "prezi ai": "blog.prezi.com",
    "weaviate": "weaviate.io/blog",
    "m-files": "m-files.com/blog",
    "luma ray3": "lumalabs.ai/news",
    "kittl": "kittl.com/blog",
}


COMMON_TOOL_NAME_WORDS = {"ai", "app", "studio", "pro", "plus"}


# WHAT: Builds the stable registry key for one tool record.
# HOW: Uses tool first, then company fallback.
# INPUT: Tool dict or string.
# OUTPUT: Normalized key string.
def tool_record_key(item: dict | str) -> str:
    if isinstance(item, str):
        return normalized_text(item)
    if not isinstance(item, dict):
        return ""
    return normalized_text(item.get("tool") or item.get("name") or item.get("company") or "")


# WHAT: Normalizes a website/path into the registry format.
# HOW: Removes scheme, www, query/fragment, and trailing slash.
# INPUT: Raw URL/domain/path string.
# OUTPUT: Canonical domain/path string.
def canonical_official_site(value: str = "") -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = (parsed.netloc or parsed.path.split("/", 1)[0]).lower().removeprefix("www.")
    path = parsed.path if parsed.netloc else ("/" + parsed.path.split("/", 1)[1] if "/" in parsed.path else "")
    path = re.sub(r"/+", "/", path).strip("/")
    return f"{host}/{path}".rstrip("/") if path else host


# WHAT: Converts a canonical official site into a URL.
# HOW: Adds https:// after canonical cleanup.
# INPUT: Canonical or raw site string.
# OUTPUT: HTTPS URL string or empty string.
def official_site_url(site: str = "") -> str:
    clean = canonical_official_site(site)
    return f"https://{clean}" if clean else ""


# WHAT: Converts official-site check results into stable registry statuses.
# HOW: Treats reachable or cached official sites as active.
# INPUT: Raw status, official site, verified boolean.
# OUTPUT: Stable status string such as active/not_found/http:404.
def normalize_official_site_status(status: str = "", *, site: str = "", verified: bool = False) -> str:
    clean = clean_text(status or "")
    if verified or clean.startswith("ok:"):
        return "active"
    if not clean and canonical_official_site(site):
        return "active"
    if clean in {"cached", "searxng_fallback"} and canonical_official_site(site):
        return "active"
    return clean


# WHAT: Verifies that an official site is reachable.
# HOW: Performs a direct HTTP GET with redirects.
# INPUT: Site string and timeout.
# OUTPUT: Tuple of verified boolean and raw status reason.
def verify_official_site(site: str = "", *, timeout: int = 6) -> tuple[bool, str]:
    url = official_site_url(site)
    if not url:
        return False, "empty"
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 AI Newsletter official-site-check"},
            allow_redirects=True,
        )
    except Exception as exc:
        return False, f"request_error:{type(exc).__name__}"
    status = int(getattr(response, "status_code", 0) or 0)
    if 200 <= status < 400:
        final = canonical_official_site(getattr(response, "url", "") or site)
        return True, f"ok:{status}:{final or canonical_official_site(site)}"
    return False, f"http:{status}"


# WHAT: Builds product/company name variants for official-site discovery.
# HOW: Strips version numbers and generic suffixes from tool names.
# INPUT: Tool and company names.
# OUTPUT: Ordered search-name variants.
def official_site_name_variants(tool_name: str = "", company_name: str = "") -> list[str]:
    tool = clean_text(tool_name or "")
    company = clean_text(company_name or "")
    variants: list[str] = []

    # Performs the add helper step.
    def add(value: str = "") -> None:
        clean = clean_text(value)
        key = normalized_text(clean)
        if clean and key and key not in {normalized_text(item) for item in variants}:
            variants.append(clean)

    add(tool)
    base = re.sub(r"\b(v?\d+(?:\.\d+)*)\b", "", tool, flags=re.IGNORECASE)
    base = re.sub(r"\s+", " ", base).strip(" -")
    add(base)
    tokens = [part for part in re.split(r"\s+", base) if normalized_text(part) not in COMMON_TOOL_NAME_WORDS]
    if tokens:
        add(" ".join(tokens[:2]))
        add(tokens[0])
    add(company)
    return variants


# WHAT: Discovers a likely official owned domain for a tool.
# HOW: Uses Exa neural search over official blog/news/update wording.
# INPUT: Tool and company names.
# OUTPUT: Domain string or empty string.
def get_official_domain(tool_name: str = "", company_name: str = "") -> str:
    tool = clean_text(tool_name or "")
    company = clean_text(company_name or tool)
    if not EXA_API_KEY or not (tool or company):
        return ""

    headers = {"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY}
    variants = official_site_name_variants(tool, company) or [tool]

    # Performs the domain contains name helper step.
    def domain_contains_name(domain: str, name: str) -> bool:
        token = normalized_text(name).replace(" ", "")
        compact_domain = normalized_text(domain).replace(" ", "")
        return bool(token and compact_domain and token in compact_domain)

    for variant in variants:
        payload = {
            "query": f"{variant} official blog news updates product announcements",
            "type": "neural",
            "numResults": 3,
            "contents": {"text": False, "highlights": False},
        }
        try:
            response = requests.post("https://api.exa.ai/search", headers=headers, json=payload, timeout=AI_UPDATES_EXA_TIMEOUT)
            if response.status_code >= 400:
                continue
            results = response.json().get("results") or []
        except Exception:
            continue
        for result in results:
            domain = canonical_official_site(result.get("url") or "").split("/", 1)[0]
            if domain and (domain_contains_name(domain, variant) or domain_contains_name(domain, tool) or domain_contains_name(domain, company)):
                return domain
    return ""


# WHAT: Auto-detects one tool's official site metadata.
# HOW: Uses default seeds first, then Exa domain discovery, then HTTP verification.
# INPUT: Tool name, company name, and force flag.
# OUTPUT: Official-site metadata dictionary.
def auto_detect_official_site(tool_name: str = "", company_name: str = "", *, force: bool = False) -> dict:
    tool = clean_text(tool_name or "")
    company = clean_text(company_name or tool)
    key = tool_record_key({"tool": tool, "company": company})
    if not key:
        return {"tool": tool, "official_site": "", "official_site_verified": False, "official_site_status": "not_found"}

    existing = load_official_tool_sites().get(key, {})
    if existing.get("official_site") and existing.get("verified") and not force:
        return {
            "tool": tool,
            "official_site": canonical_official_site(existing.get("official_site") or ""),
            "official_site_verified": True,
            "official_site_status": "active",
            "official_site_reason": existing.get("reason") or "registry_cache",
        }

    seeded_site = canonical_official_site(DEFAULT_OFFICIAL_TOOL_SITES.get(key) or "")
    detected_site = seeded_site or canonical_official_site(get_official_domain(tool, company))
    verified, status = verify_official_site(detected_site) if detected_site else (False, "not_found")
    status = normalize_official_site_status(status, site=detected_site, verified=verified)
    return {
        "tool": tool,
        "official_site": detected_site,
        "official_site_verified": verified,
        "official_site_status": status,
        "official_site_reason": "default_seed" if seeded_site else ("auto_detected_domain" if detected_site else "not_found"),
    }


# WHAT: Loads official sites from defaults and the monthly registry.
# HOW: Reads monthly_tools-site.json and overlays saved records on default seeds.
# INPUT: No parameters.
# OUTPUT: Mapping of normalized tool/company key to official-site record.
def load_official_tool_sites() -> dict:
    data = load_json(MONTHLY_TOOLS_FILE, {"tool_records": [], "tools": []})
    sites = {
        key: {
            "official_site": canonical_official_site(site),
            "source": "default_seed",
            "verified": False,
            "status": "active",
            "reason": "default_seed",
        }
        for key, site in DEFAULT_OFFICIAL_TOOL_SITES.items()
    }
    raw_tools = data.get("tool_records") or data.get("tools") or []
    if isinstance(raw_tools, dict):
        raw_tools = list(raw_tools.values())
    for value in raw_tools:
        if not isinstance(value, dict):
            continue
        clean_key = tool_record_key(value)
        site = canonical_official_site(value.get("official_site") or value.get("site") or "")
        if clean_key and site:
            verified = bool(value.get("official_site_verified") or value.get("verified"))
            record = dict(value)
            record["official_site"] = site
            record["verified"] = verified
            record["status"] = normalize_official_site_status(
                value.get("official_site_status") or value.get("status") or "",
                site=site,
                verified=verified,
            )
            record["reason"] = value.get("official_site_reason") or value.get("reason") or ""
            sites[clean_key] = record
    return sites


# WHAT: Fills missing official sites from default seeds and normalizes statuses.
# HOW: Uses DEFAULT_OFFICIAL_TOOL_SITES and prunes nameless records.
# INPUT: Tool registry records.
# OUTPUT: Clean records list.
def apply_default_official_sites(records: list[dict]) -> list[dict]:
    output: list[dict] = []
    for item in records or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        tool = clean_text(row.get("tool") or row.get("name") or "")
        if not tool:
            continue
        company = clean_text(row.get("company") or "")
        site = canonical_official_site(row.get("official_site") or "")
        if not site:
            site = DEFAULT_OFFICIAL_TOOL_SITES.get(normalized_text(tool)) or DEFAULT_OFFICIAL_TOOL_SITES.get(normalized_text(company))
            site = canonical_official_site(site or "")
            if site:
                row["official_site"] = site
                row["official_site_verified"] = bool(row.get("official_site_verified"))
                row["official_site_reason"] = row.get("official_site_reason") or "default_seed"
        if row.get("official_site"):
            row["official_site_status"] = normalize_official_site_status(
                row.get("official_site_status") or "",
                site=row.get("official_site") or "",
                verified=bool(row.get("official_site_verified")),
            )
        output.append(row)
    return output


# WHAT: Saves discovered official sites into monthly_tools-site.json.
# HOW: Merges by normalized tool key and writes the unified registry.
# INPUT: Enriched tool records and discovered-site mapping.
# OUTPUT: None; writes JSON.
def save_official_tool_sites(tools: list[dict], discovered: dict[str, dict]) -> None:
    existing = load_json(MONTHLY_TOOLS_FILE, {"tool_records": [], "tools": []})
    records = list(existing.get("tool_records") or [])
    by_key = {tool_record_key(item): dict(item) for item in records if tool_record_key(item) and (item or {}).get("tool")}
    today = utc_now().date().isoformat()
    for item in tools or []:
        if not isinstance(item, dict):
            continue
        key = tool_record_key(item)
        if not key or not clean_text(item.get("tool") or ""):
            continue
        record = discovered.get(key) or {}
        site = canonical_official_site(record.get("official_site") or item.get("official_site") or "")
        if not site:
            continue
        current = by_key.get(key, dict(item))
        verified = bool(record.get("verified") or item.get("official_site_verified"))
        current.update({
            "official_site": site,
            "official_site_verified": verified,
            "official_site_status": normalize_official_site_status(record.get("status") or item.get("official_site_status") or "", site=site, verified=verified),
            "official_site_reason": record.get("reason") or item.get("official_site_reason") or "",
            "updated": today,
        })
        by_key[key] = current
    output = apply_default_official_sites(list(by_key.values()))
    safe_write_json(
        MONTHLY_TOOLS_FILE,
        {
            **existing,
            "schema": "monthly_tools_site_v1",
            "updated": today,
            "tools": [item.get("tool") for item in output if item.get("tool")],
            "tool_records": output,
        },
    )


# WHAT: Enriches tool records with cached/default/discovered official sites.
# HOW: Reads registry/defaults and optionally calls auto_detect_official_site.
# INPUT: Tools list and discover_missing flag.
# OUTPUT: Enriched tool records.
def enrich_tools_with_official_sites(tools: list[dict], *, discover_missing: bool = False) -> list[dict]:
    site_map = load_official_tool_sites()
    discovered: dict[str, dict] = {}
    enriched = []
    searched = 0
    for raw in tools or []:
        item = dict(raw)
        key = tool_record_key(item)
        existing = site_map.get(key) if key else None
        site = canonical_official_site(item.get("official_site") or "")
        if not site and isinstance(existing, dict):
            site = canonical_official_site(existing.get("official_site") or "")
            item["official_site"] = site
            item["official_site_verified"] = bool(existing.get("verified"))
            item["official_site_status"] = existing.get("status") or "active"
            item["official_site_reason"] = existing.get("reason") or existing.get("source") or ""
        if discover_missing and not site and searched < max(0, AI_UPDATES_TOOL_SITE_DISCOVERY_LIMIT):
            searched += 1
            detection = auto_detect_official_site(item.get("tool") or "", item.get("company") or "")
            site = canonical_official_site(detection.get("official_site") or "")
            item["official_site"] = site
            item["official_site_verified"] = bool(detection.get("official_site_verified"))
            item["official_site_status"] = detection.get("official_site_status") or ""
            item["official_site_reason"] = detection.get("official_site_reason") or ""
            if key and site:
                discovered[key] = {
                    "official_site": site,
                    "verified": item["official_site_verified"],
                    "status": item["official_site_status"],
                    "source": "auto_discovery",
                    "reason": item["official_site_reason"],
                }
        elif site:
            item["official_site_status"] = normalize_official_site_status(item.get("official_site_status") or "", site=site, verified=bool(item.get("official_site_verified")))
        enriched.append(item)
    if discovered or not MONTHLY_TOOLS_FILE.exists():
        save_official_tool_sites(enriched, discovered)
    log_event("tool_official_sites.checked", tools=len(enriched), searched=searched, discovered=len(discovered), file=file_status(MONTHLY_TOOLS_FILE))
    return enriched


# WHAT: Returns one cached official update/news site for a tool.
# HOW: Looks up tool/company in defaults plus monthly registry.
# INPUT: Tool and company names.
# OUTPUT: Canonical official-site string or empty string.
def official_tool_site(tool: str = "", company: str = "") -> str:
    site_map = load_official_tool_sites()
    for value in (tool, company):
        key = normalized_text(value)
        record = site_map.get(key) if key else None
        if isinstance(record, dict) and record.get("official_site"):
            return canonical_official_site(record.get("official_site") or "")
    return ""


# WHAT: Builds a site: query prefix from an official site.
# HOW: Uses canonical official-site string from registry/defaults.
# INPUT: Official-site string.
# OUTPUT: Search prefix string.
def official_site_query_prefix(site: str = "") -> str:
    clean = canonical_official_site(site)
    return f"site:{clean} " if clean else ""


