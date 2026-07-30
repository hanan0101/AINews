# This file is part of the AI newsletter system.
"""Generic HTTP/text fetch helpers shared by news, course, and film fetching.

Nothing in this module is specific to any one content type - it exists so
`courses.py` and `films.py` don't have to reach into `news_discovery.py` for
plain HTTP/text plumbing that has nothing to do with news discovery.
"""

from __future__ import annotations

import os
import re
import sys

import requests

from backend.config.settings import source_domain

# Brave/Startpage/DuckDuckGo are currently CAPTCHA/rate-limited on this
# self-hosted SearXNG instance (confirmed live testing 2026-07). Every
# SearXNG request should request only the engines that are actually
# answering right now; the others stay enabled in searxng/settings.yml so
# SearXNG itself can use them once unblocked.
SEARXNG_RELIABLE_ENGINES = (os.getenv("AI_UPDATES_SEARXNG_ENGINES") or "google,bing").strip()

# 2026-07-18: identifying as a bot in the User-Agent gets a real, measured
# share of page fetches 403'd or timed out by sites with basic bot blocking
# (confirmed live: 11 HTTPError + 3 ReadTimeout out of 144 SearXNG results in
# one run) - a browser UA is not deceptive here, it's what any reader's
# browser would send to load the same public page.
PAGE_FETCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def safe_print(message: str) -> None:
    """Print safely when stdout is redirected through a narrow Windows encoding."""
    text = str(message)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")
    print(safe_text, flush=True)


def exa_http_error(response: requests.Response) -> str:
    """Return a stable Exa error code without exposing request credentials."""
    status = getattr(response, "status_code", 0)
    if status == 402:
        body = ""
        try:
            body = response.text[:800]
        except Exception:
            body = ""
        lowered = body.lower()
        if "no_more_credits" in lowered or "credits limit" in lowered or "top up" in lowered:
            return "exa_no_credits:402"
        return "exa_billing_required:402"
    return f"exa_request_failed:{status}"


def query_site_domains(query: str = "") -> set[str]:
    domains = set()
    for raw_site in re.findall(r"site:([^\s)\"']+)", str(query or ""), flags=re.IGNORECASE):
        site = raw_site.strip().rstrip(".,;")
        if not site:
            continue
        domain = source_domain(f"https://{site}")
        if domain:
            domains.add(domain)
    return domains


def query_site_domain_matches_url(query: str = "", url: str = "") -> bool:
    domains = query_site_domains(query)
    if not domains:
        return True
    result_domain = source_domain(url)
    if not result_domain:
        return False
    return any(result_domain == domain or result_domain.endswith(f".{domain}") for domain in domains)
