# This file is part of the AI newsletter system.
import http.server
import ipaddress
import json
import os
import socket
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from backend.utils.debug_logging import configure_console_encoding, trace
# PDF export helpers: render the newsletter preview HTML into downloadable PDF bytes.
from backend.utils.pdf_export_service import export_preview_pdf_bytes, PDF_EXPORT_PROFILE
from backend.utils.pptx_export_service import export_newsletter_pptx_bytes
from backend.utils.text_normalization import cleanup_text_fields, repair_mojibake_text
from backend.server.card_items import (
    clamp_logo_position,# keeps logo x/y positions inside safe UI limits.
    clamp_logo_size,# keeps logo size inside safe UI limits.
    normalize_item,
)
from backend.server.single_card_refill import (
    cancel_single_refill,
    current_single_refill_state,
    single_item_refill,
)
from backend.storage.newsletter_store import (
    DISPLAY_COUNTS,
    FEATURE_MODES,
    FRONTEND_DIR,
    NEWS_SELECTION_AUDIT_FILE,
    REQUIRED_COUNTS,
    SECTION_KEYS,
    SECTION_TO_CONTENT_TYPE,
    find_item,
    get_feature_item,
    ensure_published_store,
    load_newsletter_settings,
    load_news_fetch_state_server,
    load_store,
    load_published_store,
    missing_display_sections,
    missing_sections,
    newsletter_template_from_settings,
    previous_generation_counts,
    reorder_positions,
    restore_previous_card_at_index,
    safe_int,
    save_newsletter_settings,
    save_store,
    update_card_from_client,
    visible_items,
    StoreConflict,
)
from backend.storage.manage_versions.version_routes import (
    handle_versions_delete,
    handle_versions_get,
    handle_versions_post,
    handle_versions_put,
)
from backend.storage.manage_versions.versions_db import init_versions_db
from backend.storage.manage_versions.pdf_import import attach_newsletter_json_to_pdf
from backend.server.generator_bridge import (
    AUTO_FETCH_COOLDOWN,
    GENERATOR_STATE,
    NEWS_JSON_ONLY_MODE,
    generator_public_state,
    cancel_generator,
    start_generator_background,
)

# Load the pipeline functions used by fetch/refill routes.
# Pipeline import errors should stop startup so code/configuration issues are visible immediately.
from backend.pipeline.orchestrator import start_background_daemon
from backend.pipeline.modeling.model_client import (
    MODEL_FLASH_MODEL,
    MODEL_PROVIDER,
    generate_json as model_generate_json,
    model_available,
)
from backend.auth.authentication import (
    auth_token_cookies,
    authenticate,
    clear_auth_cookies,
    require_admin,
    require_user,
    user_from_headers_with_refresh,
)
from backend.auth.keycloak_bootstrap import bootstrap_keycloak_if_missing
from backend.config.settings import AI_UPDATES_RUN_REPORT_FILE

# Runtime paths used by the static UI server and local Python launcher.
ROOT_DIR = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT_DIR.parent / "venv" / "Scripts" / "python.exe"
PYTHON_EXECUTABLE = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))
API_BASE = "/api"
DEFAULT_UI_PATH = "/News.html"
LOGIN_SUCCESS_PATH = f"{DEFAULT_UI_PATH}?from=login"
load_dotenv(ROOT_DIR / ".env", override=True)
configure_console_encoding()

# Preserve the newsletter that existed at startup as the initial public issue.
# Subsequent Generate runs stay admin-only drafts until Save publishes them.
ensure_published_store()

# AUTH BLOCK: Paths that can be opened before a Keycloak session exists.
# Reason: Login and browser metadata must remain reachable while every app/API
# route is protected by either user or admin permissions.
PUBLIC_GET_PATHS = {"/login", "/favicon.ico"}
PUBLIC_POST_PATHS = {"/auth/login"}

# AUTH BLOCK: Read-only paths available to both user and admin roles.
# Reason: Users can view/download the newsletter and versions, but cannot edit.
USER_GET_PREFIXES = (
    "/",
    API_BASE + "/news",
    API_BASE + "/versions",
    API_BASE + "/image-proxy",
    API_BASE + "/auth/me",
)

# AUTH BLOCK: Operational diagnostics remain admin-only.
# Reason: These routes expose pipeline state and system internals.
ADMIN_GET_PREFIXES = (
    API_BASE + "/debug",
    API_BASE + "/ai-updates",
    API_BASE + "/refill/progress",
)

# AUTH BLOCK: Only explicit read/download POSTs are user-accessible.
# Reason: Existing download flow posts rendered HTML to export a PDF.
USER_POST_PATHS = {"/auth/logout", API_BASE + "/export-pdf", API_BASE + "/export-pptx"}

TRACE_HTTP = os.getenv("SERVER_TRACE_HTTP", "1").strip().lower() not in {"0", "false", "no", "off"}

# AVAILABILITY BLOCK: Cap JSON request bodies so a single request can't
# exhaust memory. Every legitimate JSON payload this app sends (card edits,
# refill requests, settings) is well under this. Multipart file uploads (PDF
# import) are exempt - they already have their own 25MB cap in
# read_multipart_upload (backend/storage/manage_versions/pdf_import.py).
MAX_JSON_BODY_BYTES = max(1024, int(os.getenv("MAX_JSON_BODY_BYTES", str(2 * 1024 * 1024)) or str(2 * 1024 * 1024)))

# AVAILABILITY BLOCK: PDF and PPTX export both launch a full Chromium process
# (see backend/utils/pdf_export_service.py, pptx_export_service.py) - cap how
# many can run at once so a burst of export requests can't exhaust memory/CPU.
PDF_EXPORT_MAX_CONCURRENT = max(1, int(os.getenv("PDF_EXPORT_MAX_CONCURRENT", "1") or "1"))
PDF_EXPORT_SEMAPHORE = threading.Semaphore(PDF_EXPORT_MAX_CONCURRENT)

# AVAILABILITY BLOCK: Simple per-user sliding-window rate limit on PDF/PPTX
# export, on top of the server-wide concurrency cap above.
PDF_EXPORT_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("PDF_EXPORT_RATE_LIMIT_PER_MINUTE", "6") or "6"))
_PDF_EXPORT_RATE_LIMIT_LOCK = threading.Lock()
_pdf_export_recent_requests = {}


def _pdf_export_rate_limit_allows(username):
    now = time.time()
    cutoff = now - 60
    key = username or "anonymous"
    with _PDF_EXPORT_RATE_LIMIT_LOCK:
        times = _pdf_export_recent_requests.setdefault(key, [])
        while times and times[0] < cutoff:
            times.pop(0)
        if len(times) >= PDF_EXPORT_RATE_LIMIT_PER_MINUTE:
            return False
        times.append(now)
        return True

# SSRF BLOCK: Hostnames the image proxy must never reach, on top of the IP
# range checks below. These are internal-only in every deployment of this
# app (see docker-compose.yml's service names / localhost), so there is no
# legitimate image source among them.
IMAGE_PROXY_BLOCKED_HOSTNAMES = {
    "localhost", "keycloak", "qdrant", "searxng", "postgres", "ainewsletter",
}
IMAGE_PROXY_ALLOWED_PORTS = {80, 443}


# SSRF BLOCK: True if this resolved IP must never be reached by the image
# proxy (loopback, private/RFC1918, link-local - which also covers the
# 169.254.169.254 cloud metadata address, and other non-public ranges).
# Checks the IPv4-mapped address too so "::ffff:127.0.0.1" can't slip past
# an IPv6-only check.
def _is_blocked_proxy_ip(ip_str):
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    candidates = [ip]
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped:
        candidates.append(mapped)
    return any(
        candidate.is_private
        or candidate.is_loopback
        or candidate.is_link_local
        or candidate.is_reserved
        or candidate.is_multicast
        or candidate.is_unspecified
        for candidate in candidates
    )


# SSRF BLOCK: Resolve and validate a candidate image URL before the proxy is
# allowed to fetch it. Reason: send_image_proxy used to fetch any http/https
# URL a caller supplied, which could reach internal services, private
# addresses, or the cloud metadata endpoint. Called both on the original
# request and again on every redirect hop (see _SafeImageRedirectHandler).
def _validate_image_proxy_url(url):
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in IMAGE_PROXY_BLOCKED_HOSTNAMES or hostname.endswith((".local", ".internal")):
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in IMAGE_PROXY_ALLOWED_PORTS:
        return False
    try:
        resolved = socket.getaddrinfo(hostname, None)
    except Exception:
        return False
    if not resolved:
        return False
    return all(not _is_blocked_proxy_ip(info[4][0]) for info in resolved)


