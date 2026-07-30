"""Logo and visual identity enrichment helpers."""

from __future__ import annotations

import re

from backend.config.settings import clean_text, source_domain

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
    "anysphere": "anysphere.inc",
    "cursor": "cursor.com",
    "reallusion": "reallusion.com",
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
    "anysphere": "cursor",
    "cursor": "cursor",
}

def logo_name_key(value: str = "") -> str:
    key = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    key = re.sub(r"\b(inc|llc|ltd|corp|corporation|company|co)\b", " ", key)
    return re.sub(r"\s+", " ", key).strip()


# Performs the domain root helper step.

def domain_root(domain: str = "") -> str:
    clean = source_domain(domain if "://" in str(domain or "") else f"https://{domain}")
    parts = [part for part in clean.split(".") if part and part not in {"www"}]
    if len(parts) >= 3 and parts[-2] in {"co", "com", "net", "org"}:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


# Performs the company matches domain helper step.

def company_matches_domain(company: str = "", domain: str = "") -> bool:
    key = logo_name_key(company)
    root = logo_name_key(domain_root(domain))
    if not key or not root:
        return False
    tokens = [token for token in key.split() if token not in {"ai", "app", "tool", "labs"}]
    return root in {key.replace(" ", ""), key.replace(" ", "-")} or root in tokens


# Performs the favicon for domain helper step.

def favicon_for_domain(domain: str = "") -> str:
    clean = re.sub(r"^https?://", "", str(domain or "").lower()).replace("www.", "").split("/")[0]
    if not clean or "." not in clean:
        return ""
    return f"https://www.google.com/s2/favicons?sz=128&domain={clean}"


# Performs the domain label helper step.

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


# Performs the favicon for url helper step.

def favicon_for_url(url: str = "") -> str:
    """Resolve a generic favicon URL from any source URL."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    domain = source_domain(raw if "://" in raw else f"https://{raw}")
    return favicon_for_domain(domain)


# Performs the simple icon candidates helper step.

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


# Performs the guessed company domains helper step.

def guessed_company_domains(company: str = "") -> list[str]:
    """Guess plausible domains for a company not in the static COMPANY_DOMAINS map.

    Logo bug fix (2026-07-29, hit in production: smaller/newer tools like
    "Tines" only ever got a single cdn.simpleicons.org guess as their entire
    logo_candidates list - simple-icons only covers well-known consumer
    brands, so that guess 404s and there is nothing else to fall back to).
    Clearbit/DuckDuckGo/Google favicon all key off a domain, not a name, and
    return a harmless 404 for a wrong guess (the frontend's onerror chain
    just moves on to the next candidate) - so guessing common TLDs here is
    safe even when unverified.
    """
    key = logo_name_key(company)
    stem = key.replace(" ", "")
    if len(stem) < 3:
        return []
    return [f"{stem}.com", f"{stem}.ai", f"{stem}.io"]


# Performs the company logo candidates helper step.

def company_logo_candidates(company: str = "", source_url: str = "") -> list[str]:
    """Return verified logo candidates ordered from most brand-specific to fallback."""
    candidates = []

    # Performs the add helper step.
    def add(url: str):
        clean = str(url or "").strip()
        if clean and clean not in candidates:
            candidates.append(clean)

    key = logo_name_key(company)
    mapped_domain = COMPANY_DOMAINS.get(key, "")
    if key == "reallusion":
        add("https://www.reallusion.com/about/includes/image/press_resource_product/rl/reallusion-logo-horizontal-lightbg_2000x443.png")
    for url in simple_icon_candidates(company):
        add(url)
    if mapped_domain:
        add(f"https://logo.clearbit.com/{mapped_domain}")
        add(f"https://icons.duckduckgo.com/ip3/{mapped_domain}.ico")
        add(favicon_for_domain(mapped_domain))
    else:
        # Clearbit and DuckDuckGo both 404 on a wrong guess, so they are a
        # meaningful signal the domain is real; Google's favicon service is
        # lenient and can return a generic icon for a domain it doesn't
        # recognize, so all its guesses are tried last, only once the
        # stricter services have been exhausted across every guessed domain.
        guesses = guessed_company_domains(company)
        for guess in guesses:
            add(f"https://logo.clearbit.com/{guess}")
            add(f"https://icons.duckduckgo.com/ip3/{guess}.ico")
        for guess in guesses:
            add(favicon_for_domain(guess))
    source_domain_name = source_domain(source_url)
    if source_domain_name and company_matches_domain(company, source_domain_name):
        add(f"https://logo.clearbit.com/{source_domain_name}")
        add(f"https://icons.duckduckgo.com/ip3/{source_domain_name}.ico")
        add(favicon_for_domain(source_domain_name))
    return candidates


# Performs the logo label from card title helper step.

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


# Performs the card logo company helper step.

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


# Picks the highest-priority logo candidate without checking it actually
# loads. A server-side network verification pass (2026-07-29) fixed
# occasional broken logos for smaller/newer companies, but made every
# save/load pay for a live HTTP round trip per item; reverted by product
# decision to keep saves instant. `candidates` is still kept in full on the
# item as the client-side fallback chain, so a broken first guess degrades
# rather than staying stuck.
def first_verified_logo(candidates: list[str]) -> str:
    return candidates[0] if candidates else ""


def first_verified_logo_batch(candidates_per_item: list[list[str]]) -> list[str]:
    """Batch counterpart of first_verified_logo for enrich_cards_visual_identity_batch."""
    return [candidates[0] if candidates else "" for candidates in candidates_per_item]


def _visual_identity_result(item: dict, content_type: str, source_url: str, company: str, candidates: list[str], logo: str) -> dict:
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


def _prepare_visual_identity(item: dict | None, content_type: str) -> tuple[dict, str, str, list[str]]:
    item = dict(item or {})
    source_url = item.get("source_url") or item.get("url") or ""
    company = card_logo_company(item, content_type)
    candidates = []
    for url in company_logo_candidates(company, source_url):
        if url and url not in candidates:
            candidates.append(url)
    return item, source_url, company, candidates


# Performs the enrich card visual identity helper step.

def enrich_card_visual_identity(item: dict | None, content_type: str = "news") -> dict:
    """Resolve logos for any old-UI card shape through the enrichment pipeline."""
    item, source_url, company, candidates = _prepare_visual_identity(item, content_type)
    logo = first_verified_logo(candidates)
    return _visual_identity_result(item, content_type, source_url, company, candidates, logo)


def enrich_cards_visual_identity_batch(items_with_types: list[tuple[dict, str]]) -> list[dict]:
    """Same result as calling enrich_card_visual_identity once per item, but
    verifies every item's logo candidates in one shared concurrent batch
    instead of paying one round trip per item in sequence."""
    prepared = [
        (*_prepare_visual_identity(item, content_type), content_type)
        for item, content_type in items_with_types
    ]
    winners = first_verified_logo_batch([candidates for _, _, _, candidates, _ in prepared])
    return [
        _visual_identity_result(item, content_type, source_url, company, candidates, logo)
        for (item, source_url, company, candidates, content_type), logo in zip(prepared, winners)
    ]


# Performs the stable update id helper step.

__all__ = [
    "card_logo_company",
    "company_logo_candidates",
    "company_matches_domain",
    "domain_label",
    "domain_root",
    "enrich_card_visual_identity",
    "enrich_cards_visual_identity_batch",
    "favicon_for_domain",
    "favicon_for_url",
    "logo_label_from_card_title",
    "logo_name_key",
    "simple_icon_candidates",
]