# SSRF BLOCK: Re-validate the destination on every redirect hop instead of
# letting urllib silently follow a redirect straight into a blocked address.
class _SafeImageRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _validate_image_proxy_url(newurl):
            raise urllib.error.HTTPError(newurl, 403, "Blocked redirect destination", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Performs the safe login next helper step.
def safe_login_next(value):
    raw = (value or "").strip()
    if not raw:
        return LOGIN_SUCCESS_PATH
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return LOGIN_SUCCESS_PATH
    if parsed.path == "/login" or parsed.path.startswith("/auth/") or parsed.path.startswith(API_BASE):
        return LOGIN_SUCCESS_PATH
    return urllib.parse.urlunparse(("", "", parsed.path, "", parsed.query, ""))


# Performs the escape attr helper step.
def escape_attr(value):
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )




# Server role: Parse a JSON request body safely.
def read_json_body(handler):
    length = int(handler.headers.get("Content-Length", 0) or 0)
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


# Performs the sync item in saved views helper step.
def sync_item_in_saved_views(store, section, updated_item):
    """Keep manual edits visible after reload.

    The level-balanced UI can render cards from `items`, `backup_news`,
    `news_bank`, `courses_bank`, or `recommended_view`. Before this sync, a
    manual edit saved only to the legacy list, then the next frontend reload
    could display the old copy from the bank. This updates every saved copy
    with the same id.
    """
    if not isinstance(updated_item, dict):
        return
    item_id = str(updated_item.get("id") or "").strip()
    if not item_id:
        return

    # Performs the replace in list helper step.
    def replace_in_list(values):
        if not isinstance(values, list):
            return values
        changed = False
        output = []
        for entry in values:
            if isinstance(entry, dict) and str(entry.get("id") or "").strip() == item_id:
                output.append({**entry, **updated_item})
                changed = True
            else:
                output.append(entry)
        return output if changed else values

    if section == "items":
        for level, values in list((store.get("news_bank") or {}).items()):
            store["news_bank"][level] = replace_in_list(values)
        updated_level = str(updated_item.get("level") or "").strip().lower()
        if updated_level in {"beginner", "intermediate", "advanced"} and isinstance(store.get("news_bank"), dict):
            existed_in_bank = any(
                isinstance(entry, dict) and str(entry.get("id") or "").strip() == item_id
                for values in store["news_bank"].values() if isinstance(values, list)
                for entry in values
            )
            if existed_in_bank:
                for level, values in list(store["news_bank"].items()):
                    store["news_bank"][level] = [
                        entry for entry in (values or [])
                        if not (isinstance(entry, dict) and str(entry.get("id") or "").strip() == item_id)
                    ]
                store["news_bank"].setdefault(updated_level, []).append(dict(updated_item))
        if isinstance(store.get("recommended_view"), dict):
            store["recommended_view"]["news"] = replace_in_list(store["recommended_view"].get("news"))
    elif section == "courses":
        for level, values in list((store.get("courses_bank") or {}).items()):
            store["courses_bank"][level] = replace_in_list(values)
        updated_level = str(updated_item.get("level") or "").strip().lower()
        if updated_level in {"beginner", "intermediate", "advanced"} and isinstance(store.get("courses_bank"), dict):
            existed_in_bank = any(
                isinstance(entry, dict) and str(entry.get("id") or "").strip() == item_id
                for values in store["courses_bank"].values() if isinstance(values, list)
                for entry in values
            )
            if existed_in_bank:
                for level, values in list(store["courses_bank"].items()):
                    store["courses_bank"][level] = [
                        entry for entry in (values or [])
                        if not (isinstance(entry, dict) and str(entry.get("id") or "").strip() == item_id)
                    ]
                store["courses_bank"].setdefault(updated_level, []).append(dict(updated_item))
        if isinstance(store.get("recommended_view"), dict):
            store["recommended_view"]["courses"] = replace_in_list(store["recommended_view"].get("courses"))
    elif section == "movies" and isinstance(store.get("recommended_view"), dict):
        movie = store["recommended_view"].get("movie")
        if isinstance(movie, dict) and str(movie.get("id") or "").strip() == item_id:
            store["recommended_view"]["movie"] = {**movie, **updated_item}

    # Saved Mode/Level layouts keep their order, but manual content/logo edits
    # must update the matching card copy inside every saved context.
    saved_views = store.get("saved_views") or {}
    if isinstance(saved_views, dict):
        list_key = {"items": "items", "courses": "courses", "movies": "movies"}.get(section)
        for mode_views in saved_views.values():
            if not isinstance(mode_views, dict):
                continue
            for saved_view in mode_views.values():
                if not isinstance(saved_view, dict):
                    continue
                if list_key:
                    saved_view[list_key] = replace_in_list(saved_view.get(list_key))
                feature = saved_view.get("feature_item")
                if section == "movies" and isinstance(feature, dict) and str(feature.get("id") or "").strip() == item_id:
                    saved_view["feature_item"] = {**feature, **updated_item}


def remove_item_from_store(store, section, item_id):
    """Remove one managed card from every persisted view that can render it."""
    item_id = str(item_id or "").strip()
    if section not in SECTION_KEYS or not item_id:
        return False

    removed = False

    def without_item(values):
        nonlocal removed
        if not isinstance(values, list):
            return values
        filtered = [
            entry for entry in values
            if not (isinstance(entry, dict) and str(entry.get("id") or "").strip() == item_id)
        ]
        if len(filtered) != len(values):
            removed = True
        return filtered

    store[section] = without_item(store.get(section))
    bank_key = {"items": "news_bank", "courses": "courses_bank"}.get(section)
    if bank_key and isinstance(store.get(bank_key), dict):
        for level, values in list(store[bank_key].items()):
            store[bank_key][level] = without_item(values)

    recommended = store.get("recommended_view")
    if isinstance(recommended, dict):
        if section == "items":
            recommended["news"] = without_item(recommended.get("news"))
        elif section == "courses":
            recommended["courses"] = without_item(recommended.get("courses"))
        elif section == "movies":
            movie = recommended.get("movie")
            if isinstance(movie, dict) and str(movie.get("id") or "").strip() == item_id:
                recommended["movie"] = None
                removed = True

    saved_views = store.get("saved_views")
    if isinstance(saved_views, dict):
        for mode_views in saved_views.values():
            if not isinstance(mode_views, dict):
                continue
            for saved_view in mode_views.values():
                if not isinstance(saved_view, dict):
                    continue
                saved_view[section] = without_item(saved_view.get(section))
                feature = saved_view.get("feature_item")
                if isinstance(feature, dict) and str(feature.get("id") or "").strip() == item_id:
                    saved_view["feature_item"] = None
                    removed = True

    feature = store.get("feature_item")
    if isinstance(feature, dict) and str(feature.get("id") or "").strip() == item_id:
        store["feature_item"] = None
        removed = True
    return removed


# Server role: Resolve cards rendered from a Mode/Level bank into the editable
# primary list. Older/manual versions can contain a card in news_bank or a
# saved view without also carrying it in items/backup_news. The UI can display
# that card in Mode 6, but legacy edit routes used to return 404 because they
# searched only the primary list.
def find_editable_store_item(store, section, item_id):
    primary = store.get(section)
    if not isinstance(primary, list):
        primary = []
        store[section] = primary
    item = find_item(primary, item_id)
    if item:
        return item

    bank_key = {"items": "news_bank", "courses": "courses_bank"}.get(section)
    candidate = None
    bank = store.get(bank_key) if bank_key else None
    if isinstance(bank, dict):
        for values in bank.values():
            if isinstance(values, list):
                candidate = find_item(values, item_id)
                if candidate:
                    break

    recommended = store.get("recommended_view")
    recommended_key = {"items": "news", "courses": "courses"}.get(section)
    if not candidate and isinstance(recommended, dict):
        if recommended_key:
            candidate = find_item(recommended.get(recommended_key) or [], item_id)
        elif section == "movies":
            movie = recommended.get("movie")
            if isinstance(movie, dict) and str(movie.get("id") or "").strip() == str(item_id or "").strip():
                candidate = movie

    if not candidate:
        saved_views = store.get("saved_views")
        list_key = {"items": "items", "courses": "courses", "movies": "movies"}.get(section)
        if isinstance(saved_views, dict):
            for mode_views in saved_views.values():
                if not isinstance(mode_views, dict):
                    continue
                for saved_view in mode_views.values():
                    if not isinstance(saved_view, dict):
                        continue
                    candidate = find_item(saved_view.get(list_key) or [], item_id) if list_key else None
                    if not candidate and section == "movies":
                        feature = saved_view.get("feature_item")
                        if isinstance(feature, dict) and str(feature.get("id") or "").strip() == str(item_id or "").strip():
                            candidate = feature
                    if candidate:
                        break
                if candidate:
                    break

    if not candidate:
        return None
    promoted = dict(candidate)
    primary.append(promoted)
    return promoted


# Server role: Build the standard replacement API response payload.
def replacement_response(store, section, index, result):
    hidden_news = store.get("items", [])[DISPLAY_COUNTS.get("items", REQUIRED_COUNTS["items"]):]
    return {
        **result,
        "section": section,
        "index": index,
        "template": store.get("template", {}),
        "items": visible_items(store, "items"),
        "backup_news": hidden_news,
        "movies": store.get("movies", []),
        "courses": store.get("courses", []),
        "news_bank": store.get("news_bank", {}),
        "courses_bank": store.get("courses_bank", {}),
        "recommended_view": store.get("recommended_view", {}),
        "saved_views": store.get("saved_views", {}),
        "default_view": store.get("default_view", {}),
        "selected_levels": store.get("selected_levels", ["all"]),
        "news_display_count": store.get("news_display_count", 4),
        "metadata": store.get("metadata", {}),
        "feature_mode": store["feature_mode"],
        "feature_item": get_feature_item(store),
        "needs_fetch": missing_display_sections(store),
        "needs_fetch_required": missing_sections(store),
        "previous_counts": previous_generation_counts(),
        "generator": generator_public_state(),
    }


def client_state_news_items(data, fallback_items):
    """Return the full news pool from an undo/redo client snapshot.

    Snapshots expose visible cards as ``items`` and extra cards as
    ``all_items``. Using only ``items`` silently deleted card 7+ after undo,
    which then left nothing for the per-card replacement controls to show.
    """
    if isinstance(data.get("all_items"), list) and data.get("all_items"):
        return data.get("all_items")
    visible = data.get("items") if isinstance(data.get("items"), list) else []
    backup = data.get("backup_news") if isinstance(data.get("backup_news"), list) else []
    if visible or backup:
        return [*visible, *backup]
    return fallback_items


# Server role: Replace a visible card by fetching one fresh pipeline item.
def replace_item_at_index(store, section, item_id):
    return single_item_refill(
        store,
        section,
        item_id=item_id,
        action="replace",
        allow_fetch=True,
        live_fetch=True,
    )


# Server role: Rewrite one card title/body through the configured model provider for manual edits.
def rewrite_text(title, text, instruction):
    if not model_available():
        return {
            "title": title,
            "text": text,
            "mode": f"{MODEL_PROVIDER}_failed",
            "error": f"missing_{MODEL_PROVIDER}_api_key",
        }
    prompt = f"""
أعد صياغة العنوان والنص بالعربية الواضحة مع الحفاظ على معنى المحتوى الأصلي.
أعد النتيجة بصيغة JSON فقط:
{{"title":"","text":""}}
التعليمات: {instruction or 'حسّن الصياغة بدون تغيير المعنى.'}
العنوان: {title}
النص: {text}
""".strip()
    try:
        payload = model_generate_json(
            "You are a precise Arabic editor. Return JSON only.",
            prompt,
            model=MODEL_FLASH_MODEL,
        )
        mode = MODEL_PROVIDER
        return {
            "title": payload.get("title", title).strip() or title,
            "text": payload.get("text", text).strip() or text,
            "mode": mode,
        }
    except Exception as exc:
        return {"title": title, "text": text, "mode": f"{MODEL_PROVIDER}_failed", "error": str(exc)}


# Server role: TCP server tuned for predictable local Windows development.
class ReusableTCPServer(socketserver.TCPServer):
    # Keep this off on Windows. With SO_REUSEADDR enabled, multiple old
    # Python server processes can listen on the same port, so browser requests
    # may hit a stale process and the current terminal appears to show no logs.
    allow_reuse_address = False


# Server role: Serve API/static requests concurrently.
class ThreadedTCPServer(socketserver.ThreadingMixIn, ReusableTCPServer):
    daemon_threads = True


# Server role: HTTP handler for static UI files and JSON API routes.
class BackendHandler(http.server.SimpleHTTPRequestHandler):
    # AVAILABILITY BLOCK: A client that stalls mid-request (never finishes
    # sending headers/body) used to hold its thread open forever. This
    # applies to socket reads only, not to how long a request handler takes
    # to run - a slow PDF export or AI generation isn't blocked on socket
    # I/O, so this doesn't affect either.
    timeout = max(5, int(os.getenv("HTTP_REQUEST_READ_TIMEOUT_SECONDS", "30") or "30"))

    # Server role: Bind the handler to frontend/ static files.
    def __init__(self, *args, **kwargs):
        # Always serve static files from frontend/, even if the process working
        # directory changes or the server is launched from another folder.
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    # Server role: Add UTF-8 charset to text-like static assets.
    def guess_type(self, path):
        content_type = super().guess_type(path)
        if content_type == "text/html":
            return "text/html; charset=utf-8"
        if content_type == "text/css":
            return "text/css; charset=utf-8"
        if content_type in {"application/javascript", "text/javascript"}:
            return f"{content_type}; charset=utf-8"
        return content_type

    # Server role: Route HTTP access logs through trace().
    def log_message(self, format, *args):
        if TRACE_HTTP:
            trace(f"HTTP {self.address_string()} - {format % args}")

    # Server role: Answer CORS preflight requests.
    def do_OPTIONS(self):
        if TRACE_HTTP:
            trace(f"OPTIONS {urllib.parse.urlparse(self.path).path}")
        self.send_response(200)
        self.end_headers()

    # AUTH BLOCK: Send small HTML responses for login and redirects.
    # Reason: The app uses http.server, so auth pages are rendered directly.
    def send_html(self, html, status=200):
        payload = repair_mojibake_text(html).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    # AUTH BLOCK: Login form posts credentials to Keycloak through this server.
    # Reason: Browser never receives the client secret; it only receives a cookie.
    def send_login_page(self, error=""):
        # CHANGE: Display a clear Arabic login error for invalid credentials.
        # Reason: The login route redirects with an error code after logging the real exception.
        error_message = "بيانات الدخول غير صحيحة، يرجى المحاولة مجددًا" if error == "invalid_credentials" else ""
        message = f"<p class=\"error\">{error_message}</p>" if error_message else ""
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        next_path = safe_login_next(query.get("next", [""])[0])
        next_input = escape_attr(next_path)
        html = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>تسجيل الدخول</title>
  <style>
    :root{{
      --bg:#EEDFD0;
      --paper:#F5EDDF;
      --surface:rgba(245,237,223,.20);
      --border:rgba(255,255,255,.34);
      --text:#2e241d;
      --muted:#78675d;
      --line:#C73D39;
      --teal:#91B9B4;
      --peach:#FAC39B;
    }}
    *{{box-sizing:border-box}}
    body{{
      margin:0;
      min-height:100vh;
      display:grid;
      place-items:center;
      background:var(--bg);
      font-family:Segoe UI,Tahoma,Arial,sans-serif;
      color:var(--text);
      padding:24px;
      overflow:hidden;
    }}
    body:before{{
      content:"";
      position:fixed;
      inset:0;
      z-index:0;
      opacity:.20;
      mix-blend-mode:soft-light;
      background-image:radial-gradient(rgba(120,78,43,.18) .45px,transparent .45px);
      background-size:3px 3px;
      pointer-events:none;
    }}
    .login-neural-canvas{{
      position:fixed;
      inset:0;
      width:100%;
      height:100%;
      z-index:0;
      pointer-events:none;
      opacity:.82;
      mix-blend-mode:multiply;
    }}
    main{{
      position:relative;
      z-index:1;
      width:min(380px,calc(100vw - 32px));
      min-height:500px;
      display:flex;
      flex-direction:column;
      align-items:center;
      justify-content:center;
      background:transparent;
      border:1px solid rgba(255, 255, 255, 0.6);
      border-radius:42px;
      padding:36px 42px 34px;
      box-shadow:0 4px 16px rgba(0, 0, 0, 0.08);
      backdrop-filter:blur(2px);
      -webkit-backdrop-filter:blur(2px);
      text-align:center;
    }}
    .brand-logo{{width:88px;height:60px;margin:-12px 0 14px}}
    .transfer-message{{display:none;margin:14px 0 0;color:#4e4038;font-size:15px;font-weight:700}}
    body.logging-in main{{
      width:min(380px,calc(100vw - 32px));
      min-height:500px;
      padding:36px 42px 34px;
      transition:width .18s ease,min-height .18s ease,padding .18s ease;
    }}
    body.logging-in .brand-logo{{
      width:128px;
      height:86px;
      margin:0 0 6px;
      animation:loginLogoFlip .72s ease-in-out infinite;
      transform-origin:center;
      transform-box:fill-box;
    }}
    body.logging-in .transfer-message{{
      display:block;
    }}
    body.logging-in .login-title,
    body.logging-in .subtitle,
    body.logging-in form,
    body.logging-in .error{{
      display:none;
    }}
    @keyframes loginLogoFlip{{
      0%{{transform:rotateY(0deg)}}
      42%{{transform:rotateY(180deg)}}
      68%{{transform:rotateY(180deg)}}
      100%{{transform:rotateY(360deg)}}
    }}
    .login-title{{
      width:100%;
      margin:18px 0 8px;
      color:#2f2118;
      font-size:15px;
      font-weight:800;
      line-height:1.25;
      text-align:right;
    }}
    .subtitle{{
      width:100%;
      margin:0 0 30px;
      color:var(--muted);
      font-size:14px;
      line-height:1.75;
      text-align:right;
      white-space:nowrap;
    }}
    form{{width:80%;display:grid;gap:18px;text-align:right}}
    .field{{
      position:relative;
      min-height:42px;
      border-radius:15px;
      padding:12px 13px 5px;
      margin:0;
      border:0;
      background:transparent;
      box-shadow:none;
      backdrop-filter:none;
      -webkit-backdrop-filter:none;
    }}
    .field:before{{
      content:"";
      position:absolute;
      inset:0;
      border-radius:15px;
      padding:1px;
      background:linear-gradient(122deg,#91B9B4 0%,#BFD0BC 20%,#FAC39B 42%,#E98B74 68%,#C73D39 100%);
      -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
      -webkit-mask-composite:xor;
      mask-composite:exclude;
      pointer-events:none;
      z-index:0;
    }}
    .field:after{{
      content:"";
      position:absolute;
      top:-2px;
      right:12px;
      width:112px;
      height:5px;
      background:var(--bg);
      pointer-events:none;
      z-index:1;
    }}
    .password-wrap:after{{
      right:12px;
      width:84px;
    }}
    legend{{
      position:absolute;
      z-index:2;
      top:-10px;
      right:18px;
      height:20px;
      display:flex;
      align-items:center;
      justify-content:flex-start;
      padding:0 0;
      margin:0;
      color:#4e4038;
      font-size:12px;
      line-height:1;
      font-weight:400;
      background:transparent;
      text-align:right;
    }}
    .password-wrap legend{{right:18px}}
    input{{
      position:relative;
      z-index:1;
      width:100%;
      height:30px;
      border:0;
      border-radius:0;
      padding:0 2px;
      font:inherit;
      font-size:14px;
      font-weight:400 !important;
      background:transparent !important;
      appearance:none;
      -webkit-appearance:none;
      color:var(--text);
      outline:none;
      direction:rtl;
      text-align:right;
      box-shadow:none;
    }}
    input:-webkit-autofill,
    input:-webkit-autofill:hover,
    input:-webkit-autofill:focus{{
      -webkit-text-fill-color:var(--text);
      caret-color:var(--text);
      font-weight:400 !important;
      box-shadow:0 0 0 1000px rgba(245,237,223,0) inset !important;
      -webkit-box-shadow:0 0 0 1000px rgba(245,237,223,0) inset !important;
      transition:background-color 9999s ease-out 0s;
    }}
    input:focus{{
      background:transparent;
      box-shadow:none;
      font-weight:400 !important;
    }}
    .password-wrap{{position:relative}}
    .password-wrap input{{padding-left:2px;padding-right:42px}}
    .password-toggle{{
      position:absolute;
      right:14px;
      bottom:9px;
      width:21px;
      height:21px;
      border:0;
      margin:0;
      padding:0;
      background:transparent;
      color:#776a61;
      cursor:pointer;
      z-index:2;
    }}
    .password-toggle svg{{width:21px;height:21px;display:block}}
    .password-toggle .eye{{display:none}}
    .password-toggle.is-visible .eye{{display:block}}
    .password-toggle.is-visible .eye-off{{display:none}}
    .login-submit{{
      width:72%;
      justify-self:center;
      height:38px;
      margin-top:12px;
      border:0;
      border-radius:999px;
      background:#c97870;
      color:white;
      padding:0 18px;
      font:inherit;
      font-weight:800;
      cursor:pointer;
      box-shadow:0 13px 25px rgba(199,61,57,.18);
      transition:transform .18s ease, box-shadow .18s ease;
    }}
    .login-submit:hover{{transform:translateY(-1px);box-shadow:0 16px 32px rgba(199,61,57,.22)}}
    .error{{margin:18px 0 0;color:#b22620;font-size:13px;line-height:1.6}}
    @media (max-width:520px){{
      main{{border-radius:34px;padding:38px 24px 34px;min-height:520px}}
      .login-submit{{width:82%}}
    }}
  </style>
</head>
<body>
  <canvas id="loginNeuralCanvas" class="login-neural-canvas" aria-hidden="true"></canvas>
  <main>
    <svg class="brand-logo" viewBox="0 0 360 220" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M100 38L134 24V160L100 174Z" fill="#C73D39"/>
      <path d="M164 22L198 8V176L164 190Z" fill="#FAC39B"/>
      <path d="M228 38L262 24V160L228 174Z" fill="#91B9B4" opacity=".62"/>
      <path d="M62 132C98 128 124 144 164 146C200 148 226 142 292 86" stroke="#F8F1EA" stroke-width="4" stroke-linecap="round"/>
      <circle cx="60" cy="132" r="12" fill="#F8F1EA"/>
      <circle cx="136" cy="146" r="12" fill="#F8F1EA"/>
      <circle cx="198" cy="146" r="12" fill="#F8F1EA"/>
      <circle cx="294" cy="86" r="12" fill="#F8F1EA"/>
    </svg>
    <p class="transfer-message">يتم نقلك للنشرة</p>
    <h1 class="login-title">تسجيل الدخول</h1>
    <p class="subtitle">مرحبًا بك في نشرة أخبار الذكاء الاصطناعي</p>
    <form method="post" action="/auth/login" autocomplete="off">
      <input type="hidden" name="next" value="{next_input}">
      <fieldset class="field">
        <legend>اسم المستخدم</legend>
        <input id="username" name="username" autocomplete="off" autocapitalize="off" spellcheck="false" required>
      </fieldset>
      <fieldset class="field password-wrap">
        <legend>كلمة السر</legend>
        <input id="password" name="password" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" required>
        <button class="password-toggle" type="button" aria-label="إظهار كلمة السر" onclick="toggleLoginPassword(this)">
          <svg class="eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M1.8 12s3.8-7 10.2-7 10.2 7 10.2 7-3.8 7-10.2 7-10.2-7-10.2-7Z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
          <svg class="eye-off" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M4 13c2.1 2 4.8 3 8 3s5.9-1 8-3"/>
            <path d="M7 16.2l-1.5 1.9"/>
            <path d="M12 17v2.4"/>
            <path d="M17 16.2l1.5 1.9"/>
          </svg>
        </button>
      </fieldset>
      <button class="login-submit" type="submit">دخول</button>
    </form>
    {message}
  </main>
  <script>
    function initNeuralNetworkCanvas(canvasId){{
      const canvas = document.getElementById(canvasId);
      if(!canvas) return;
      const ctx = canvas.getContext('2d');
      let W = 0;
      let H = 0;
      let nodes = [];
      let running = true;
      let tick = 0;
      const COUNT = 68;
      const MAX_DIST = 155;

      function resize(){{
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        W = window.innerWidth;
        H = window.innerHeight;
        canvas.width = Math.floor(W * dpr);
        canvas.height = Math.floor(H * dpr);
        canvas.style.width = `${{W}}px`;
        canvas.style.height = `${{H}}px`;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }}

      function init(){{
        nodes = Array.from({{length: COUNT}}, () => ({{
          x: Math.random() * W,
          y: Math.random() * H,
          vx: (Math.random() - 0.5) * 0.42,
          vy: (Math.random() - 0.5) * 0.42,
          r: Math.random() * 2.2 + 1.35,
          phase: Math.random() * Math.PI * 2
        }}));
      }}

      function frame(){{
        if(!running) return;
        ctx.clearRect(0, 0, W, H);
        tick += 0.018;
        nodes.forEach(node => {{
          node.x += node.vx;
          node.y += node.vy;
          if(node.x < 0 || node.x > W) node.vx *= -1;
          if(node.y < 0 || node.y > H) node.vy *= -1;
        }});

        for(let i = 0; i < nodes.length; i++){{
          for(let j = i + 1; j < nodes.length; j++){{
            const dx = nodes[i].x - nodes[j].x;
            const dy = nodes[i].y - nodes[j].y;
            const d = Math.sqrt(dx * dx + dy * dy);
            if(d < MAX_DIST){{
              const strength = 1 - d / MAX_DIST;
              const pulse = 0.72 + Math.sin(tick + nodes[i].phase + nodes[j].phase) * 0.28;
              ctx.beginPath();
              ctx.strokeStyle = `rgba(199,61,57,${{strength * pulse * 0.30}})`;
              ctx.lineWidth = 0.65 + strength * 0.75;
              ctx.moveTo(nodes[i].x, nodes[i].y);
              ctx.lineTo(nodes[j].x, nodes[j].y);
              ctx.stroke();
            }}
          }}
        }}

        nodes.forEach(node => {{
          const pulse = 0.76 + Math.sin(tick * 1.6 + node.phase) * 0.24;
          ctx.beginPath();
          ctx.arc(node.x, node.y, node.r * pulse, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(199,61,57,0.44)';
          ctx.shadowColor = 'rgba(199,61,57,0.16)';
          ctx.shadowBlur = 5;
          ctx.fill();
          ctx.shadowBlur = 0;
        }});
        requestAnimationFrame(frame);
      }}

      resize();
      init();
      frame();
      window.addEventListener('resize', () => {{
        resize();
        init();
      }});
      return () => {{ running = false; }};
    }}
    initNeuralNetworkCanvas('loginNeuralCanvas');
    function toggleLoginPassword(button){{
      const input = document.getElementById('password');
      if(!input) return;
      const visible = input.type === 'password';
      input.type = visible ? 'text' : 'password';
      button.classList.toggle('is-visible', visible);
      button.setAttribute('aria-label', visible ? 'إخفاء كلمة السر' : 'إظهار كلمة السر');
    }}
    document.querySelector('form')?.addEventListener('submit', event => {{
      const form = event.currentTarget;
      if(!form.checkValidity()) return;
      document.body.classList.add('logging-in');
      form.querySelectorAll('button').forEach(element => element.disabled = true);
    }});
  </script>
</body>
</html>"""
        self.send_html(repair_mojibake_text(html))

    # AUTH BLOCK: Shared redirect helper for browser navigations.
    # Reason: HTML/static requests should go to /login instead of receiving JSON.
    def queue_cookie_headers(self, cookie_headers):
        if not cookie_headers:
            return
        if isinstance(cookie_headers, str):
            cookie_headers = [cookie_headers]
        pending = getattr(self, "_pending_cookie_headers", [])
        pending.extend(header for header in cookie_headers if header)
        self._pending_cookie_headers = pending

    # Performs the end headers helper step: CORS, cache-control, and any pending Set-Cookie headers.
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Credentials", "true")
        request_path = urllib.parse.urlparse(getattr(self, "path", "")).path.lower()
        if request_path.endswith((".html", ".css", ".js")):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        pending = getattr(self, "_pending_cookie_headers", [])
        for cookie_header in pending:
            self.send_header("Set-Cookie", cookie_header)
        self._pending_cookie_headers = []
        super().end_headers()

    # Performs the redirect helper step.
    def redirect(self, location, status=302, cookie_header=None):
        self.send_response(status)
        self.send_header("Location", location)
        self.queue_cookie_headers(cookie_header)
        self.end_headers()

    # AUTH BLOCK: Fail unauthenticated API calls with JSON, page calls with redirect.
    # Reason: The frontend fetch layer expects JSON while browser navigation expects HTML.
    def reject_auth(self, path, status=401, message="Login required"):
        if path.startswith(API_BASE):
            return self.send_json({"error": message}, status)
        next_path = urllib.parse.quote(safe_login_next(self.path), safe="/?=&%")
        return self.redirect(f"/login?next={next_path}")

    # AUTH BLOCK: Current Keycloak user for this request.
    # Reason: All route protection is centralized before existing business logic.
    def current_user(self):
        if hasattr(self, "_current_user_cache"):
            return self._current_user_cache
        user, refreshed_token = user_from_headers_with_refresh(self.headers)
        if refreshed_token:
            self.queue_cookie_headers(auth_token_cookies(refreshed_token))
        self._current_user_cache = user
        return user

    # AUTH BLOCK: Role gates for current HTTP route.
    # Reason: Admin-only routes are blocked before they can mutate pipeline state.
    def ensure_user(self, path):
        user = self.current_user()
        if require_user(user):
            return user
        self.reject_auth(path, 401, "Login required")
        return None

    # Handles ensure admin for the HTTP API layer.
    def ensure_admin(self, path):
        user = self.ensure_user(path)
        if not user:
            return None
        if require_admin(user):
            return user
        self.reject_auth(path, 403, "Admin access required")
        return None

    # AUTH BLOCK: Read URL-encoded form data for /auth/login.
    # Reason: Login is a normal HTML form, not a JSON API call.
    def read_form_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        return {key: values[0] if values else "" for key, values in urllib.parse.parse_qs(raw).items()}

    # AVAILABILITY BLOCK: Reject an oversized body before reading any of it
    # into memory, based on the declared Content-Length alone. Multipart
    # uploads (PDF import) are exempt - see MAX_JSON_BODY_BYTES. Closes the
    # connection afterward since the client may still be sending more bytes
    # than we're willing to buffer.
    def reject_if_body_too_large(self, max_bytes=MAX_JSON_BODY_BYTES):
        if "multipart/form-data" in (self.headers.get("Content-Type", "") or ""):
            return False
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= max_bytes:
            return False
        self.close_connection = True
        self.send_json({"error": "Request body too large"}, 413)
        return True

    # Server role: Send no-cache JSON responses.
    def send_json(self, data, status=200):
        data = cleanup_text_fields(data, all_strings=True)
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            trace("Client disconnected before JSON response was sent")

    # Server role: Send generated PDF responses.
    def send_pdf(self, payload, filename="AINewsletter_v02.pdf"):
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    # Server role: Send an editable PowerPoint presentation response.
    def send_pptx(self, payload, filename="AINewsletter_v02.pptx"):
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    # Server role: Proxy remote images needed by the UI/PDF preview.
    def send_image_proxy(self, query):
        raw_url = (query.get("url", [""])[0] or "").strip()
        if not _validate_image_proxy_url(raw_url):
            self.send_json({"error": "Invalid image URL"}, 400)
            return
        try:
            request = urllib.request.Request(
                raw_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                },
            )
            opener = urllib.request.build_opener(_SafeImageRedirectHandler)
            with opener.open(request, timeout=10) as response:
                content_type = response.headers.get("Content-Type", "image/png").split(";")[0].strip()
                payload = response.read(3 * 1024 * 1024 + 1)
            if len(payload) > 3 * 1024 * 1024:
                self.send_json({"error": "Image is too large"}, 413)
                return
            stripped_payload = payload.lstrip()
            if stripped_payload.startswith(b"<svg") or stripped_payload.startswith(b"<?xml"):
                content_type = "image/svg+xml"
            elif payload.startswith(b"\x89PNG\r\n\x1a\n"):
                content_type = "image/png"
            elif payload.startswith(b"\xff\xd8\xff"):
                content_type = "image/jpeg"
            elif payload.startswith(b"GIF87a") or payload.startswith(b"GIF89a"):
                content_type = "image/gif"
            elif payload.startswith(b"RIFF") and b"WEBP" in payload[:16]:
                content_type = "image/webp"
            if not content_type.startswith("image/"):
                content_type = "image/png"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            trace(f"image proxy failed for {raw_url}: {exc}")
            self.send_json({"error": "Image proxy failed"}, 502)

    # Server role: Handle static file reads and read-only API routes.
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)
        if TRACE_HTTP:
            trace(f"GET {path or '/'}")
        # AUTH BLOCK: Public login page and protected read routes.
        # Reason: Users can read newsletters/versions; admin diagnostics stay private.
        if path == "/login":
            query = urllib.parse.parse_qs(parsed_url.query)
            next_path = safe_login_next(query.get("next", [""])[0])
            if require_user(self.current_user()):
                return self.redirect(next_path)
            # CHANGE: Read the login error code and render a friendly Arabic message.
            # Reason: Users should see invalid credentials text instead of a raw code.
            return self.send_login_page((query.get("error", [""])[0] or "").strip())
        if path in PUBLIC_GET_PATHS:
            return super().do_GET()
        if any(path.startswith(prefix) for prefix in ADMIN_GET_PREFIXES):
            if not self.ensure_admin(path):
                return
        else:
            if not self.ensure_user(path):
                return
        if path == f"{API_BASE}/auth/me":
            user = self.current_user()
            return self.send_json({
                "username": user.get("username", ""),
                "roles": user.get("roles", []),
                "is_admin": bool(user.get("is_admin")),
                "is_user": bool(user.get("is_user")),
            })
        if path in {"", "/"}:
            self.send_response(302)
            suffix = f"?{parsed_url.query}" if parsed_url.query else ""
            self.send_header("Location", f"{DEFAULT_UI_PATH}{suffix}")
            self.end_headers()
            return
        if path.lower() == "/ui.html":
            self.send_response(302)
            suffix = f"?{parsed_url.query}" if parsed_url.query else ""
            self.send_header("Location", f"{DEFAULT_UI_PATH}{suffix}")
            self.end_headers()
            return
        if path.lower() == DEFAULT_UI_PATH.lower() and path != DEFAULT_UI_PATH:
            self.path = f"{DEFAULT_UI_PATH}{('?' + parsed_url.query) if parsed_url.query else ''}"
            return super().do_GET()
        if path == f"{API_BASE}/image-proxy":
            return self.send_image_proxy(query)
        if path == f"{API_BASE}/refill/progress":
            return self.send_json(current_single_refill_state())
        if path == f"{API_BASE}/news":
            user = self.current_user()
            store = load_store() if user.get("is_admin") else load_published_store()
            hidden_news = store.get("items", [])[DISPLAY_COUNTS.get("items", REQUIRED_COUNTS["items"]):]
            # AUTHZ BLOCK: GET /api/news no longer triggers generation, even
            # with ?auto=1. Reason: this route only requires the "user" role
            # (see USER_GET_PREFIXES), so any logged-in viewer could trigger a
            # paid AI-generation run. Missing content is now only ever fetched
            # through POST /api/refill, which is admin-only (ensure_admin) and
            # already single-flighted (GENERATOR_LOCK in generator_bridge.py).
            feedback = []
            missing = missing_sections(store)
            display_missing = missing_display_sections(store)
            return self.send_json({
                "items": visible_items(store, "items"),
                "backup_news": hidden_news,
                "movies": store.get("movies", []),
                "courses": store.get("courses", []),
                "news_bank": store.get("news_bank", {}),
                "courses_bank": store.get("courses_bank", {}),
                "recommended_view": store.get("recommended_view", {}),
                "saved_views": store.get("saved_views", {}),
                "default_view": store.get("default_view", {}),
                "selected_levels": store.get("selected_levels", ["all"]),
                "news_display_count": store.get("news_display_count", 4),
                "metadata": store.get("metadata", {}),
                "template": store["template"],
                "feature_mode": store["feature_mode"],
                "feature_item": get_feature_item(store),
                "generator": generator_public_state(),
                "needs_fetch": display_missing,
                "needs_fetch_required": missing,
                "previous_counts": previous_generation_counts(),
                "feedback": feedback,
            })
        if path == f"{API_BASE}/debug":
            store = load_store()
            fetch_state = load_news_fetch_state_server()
            selection_audit = {}
            if NEWS_SELECTION_AUDIT_FILE.exists():
                try:
                    selection_audit = json.loads(NEWS_SELECTION_AUDIT_FILE.read_text(encoding="utf-8"))
                except Exception:
                    selection_audit = {"error": "Could not read news_selection_audit.json"}
            return self.send_json({
                "counts": {section: len(store.get(section, [])) for section in REQUIRED_COUNTS},
                "visible_counts": {section: len(visible_items(store, section)) for section in REQUIRED_COUNTS},
                "required_counts": REQUIRED_COUNTS,
                "missing": missing_sections(store),
                "generator": generator_public_state(),
                "last_run_performance": fetch_state.get("last_run_performance", {}) if isinstance(fetch_state, dict) else {},
                "last_log_tail": GENERATOR_STATE.get("last_log_tail", ""),
                "auto_fetch_cooldown": AUTO_FETCH_COOLDOWN,
                "last_auto_start": GENERATOR_STATE.get("last_auto_start"),
                "selection_audit_file": str(NEWS_SELECTION_AUDIT_FILE),
                "selection_audit_summary": selection_audit.get("summary", {}),
                "selection_audit_queries": selection_audit.get("queries", {}),
                "selection_audit_rejected_items": [
                    item for item in selection_audit.get("items", [])
                    if item.get("decision") == "rejected"
                ],
                "selection_audit_selected_items": selection_audit.get("selected_items", []),
            })
        if handle_versions_get(self, path):
            return

        if path == f"{API_BASE}/ai-updates":
            ai_updates_report_file = AI_UPDATES_RUN_REPORT_FILE
            if ai_updates_report_file.exists():
                try:
                    with open(ai_updates_report_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return self.send_json(data)
                except Exception as exc:
                    trace(f"Failed to load AI updates: {exc}")
                    return self.send_json({"error": "Failed to load AI updates", "latest_updates": []}, 500)
            else:
                return self.send_json({"latest_updates": [], "timestamp": None, "message": "No AI updates yet"})
        return super().do_GET()

    # DATA INTEGRITY BLOCK: Turn a StoreConflict raised anywhere in the POST
    # handling (a direct edit, or several layers deep through single-card
    # refill/version restore) into a clean 409 instead of an unhandled
    # exception. See backend/storage/newsletter_store.py save_store().
    def do_POST(self):
        try:
            return self._do_POST_impl()
        except StoreConflict as exc:
            return self.send_json({"success": False, "error": str(exc), "conflict": True}, 409)

    # Server role: Handle generate/refill/edit/settings API actions.
    def _do_POST_impl(self):
        path = urllib.parse.urlparse(self.path).path
        if TRACE_HTTP:
            trace(f"POST {path}")
        # AUTH BLOCK: Login and logout are the only public/auth lifecycle posts.
        # Reason: Login creates the httponly token cookie; logout clears it.
        if path == "/auth/login":
            form = self.read_form_body()
            next_path = safe_login_next(form.get("next", ""))
            try:
                token = authenticate(form.get("username", ""), form.get("password", ""))
            except Exception as exc:
                # CHANGE: Log the real Keycloak login error and redirect with one public error code.
                # Reason: Generic errors hide debugging details while users only need one clear message.
                print(f"Login error: {str(exc)}")
                trace(f"Login failed: {exc}")
                quoted_next = urllib.parse.quote(next_path, safe="/?=&%")
                return self.redirect(f"/login?error=invalid_credentials&next={quoted_next}")
            cookie_header = auth_token_cookies(token)
            return self.redirect(next_path, cookie_header=cookie_header)
        if path == "/auth/logout":
            return self.redirect("/login", cookie_header=clear_auth_cookies())

        # AUTH BLOCK: POST route authorization before existing business logic.
        # Reason: Users can export PDFs; every mutation/run/settings action is admin-only.
        if path in USER_POST_PATHS:
            if not self.ensure_user(path):
                return
        else:
            if not self.ensure_admin(path):
                return
        if self.reject_if_body_too_large():
            return
        if handle_versions_post(self, path):
            return
        if path in {f"{API_BASE}/generation/cancel", f"{API_BASE}/refill/cancel"}:
            full = cancel_generator()
            single = cancel_single_refill()
            return self.send_json({
                "success": True,
                "cancel_requested": bool(full.get("cancel_requested") or single.get("cancel_requested")),
                "generator": generator_public_state(),
                "single_refill": current_single_refill_state(),
            })
        data = read_json_body(self)
        store = load_store()

        if path.startswith(f"{API_BASE}/rewrite/"):
            item_id = path.split("/")[-1]
            item = find_editable_store_item(store, "items", item_id)
            if not item:
                return self.send_json({"error": "News item not found"}, 404)
            rewritten = rewrite_text(item["title"], item["text"], data.get("instruction", ""))
            item["title"] = rewritten["title"]
            item["text"] = rewritten["text"]
            sync_item_in_saved_views(store, "items", item)
            save_store(store)
            return self.send_json({"success": True, "item": item, "rewrite_mode": rewritten["mode"], "rewrite_error": rewritten.get("error", "")})

        if path.startswith(f"{API_BASE}/replace/"):
            parts = path.strip("/").split("/")
            section = "items"
            item_id = parts[-1]
            if len(parts) >= 4 and parts[2] in SECTION_KEYS:
                section = parts[2]
                item_id = parts[3]
            store, result = replace_item_at_index(store, section, item_id)
            if result.get("needs_fetch"):
                result["message"] = (
                    "لا يوجد بديل جاهز. هل تريد البحث عن بديل جديد؟"
                    if not NEWS_JSON_ONLY_MODE
                    else "JSON-only mode active. No fetch will run; only current news.json reserves are available."
                )
            if result.get("error"):
                return self.send_json(result, 404)
            return self.send_json(
                replacement_response(store, section, result.get("index", -1), result),
                200 if result.get("success") else 409,
            )

        if path == f"{API_BASE}/export-pdf":
            if not _pdf_export_rate_limit_allows((self.current_user() or {}).get("username")):
                return self.send_json(
                    {"success": False, "error": "Too many export requests. Try again in a moment."}, 429
                )
            if not PDF_EXPORT_SEMAPHORE.acquire(blocking=False):
                return self.send_json(
                    {"success": False, "error": "An export is already in progress. Try again shortly."}, 429
                )
            try:
                preview_html = str(data.get("html") or "")
                width = data.get("width") or 1000
                height = data.get("height") or 1340
                direction = str(data.get("direction") or "rtl")
                pdf_profile = str(data.get("pdf_profile") or data.get("share_profile") or PDF_EXPORT_PROFILE)
                pdf_scale = data.get("scale")
                source_html = str(data.get("source_html") or "")
                host = self.headers.get("Host") or "127.0.0.1:8000"
                origin = f"http://{host}"
                try:
                    pdf_bytes = export_preview_pdf_bytes(
                        preview_html,
                        width,
                        height,
                        origin,
                        direction,
                        scale=pdf_scale,
                        profile=pdf_profile,
                        source_file=source_html,
                    )
                    newsletter_json = data.get("newsletter_json")
                    if isinstance(newsletter_json, dict):
                        trace(
                            "PDF export received newsletter_json "
                            f"items={len(newsletter_json.get('items') or [])} "
                            f"backup={len(newsletter_json.get('backup_news') or [])} "
                            f"courses={len(newsletter_json.get('courses') or [])}"
                        )
                        pdf_bytes = attach_newsletter_json_to_pdf(pdf_bytes, newsletter_json)
                    else:
                        trace("PDF export did not receive newsletter_json; exported PDF will not be fully re-importable")
                except Exception as exc:
                    trace(f"PDF export failed: {exc}")
                    return self.send_json({"success": False, "error": str(exc)}, 500)
                return self.send_pdf(pdf_bytes)
            finally:
                PDF_EXPORT_SEMAPHORE.release()

        if path == f"{API_BASE}/export-pptx":
            if not _pdf_export_rate_limit_allows((self.current_user() or {}).get("username")):
                return self.send_json(
                    {"success": False, "error": "Too many export requests. Try again in a moment."}, 429
                )
            if not PDF_EXPORT_SEMAPHORE.acquire(blocking=False):
                return self.send_json(
                    {"success": False, "error": "An export is already in progress. Try again shortly."}, 429
                )
            try:
                host = self.headers.get("Host") or "127.0.0.1:8000"
                origin = f"http://{host}"
                try:
                    pptx_bytes = export_newsletter_pptx_bytes(data, origin)
                except Exception as exc:
                    trace(f"PowerPoint export failed: {exc}")
                    return self.send_json({"success": False, "error": str(exc)}, 500)
                return self.send_pptx(pptx_bytes)
            finally:
                PDF_EXPORT_SEMAPHORE.release()

        if path == f"{API_BASE}/refill":
            section = data.get("section")
            if section not in SECTION_KEYS:
                section = None
            force_refresh = bool(data.get("force") or data.get("force_refresh"))
            pool_only = bool(data.get("pool_only"))
            item_id = str(data.get("item_id") or "").strip()
            action = "replace"
            extra_exclude = data.get("exclude_items") or []
            if not isinstance(extra_exclude, list):
                extra_exclude = []
            card_history = data.get("card_refill_history") or {}
            if isinstance(card_history, dict):
                if isinstance(card_history.get("tried_items"), list):
                    extra_exclude.extend(item for item in card_history.get("tried_items") if isinstance(item, dict))
                for url in card_history.get("tried_urls") or []:
                    if url:
                        extra_exclude.append({"url": str(url), "title": "", "source": ""})
                for title in card_history.get("tried_titles") or []:
                    if title:
                        extra_exclude.append({"title": str(title), "url": "#", "source": ""})
                for source_id in card_history.get("tried_source_ids") or []:
                    if source_id:
                        extra_exclude.append({"source_id": str(source_id), "id": str(source_id), "url": "#"})
            index = data.get("index")
            try:
                index = int(index) if index is not None else None
            except Exception:
                index = None
            if NEWS_JSON_ONLY_MODE:
                return self.send_json(
                    {
                        "success": False,
                        "running": False,
                        "message": "JSON-only mode active. Single refill requires live pipeline fetch.",
                    },
                    409,
                )
            single_card_request = bool(section and (item_id or index is not None or pool_only))
            if single_card_request:
                trace(
                    f"Single-item refill requested section={section} "
                    f"action={action} item_id={item_id or '-'} index={index}"
                )
                store, result = single_item_refill(
                    store,
                    section,
                    item_id=item_id or None,
                    index=index,
                    action="replace",
                    extra_exclude=extra_exclude,
                    visible_exclude=data.get("visible_items"),
                    allow_fetch=True,
                    live_fetch=True,
                    requested_level=str(data.get("level") or "").strip(),
                )
                return self.send_json(
                    replacement_response(store, section, result.get("index", index or -1), result),
                    200 if (result.get("success") or result.get("running")) else 409,
                )
            trace(f"Refill requested section={section or 'all'} force_refresh={force_refresh}")
            result = start_generator_background(
                section,
                force_refresh=force_refresh,
                preserve_visible_sections=None,
            )
            trace(f"Refill response running={result.get('running', False)} success={result.get('success', False)}")
            store = load_store()
            return self.send_json({
                "success": result["success"],
                "message": result["message"],
                "running": result.get("running", False),
                "items": visible_items(store, "items"),
                "movies": store.get("movies", []),
                "courses": store.get("courses", []),
                "needs_fetch": missing_display_sections(store),
                "needs_fetch_required": missing_sections(store),
                "previous_counts": previous_generation_counts(),
                "generator": generator_public_state(),
            })

        if path == f"{API_BASE}/ai-edit":
            title = str(data.get("title", "") or "")
            text = str(data.get("text", "") or "")
            rewritten = rewrite_text(title, text, data.get("instruction", ""))
            return self.send_json({"success": True, "title": rewritten["title"], "text": rewritten["text"], "rewrite_mode": rewritten["mode"], "rewrite_error": rewritten.get("error", "")})

        if path == f"{API_BASE}/restore-previous-card":
            section = data.get("section")
            if section not in SECTION_KEYS:
                return self.send_json({"success": False, "error": "Invalid section"}, 400)
            try:
                index = int(data.get("index"))
            except Exception:
                return self.send_json({"success": False, "error": "Invalid card index"}, 400)
            store, result = restore_previous_card_at_index(store, section, index)
            return self.send_json(
                replacement_response(store, section, result.get("index", index), result),
                200 if result.get("success") else 409,
            )

        if path.startswith(f"{API_BASE}/card/"):
            parts = path.strip("/").split("/")
            if len(parts) < 4 or parts[2] not in SECTION_KEYS:
                return self.send_json({"error": "Invalid card path"}, 400)
            section = parts[2]
            try:
                index = int(parts[3])
            except Exception:
                return self.send_json({"error": "Invalid card index"}, 400)
            store, result = update_card_from_client(
                store,
                section,
                index,
                data.get("item") or data,
                target_id=data.get("target_id"),
                visible_items=data.get("visible_items"),
            )
            if result.get("error"):
                return self.send_json(result, 409)
            return self.send_json(replacement_response(store, section, index, result))

        if path == f"{API_BASE}/settings":
            current_settings = load_newsletter_settings()
            current_settings.update({
                "newsletter_title": str(data.get("newsletter_title") or current_settings.get("newsletter_title") or "").strip(),
                "footer_prefix": str(data.get("footer_prefix") or current_settings.get("footer_prefix") or "").strip(),
                "issue_number": safe_int(data.get("issue_number"), current_settings.get("issue_number")),
                "month_year_override": str(data.get("month_year_override") or "").strip(),
            })
            saved_settings = save_newsletter_settings(current_settings)
            store["template"] = newsletter_template_from_settings(saved_settings)
            save_store(store)
            return self.send_json({"success": True, "template": store["template"]})

        return self.send_json({"error": "Route not found"}, 404)

    # DATA INTEGRITY BLOCK: See do_POST's wrapper - same reasoning.
    def do_PUT(self):
        try:
            return self._do_PUT_impl()
        except StoreConflict as exc:
            return self.send_json({"success": False, "error": str(exc), "conflict": True}, 409)

    # Server role: Handle direct card/settings state updates.
    def _do_PUT_impl(self):
        path = urllib.parse.urlparse(self.path).path
        if TRACE_HTTP:
            trace(f"PUT {path}")
        # AUTH BLOCK: All PUT routes edit newsletter/version state.
        # Reason: Read-only users must not modify items, settings, order, or versions.
        if not self.ensure_admin(path):
            return
        if self.reject_if_body_too_large():
            return
        data = read_json_body(self)
        if handle_versions_put(self, path, data):
            return
        store = load_store()

        if path.startswith(f"{API_BASE}/news/"):
            item_id = path.split("/")[-1]
            item = find_editable_store_item(store, "items", item_id)
            if not item:
                return self.send_json({"error": "News item not found"}, 404)
            editable_news_fields = (
                "title", "text", "summary", "url", "source", "source_id", "source_url",
                "original_url", "original_title", "original_source", "published", "date",
                "logo", "provider_logo", "source_logo", "company", "main_company",
                "logo_company", "logo_override_url", "manual_logo_url", "tool_name", "product_name", "product_or_tool",
                "feature_or_tool", "what_is_new", "new_capability", "why_it_is_valuable",
                "practical_benefit", "user_can_do", "end_user_value",
                "domain_bucket", "selection_reason", "verification_status",
                "reader_access_type",
                "level",
            )
            for field in editable_news_fields:
                if field in data:
                    item[field] = str(data.get(field, "")).strip()
            if "logo_unresolved" in data:
                item["logo_unresolved"] = bool(data.get("logo_unresolved"))
            if "logo_manual_override" in data:
                item["logo_manual_override"] = bool(data.get("logo_manual_override"))
            if "logo_size" in data:
                item["logo_size"] = clamp_logo_size(data.get("logo_size"))
            if "logo_x" in data:
                item["logo_x"] = clamp_logo_position(data.get("logo_x"))
            if "logo_y" in data:
                item["logo_y"] = clamp_logo_position(data.get("logo_y"))
            if isinstance(data.get("metadata"), dict):
                item["metadata"] = cleanup_text_fields(data.get("metadata"))
            for field in ("field_secondary", "life_domains", "logo_candidates"):
                if isinstance(data.get(field), list):
                    item[field] = cleanup_text_fields(data.get(field))
            for field in ("quality_score", "confidence_score", "recency_score", "score", "user_value_score", "query_alignment_score"):
                if field in data:
                    item[field] = safe_int(data.get(field), 0)
            if any(field in data for field in ("logo", "provider_logo", "source_logo", "logo_override_url", "manual_logo_url", "logo_candidates")):
                item["logo_updated_at"] = str(int(time.time()))
            normalized_item = normalize_item(item, "news")
            item.clear()
            item.update(normalized_item)
            sync_item_in_saved_views(store, "items", item)
            save_store(store)
            return self.send_json({"success": True, "item": item})

        if path.startswith(f"{API_BASE}/content/"):
            parts = path.strip("/").split("/")
            if len(parts) < 4:
                return self.send_json({"error": "Invalid content path"}, 400)
            section, item_id = parts[2], parts[3]
            if section not in SECTION_KEYS:
                return self.send_json({"error": "Invalid section"}, 400)
            item = find_editable_store_item(store, section, item_id)
            if not item:
                return self.send_json({"error": "Content item not found"}, 404)
            for field in ("title", "text", "url", "source", "logo", "provider_logo", "source_logo", "logo_override_url", "manual_logo_url", "image", "poster", "rating", "duration", "level"):
                if field in data:
                    item[field] = str(data.get(field, "")).strip()
            if "logo_manual_override" in data:
                item["logo_manual_override"] = bool(data.get("logo_manual_override"))
            if "logo_size" in data:
                item["logo_size"] = clamp_logo_size(data.get("logo_size"))
            if "logo_x" in data:
                item["logo_x"] = clamp_logo_position(data.get("logo_x"))
            if "logo_y" in data:
                item["logo_y"] = clamp_logo_position(data.get("logo_y"))
            if isinstance(data.get("logo_candidates"), list):
                item["logo_candidates"] = cleanup_text_fields(data.get("logo_candidates"))
            if any(field in data for field in ("logo", "provider_logo", "source_logo", "logo_override_url", "manual_logo_url", "logo_candidates", "image", "poster")):
                item["logo_updated_at"] = str(int(time.time()))
            normalized_item = normalize_item(item, SECTION_TO_CONTENT_TYPE.get(section, "news"))
            item.clear()
            item.update(normalized_item)
            sync_item_in_saved_views(store, section, item)
            save_store(store)
            return self.send_json({"success": True, "item": item, "section": section})

        if path.startswith(f"{API_BASE}/feature/"):
            feature_mode = path.split("/")[-1]
            if feature_mode not in FEATURE_MODES:
                return self.send_json({"error": "Invalid feature mode"}, 400)
            store["feature_mode"] = feature_mode
            save_store(store)
            return self.send_json({"success": True, "feature_mode": feature_mode, "feature_item": get_feature_item(store)})

        if path == f"{API_BASE}/state":
            restored = {
                "items": client_state_news_items(data, store.get("items", [])),
                "movies": data.get("movies") if isinstance(data.get("movies"), list) else store.get("movies", []),
                "courses": data.get("courses") if isinstance(data.get("courses"), list) else store.get("courses", []),
                "news_bank": data.get("news_bank") if isinstance(data.get("news_bank"), dict) else store.get("news_bank", {}),
                "courses_bank": data.get("courses_bank") if isinstance(data.get("courses_bank"), dict) else store.get("courses_bank", {}),
                "recommended_view": data.get("recommended_view") if isinstance(data.get("recommended_view"), dict) else store.get("recommended_view", {}),
                "saved_views": data.get("saved_views") if isinstance(data.get("saved_views"), dict) else store.get("saved_views", {}),
                "default_view": data.get("default_view") if isinstance(data.get("default_view"), dict) else store.get("default_view", {}),
                "selected_levels": data.get("selected_levels") if isinstance(data.get("selected_levels"), list) else store.get("selected_levels", ["all"]),
                "news_display_count": 6 if int(data.get("newsDisplayCount") or data.get("news_display_count") or store.get("news_display_count") or 4) == 6 else 4,
                "metadata": data.get("metadata") if isinstance(data.get("metadata"), dict) else store.get("metadata", {}),
                "template": {**store.get("template", {}), **(data.get("template") if isinstance(data.get("template"), dict) else {})},
                "feature_mode": data.get("feature_mode") if data.get("feature_mode") in FEATURE_MODES else store.get("feature_mode", "course"),
            }
            restored = save_store(restored)
            hidden_news = restored.get("items", [])[DISPLAY_COUNTS.get("items", REQUIRED_COUNTS["items"]):]
            return self.send_json({
                "success": True,
                "items": visible_items(restored, "items"),
                "backup_news": hidden_news,
                "movies": restored.get("movies", []),
                "courses": restored.get("courses", []),
                "news_bank": restored.get("news_bank", {}),
                "courses_bank": restored.get("courses_bank", {}),
                "recommended_view": restored.get("recommended_view", {}),
                "saved_views": restored.get("saved_views", {}),
                "default_view": restored.get("default_view", {}),
                "selected_levels": restored.get("selected_levels", ["all"]),
                "news_display_count": restored.get("news_display_count", 4),
                "metadata": restored.get("metadata", {}),
                "template": restored["template"],
                "feature_mode": restored["feature_mode"],
                "feature_item": get_feature_item(restored),
                "needs_fetch": missing_display_sections(restored),
                "needs_fetch_required": missing_sections(restored),
                "previous_counts": previous_generation_counts(),
            })

        if path in {f"{API_BASE}/reorder/items", f"{API_BASE}/reorder/courses"}:
            section = path.rsplit("/", 1)[-1]
            ids = data.get("ids") or []
            if not isinstance(ids, list):
                return self.send_json({"error": "ids must be a list"}, 400)
            by_id = {i["id"]: i for i in store[section]}
            reordered = [by_id[i] for i in ids if i in by_id]
            for item in store[section]:
                if item["id"] not in ids:
                    reordered.append(item)
            store[section] = reorder_positions(reordered)
            save_store(store)
            return self.send_json({"success": True, section: visible_items(store, section)})

        return self.send_json({"error": "Route not found"}, 404)

    # DATA INTEGRITY BLOCK: See do_POST's wrapper - same reasoning.
    def do_DELETE(self):
        try:
            return self._do_DELETE_impl()
        except StoreConflict as exc:
            return self.send_json({"success": False, "error": str(exc), "conflict": True}, 409)

    # Handles do DELETE for the HTTP API layer.
    def _do_DELETE_impl(self):
        path = urllib.parse.urlparse(self.path).path
        if TRACE_HTTP:
            trace(f"DELETE {path}")
        # AUTH BLOCK: All DELETE routes remove saved content.
        # Reason: Only admins can delete versions or other managed resources.
        if not self.ensure_admin(path):
            return
        if handle_versions_delete(self, path):
            return
        store = load_store()
        section = None
        item_id = ""
        if path.startswith(f"{API_BASE}/news/"):
            section = "items"
            item_id = path.rsplit("/", 1)[-1]
        elif path.startswith(f"{API_BASE}/content/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[2] in SECTION_KEYS:
                section, item_id = parts[2], parts[3]
        if section:
            if not remove_item_from_store(store, section, item_id):
                return self.send_json({"error": "Content item not found"}, 404)
            saved = save_store(store, rebalance_news=False)
            return self.send_json({
                "success": True,
                "section": section,
                "deleted_id": item_id,
                "items": visible_items(saved, "items"),
                "courses": saved.get("courses", []),
                "movies": saved.get("movies", []),
                "feature_item": get_feature_item(saved),
            })
        return self.send_json({"error": "Route not found"}, 404)

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = 8000
    try:
        bootstrap_keycloak_if_missing()
        init_versions_db()
        # Start the AI updates background daemon
        start_background_daemon()
        
        with ThreadedTCPServer((host, port), BackendHandler) as httpd:
            print(f"Running: http://{host}:{port}{DEFAULT_UI_PATH}", flush=True)
            trace(f"Serving static files from {FRONTEND_DIR}")
            trace(f"API base {API_BASE}; pipeline backend\\pipeline\\orchestrator.py")
            trace(f"HTTP tracing is {'on' if TRACE_HTTP else 'off'}")
            httpd.serve_forever()
    except OSError as exc:
        print(f"Could not start server on http://{host}:{port}: {exc}", flush=True)
        print("Another server is probably still running. Stop old terminals or run:", flush=True)
        print("  netstat -ano | findstr :8000", flush=True)
        print("  taskkill /PID <PID> /F", flush=True)
        raise
