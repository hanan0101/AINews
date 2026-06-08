import http.server
import json
import os
import socketserver
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
# Wrapper functions around debugging.py helpers.
# Local shortcuts for debugging.py helpers.
# They automatically pass the server's generator state and progress settings.
# update the timeline or return public generator status without repeating those arguments.
from debugging import (
    append_generator_timeline as debug_append_generator_timeline,
    configure_console_encoding,
    generator_public_state as debug_generator_public_state,
    trace,
)
# PDF export helpers: render the newsletter preview HTML into downloadable PDF bytes.
from pdf_export import export_preview_pdf_bytes, PDF_EXPORT_PROFILE
from text_cleanup import cleanup_text_fields
from server_items import (
    clamp_logo_position,# keeps logo x/y positions inside safe UI limits.
    clamp_logo_size,# keeps logo size inside safe UI limits.
    normalize_item,
)
from server_refill import current_single_refill_state, single_item_refill
from server_store import (
    DISPLAY_COUNTS,
    FEATURE_MODES,
    FRONTEND_DIR,
    NEWS_BACKUP_COUNT,
    NEWS_FETCH_STATE_FILE,
    NEWS_JSON_FILE,
    NEWS_SELECTION_AUDIT_FILE,
    REQUIRED_COUNTS,
    SECTION_KEYS,
    SECTION_TO_CONTENT_TYPE,
    find_item,
    get_feature_item,
    increment_newsletter_issue,
    load_newsletter_settings,
    load_news_fetch_state_server,
    load_store,
    missing_display_sections,
    missing_sections,
    newsletter_template_from_settings,
    previous_generation_counts,
    restore_previous_card_at_index,
    safe_int,
    save_newsletter_settings,
    save_store,
    save_previous_generation_snapshot,
    section_feedback,
    update_card_from_client,
    visible_items,
)

# for Optional OpenAI client for manual rewrite/edit routes.
# If the package is missing, the server still runs and rewrite uses fallback behavior.
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Load the pipeline functions used by fetch/refill routes.
# Pipeline import errors should stop startup so code/configuration issues are visible immediately.
from ai_update_pipeline import run_pipeline as run_ai_updates_pipeline
from ai_update_pipeline import start_background_daemon

# Runtime paths used by the static UI server and local Python launcher.
ROOT_DIR = Path(__file__).resolve().parent
VENV_PYTHON = ROOT_DIR.parent / "venv" / "Scripts" / "python.exe"
PYTHON_EXECUTABLE = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))
API_BASE = "/api"
load_dotenv(ROOT_DIR / ".env", override=True)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
openai_client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None
REWRITE_MODEL = os.getenv("OPENAI_REWRITE_MODEL", "gpt-4o-mini")
GENERATOR_TIMEOUT = int(os.getenv("GENERATOR_TIMEOUT", "600"))
AUTO_FETCH_COOLDOWN = int(os.getenv("AUTO_FETCH_COOLDOWN", "300") or "300")
USE_AI_UPDATES_PIPELINE_FOR_GENERATE = os.getenv("USE_AI_UPDATES_PIPELINE_FOR_GENERATE", "1").strip().lower() in {"1", "true", "yes", "on"}
GENERATOR_LOCK = threading.Lock()

configure_console_encoding()
GENERATOR_STATE = {
    "running": False,
    "last_result": None,
    "last_log_tail": "",
    "timeline": [],
    "started_at": None,
    "finished_at": None,
    "last_auto_start": None,
    "sections": [],
    "active_stage_key": "",
    "stage_started_at": {},
    "stage_completed_at": {},
}
NEWS_JSON_ONLY_MODE = os.getenv("NEWS_JSON_ONLY_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}


# Generator progress stages define the steps 
GENERATOR_PROGRESS_STAGES = [
    {
        "key": "source_fetch",
        "label_ar": "جلب المصادر",
        "label_en": "Fetch Sources",
    },
    {
        "key": "quality_filter",
        "label_ar": "فلترة الجودة والذاكرة",
        "label_en": "Filter and Deduplicate",
    },
    {
        "key": "ai_model",
        "label_ar": "اختيار وصياغة الأخبار",
        "label_en": "AI Selection and Writing",
    },
    {
        "key": "save",
        "label_ar": "حفظ الأخبار",
        "label_en": "Save News",
    },
    {
        "key": "supporting",
        "label_ar": "تحديث الكورسات والأفلام",
        "label_en": "Courses and Films",
    },
    {
        "key": "ready",
        "label_ar": "النشرة جاهزة للمراجعة",
        "label_en": "Newsletter Ready for Review",
    },
]
STAGE_KEY_TO_INDEX = {stage["key"]: index for index, stage in enumerate(GENERATOR_PROGRESS_STAGES)}

LOG_TAIL_LIMIT = 6000
TIMELINE_LIMIT = 120
MESSAGE_LIMIT = 700
TRACE_HTTP = os.getenv("SERVER_TRACE_HTTP", "1").strip().lower() not in {"0", "false", "no", "off"}

# Generator state accessors for the frontend and generator code to update progress and timeline in a consistent way.
append_generator_timeline = lambda line: debug_append_generator_timeline(  # noqa: E731
    line,
    GENERATOR_STATE,
    STAGE_KEY_TO_INDEX,
    TIMELINE_LIMIT,
)
generator_public_state = lambda: debug_generator_public_state(  # noqa: E731
    GENERATOR_STATE,
    GENERATOR_PROGRESS_STAGES,
    STAGE_KEY_TO_INDEX,
    load_news_fetch_state_server,
    MESSAGE_LIMIT,
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
        "feature_mode": store["feature_mode"],
        "feature_item": get_feature_item(store),
        "needs_fetch": missing_display_sections(store),
        "needs_fetch_required": missing_sections(store),
        "previous_counts": previous_generation_counts(),
        "generator": generator_public_state(),
    }


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


# Server role: Decide whether Generate should route to ai_update_pipeline.
def should_use_ai_updates_generator(section=None, preserve_visible_sections=None):
    """Return True when the old Generate button should use the new modular path."""
    return bool(USE_AI_UPDATES_PIPELINE_FOR_GENERATE and run_ai_updates_pipeline is not None)


# Server role: Refresh courses/movies through modular supporting pipelines.
def refresh_supporting_content_into_store(base_store, pre_run_store_snapshot):
    """
    The new AI updates path owns news discovery, but the old UI still needs
    vetted course and movie cards from the modular supporting fetchers.
    """
    if os.getenv("AI_UPDATES_REFRESH_SUPPORTING_CONTENT", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        return dict(base_store or {}), {"courses": 0, "movies": 0}

    counts = {"courses": 0, "movies": 0}
    try:
        from ai_update_pipeline.config import SUPPORTING_COURSE_FETCH_POOL, SUPPORTING_MOVIE_FETCH_POOL
        from ai_update_pipeline.fetchers import fetch_course_candidates, fetch_movie_candidates
        from ai_update_pipeline.filters import filter_supporting_candidates, save_supporting_memory
        from ai_update_pipeline.model import select_supporting_content_cards
    except Exception as exc:
        trace(f"AI updates supporting content skipped; modular sources unavailable: {exc}")
        return dict(base_store or {}), counts

    store = dict(base_store or load_store())
    fetch_plan = (
        ("course", "courses", lambda: fetch_course_candidates(max_results=max(SUPPORTING_COURSE_FETCH_POOL, DISPLAY_COUNTS.get("courses", 2) + 8))),
        ("movie", "movies", lambda: fetch_movie_candidates(target_count=max(SUPPORTING_MOVIE_FETCH_POOL, DISPLAY_COUNTS.get("movies", 1) + 12))),
    )
    for content_type, section, fetcher in fetch_plan:
        try:
            append_generator_timeline(f"Refreshing {section} with modular sources")
            raw = fetcher() or []
            required = DISPLAY_COUNTS.get(section, REQUIRED_COUNTS.get(section, 1))
            limit = max(required + 6, required)
            visible_items = []
            if isinstance(pre_run_store_snapshot, dict) and isinstance(pre_run_store_snapshot.get(section), list):
                visible_items = pre_run_store_snapshot.get(section) or []
            elif isinstance(store.get(section), list):
                visible_items = store.get(section) or []
            result = filter_supporting_candidates(raw, content_type, limit, visible_items=visible_items)
            gpt_result = select_supporting_content_cards(
                result,
                content_type,
                min(limit, len(result) or limit),
            )
            if len(gpt_result or []) >= required:
                result = gpt_result
                trace(f"AI updates supporting {section} selected with modular supporting prompt")
            else:
                trace(
                    f"AI updates supporting {section} prompt returned "
                    f"{len(gpt_result or [])}/{required}; keeping existing content"
                )
                result = []
            if len(result or []) < required:
                trace(
                    f"AI updates supporting {section} refresh kept existing content: "
                    f"new={len(result or [])}/{required}"
                )
                continue
            store[section] = result
            counts[section] = len(result or [])
            try:
                visible_count = DISPLAY_COUNTS.get(section, REQUIRED_COUNTS.get(section, len(result or [])))
                save_supporting_memory((result or [])[:visible_count], content_type)
            except Exception as memory_exc:
                trace(f"AI updates supporting {section} memory save skipped: {memory_exc}")
            trace(f"AI updates supporting {section} refreshed: {counts[section]}")
        except Exception as exc:
            trace(f"AI updates supporting {section} refresh failed: {exc}")

    return store, counts


# Server role: Refresh and persist supporting content after news generation.
def refresh_supporting_content_for_ai_updates(pre_run_store_snapshot):
    store, counts = refresh_supporting_content_into_store(load_store(), pre_run_store_snapshot)
    if counts["courses"] or counts["movies"]:
        save_store(store, rebalance_news=True)
    return counts


# Server role: Bridge the frontend Generate action to ai_update_pipeline.
def run_ai_updates_generator(section=None, force_refresh=False, preserve_visible_sections=None):
    """Bridge the old UI Generate endpoint to backend/ai_update_pipeline."""
    if run_ai_updates_pipeline is None:
        return {"success": False, "message": "AI updates pipeline is not available"}
    if not GENERATOR_LOCK.acquire(blocking=False):
        return {"success": True, "running": True, "message": "Pipeline is already running"}
    started = time.time()
    try:
        GENERATOR_STATE["running"] = True
        GENERATOR_STATE["sections"] = ["items"]
        GENERATOR_STATE["started_at"] = started
        GENERATOR_STATE["finished_at"] = None
        GENERATOR_STATE["last_log_tail"] = ""
        GENERATOR_STATE["timeline"] = []
        GENERATOR_STATE["last_result"] = None
        GENERATOR_STATE["active_stage_key"] = ""
        GENERATOR_STATE["stage_started_at"] = {}
        GENERATOR_STATE["stage_completed_at"] = {}
        append_generator_timeline("Starting news fetch with SearXNG")
        pre_run_store_snapshot = load_store()
        if section in {"courses", "movies"}:
            GENERATOR_STATE["sections"] = [section]
            append_generator_timeline(f"Refreshing {section} with modular pipeline")
            store, counts = refresh_supporting_content_into_store(pre_run_store_snapshot, pre_run_store_snapshot)
            save_store(store, rebalance_news=True)
            selected = counts.get(section, 0)
            success = selected >= DISPLAY_COUNTS.get(section, REQUIRED_COUNTS.get(section, 1))
            message = f"AI updates refreshed {section}: {selected} item(s)."
            GENERATOR_STATE["last_log_tail"] = message
            GENERATOR_STATE["last_result"] = {"success": success, "message": message, "counts": counts}
            trace(f"AI updates supporting-only refresh section={section} success={success} counts={counts}")
            return GENERATOR_STATE["last_result"]
        if section is None:
            GENERATOR_STATE["sections"] = ["items", "courses", "movies"]
        trace("Starting SearXNG AI updates pipeline for old UI Generate")
        try:
            report = run_ai_updates_pipeline(write_news_json=True, progress_callback=append_generator_timeline)
        except Exception as exc:
            report = {"success": False, "error": "ai_updates_pipeline_exception", "exception": str(exc)}
        performance = report.get("performance") if isinstance(report, dict) else {}
        selected_count = len(report.get("latest_updates") or []) if isinstance(report, dict) else 0
        minimum_news_to_save = DISPLAY_COUNTS.get("items", REQUIRED_COUNTS["items"])
        required_total = DISPLAY_COUNTS.get("items", REQUIRED_COUNTS["items"]) + NEWS_BACKUP_COUNT
        append_generator_timeline(
            f"SearXNG news selected {selected_count}/{required_total} "
            f"in {safe_int(round(float(performance.get('total_seconds', 0) or 0)))}s"
        )
        effective_success = bool(
            isinstance(report, dict)
            and report.get("success")
            and selected_count >= minimum_news_to_save
            and performance.get("news_json_saved")
            and NEWS_JSON_FILE.exists()
        )
        if effective_success:
            support_counts = {"courses": 0, "movies": 0}
            if section is None and isinstance(report, dict) and report.get("supporting_content_handled"):
                support_info = report.get("supporting_content") if isinstance(report.get("supporting_content"), dict) else {}
                support_counts = {
                    "courses": safe_int(support_info.get("courses", 0)),
                    "movies": safe_int(support_info.get("movies", 0)),
                }
                trace(
                    "SearXNG pipeline handled supporting content: "
                    f"courses={support_counts.get('courses', 0)} movies={support_counts.get('movies', 0)}"
                )
            elif section is None:
                support_counts = refresh_supporting_content_for_ai_updates(pre_run_store_snapshot)
            try:
                reconciled_store = load_store()
                save_store(reconciled_store, rebalance_news=True)
                reconciled_store = load_store()
                trace(
                    "SearXNG pipeline reconciled frontend/news.json: "
                    f"items={len(reconciled_store.get('items', []))} "
                    f"visible_items={len(visible_items(reconciled_store, 'items'))}"
                )
            except Exception as reconcile_exc:
                trace(f"SearXNG pipeline reconcile failed: {reconcile_exc}")
            if section is None:
                increment_newsletter_issue()
            append_generator_timeline("Saved frontend/news.json")
            append_generator_timeline("Newsletter ready for review")
        else:
            try:
                restored_store = dict(pre_run_store_snapshot or {})
                support_counts = {"courses": 0, "movies": 0}
                save_store(restored_store)
                trace(
                    "SearXNG pipeline did not produce enough live news to save; "
                    "restored pre-run news and skipped supporting refresh"
                )
            except Exception as restore_exc:
                trace(f"SearXNG pipeline restore skipped: {restore_exc}")
        total_seconds = time.time() - started
        append_generator_timeline(
            "Fetch finished successfully" if effective_success else "Fetch finished without enough news"
        )
        message = (
            f"SearXNG generated {selected_count} news items in {total_seconds:.1f}s."
            if effective_success
            else f"SearXNG generated {selected_count}/{minimum_news_to_save} minimum news items."
        )
        if effective_success and section is None:
            message += f" courses={support_counts.get('courses', 0)} movies={support_counts.get('movies', 0)}."
        if performance:
            message += (
                f" fetch={float(performance.get('fetch_seconds', 0) or 0):.1f}s"
                f" gpt={float(performance.get('gpt_seconds', 0) or 0):.1f}s"
            )
        payload = {"success": effective_success, "message": message, "performance": performance}
        GENERATOR_STATE["last_log_tail"] = message
        GENERATOR_STATE["last_result"] = payload
        trace(f"SearXNG AI updates pipeline finished in {total_seconds:.1f}s success={effective_success}")
        return payload
    except Exception as exc:
        payload = {"success": False, "message": str(exc)}
        GENERATOR_STATE["last_log_tail"] = str(exc)
        GENERATOR_STATE["last_result"] = payload
        return payload
    finally:
        GENERATOR_STATE["running"] = False
        GENERATOR_STATE["finished_at"] = time.time()
        GENERATOR_STATE["sections"] = []
        GENERATOR_LOCK.release()


# Server role: Block the disabled legacy generator path.
def run_generator(section=None, force_refresh=False, preserve_visible_sections=None):
    """Legacy generator runtime is intentionally disabled.

    All generate/refill work is routed through backend.ai_update_pipeline.
    This guard keeps old UI entry points on the modular pipeline.
    """
    return {
        "success": False,
        "message": "Legacy generator is disabled. The server uses ai_update_pipeline only.",
    }


# Server role: Start a background generation/refill thread for the UI.
def start_generator_background(section=None, reason="manual", force_refresh=False, preserve_visible_sections=None):
    if NEWS_JSON_ONLY_MODE:
        trace(
            f"Pipeline blocked by NEWS_JSON_ONLY_MODE section={section or 'all'} "
            f"reason={reason} preserve_visible_sections={preserve_visible_sections or []}"
        )
        return {
            "success": True,
            "running": False,
            "message": "JSON-only mode active. Using current newsletter content without fetching.",
        }
    if GENERATOR_STATE["running"]:
        trace(f"Pipeline already running; request joined section={section or 'all'}")
        message = section_feedback(section) if section else "Fetching more content..."
        return {"success": True, "running": True, "message": message}

    now = time.time()
    if reason == "auto":
        last_auto_start = GENERATOR_STATE.get("last_auto_start")
        if last_auto_start and now - last_auto_start < AUTO_FETCH_COOLDOWN:
            remaining = int(AUTO_FETCH_COOLDOWN - (now - last_auto_start))
            trace(
                f"Auto-fetch skipped section={section or 'all'}; "
                f"cooldown active for {remaining}s"
            )
            return {
                "success": True,
                "running": False,
                "message": f"Waiting before another automatic fetch ({remaining}s).",
            }
        GENERATOR_STATE["last_auto_start"] = now

    if section is None and reason != "auto" and not preserve_visible_sections:
        save_previous_generation_snapshot()

    GENERATOR_STATE["running"] = True
    GENERATOR_STATE["sections"] = [section] if section else list(REQUIRED_COUNTS)
    GENERATOR_STATE["started_at"] = time.time()
    GENERATOR_STATE["finished_at"] = None
    GENERATOR_STATE["last_log_tail"] = ""
    GENERATOR_STATE["last_result"] = None
    GENERATOR_STATE["timeline"] = []
    GENERATOR_STATE["active_stage_key"] = ""
    GENERATOR_STATE["stage_started_at"] = {}
    GENERATOR_STATE["stage_completed_at"] = {}
    trace(
        f"Queueing pipeline thread section={section or 'all'} "
        f"reason={reason} force_refresh={force_refresh} "
        f"preserve_visible_sections={preserve_visible_sections or []}"
    )
    target = run_ai_updates_generator if should_use_ai_updates_generator(section, preserve_visible_sections) else run_generator
    if target is run_ai_updates_generator:
        GENERATOR_STATE["sections"] = ["items"]
        trace("Generate routed to SearXNG AI updates pipeline")
    thread = threading.Thread(
        target=target,
        args=(section, force_refresh, preserve_visible_sections),
        daemon=True,
    )
    thread.start()
    message = section_feedback(section) if section else "Fetching more content..."
    return {"success": True, "running": True, "message": message}


# Server role: Rewrite one card title/body through OpenAI for manual edits.
def rewrite_text(title, text, instruction):
    if not openai_client:
        return {
            "title": title,
            "text": f"نسخة محررة: {text}" if text else text,
            "mode": "fallback",
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
        response = openai_client.chat.completions.create(
            model=REWRITE_MODEL,
            temperature=0.4,
            messages=[
                {"role": "system", "content": "You are a precise Arabic editor. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        return {
            "title": payload.get("title", title).strip() or title,
            "text": payload.get("text", text).strip() or text,
            "mode": "ai",
        }
    except Exception:
        return {"title": title, "text": f"نسخة محررة: {text}" if text else text, "mode": "fallback"}


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

    # Server role: Add CORS headers for local frontend/API access.
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    # Server role: Answer CORS preflight requests.
    def do_OPTIONS(self):
        if TRACE_HTTP:
            trace(f"OPTIONS {urllib.parse.urlparse(self.path).path}")
        self.send_response(200)
        self.end_headers()

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
    def send_pdf(self, payload, filename="AINewsletter_v0.1.pdf"):
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    # Server role: Proxy remote images needed by the UI/PDF preview.
    def send_image_proxy(self, query):
        raw_url = (query.get("url", [""])[0] or "").strip()
        try:
            parsed = urllib.parse.urlparse(raw_url)
        except Exception:
            parsed = None
        if not parsed or parsed.scheme not in {"http", "https"} or not parsed.netloc:
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
            with urllib.request.urlopen(request, timeout=10) as response:
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
        auto_fetch_enabled = (query.get("auto", ["0"])[0] or "0").lower() in {"1", "true", "yes", "on"}
        if TRACE_HTTP:
            trace(f"GET {path or '/'}")
        if path in {"", "/"}:
            self.send_response(302)
            self.send_header("Location", "/UI.html")
            self.end_headers()
            return
        if path.lower() == "/ui.html" and path != "/UI.html":
            self.path = "/UI.html"
            return super().do_GET()
        if path == f"{API_BASE}/image-proxy":
            return self.send_image_proxy(query)
        if path == f"{API_BASE}/refill/progress":
            return self.send_json(current_single_refill_state())
        if path == f"{API_BASE}/news":
            store = load_store()
            hidden_news = store.get("items", [])[DISPLAY_COUNTS.get("items", REQUIRED_COUNTS["items"]):]
            feedback = []
            missing = missing_sections(store)
            display_missing = missing_display_sections(store)
            if auto_fetch_enabled and display_missing and not GENERATOR_STATE["running"] and not NEWS_JSON_ONLY_MODE:
                section = display_missing[0] if len(display_missing) == 1 else None
                result = start_generator_background(section, reason="auto")
                feedback.append(result["message"])
            elif auto_fetch_enabled and NEWS_JSON_ONLY_MODE:
                feedback.append("JSON-only mode active. Showing current news.json content only.")
            return self.send_json({
                "items": visible_items(store, "items"),
                "backup_news": hidden_news,
                "movies": store.get("movies", []),
                "courses": store.get("courses", []),
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
        if path == f"{API_BASE}/ai-updates":
            ai_updates_report_file = FRONTEND_DIR / "ai_updates_run_report.json"
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

    # Server role: Handle generate/refill/edit/settings API actions.
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if TRACE_HTTP:
            trace(f"POST {path}")
        data = read_json_body(self)
        store = load_store()

        if path.startswith(f"{API_BASE}/rewrite/"):
            item_id = path.split("/")[-1]
            item = find_item(store["items"], item_id)
            if not item:
                return self.send_json({"error": "News item not found"}, 404)
            rewritten = rewrite_text(item["title"], item["text"], data.get("instruction", ""))
            item["title"] = rewritten["title"]
            item["text"] = rewritten["text"]
            save_store(store)
            return self.send_json({"success": True, "item": item, "rewrite_mode": rewritten["mode"]})

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
            preview_html = str(data.get("html") or "")
            width = data.get("width") or 1000
            height = data.get("height") or 1340
            direction = str(data.get("direction") or "rtl")
            pdf_profile = str(data.get("pdf_profile") or data.get("share_profile") or PDF_EXPORT_PROFILE)
            pdf_scale = data.get("scale")
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
                )
            except Exception as exc:
                trace(f"PDF export failed: {exc}")
                return self.send_json({"success": False, "error": str(exc)}, 500)
            return self.send_pdf(pdf_bytes)

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
                    allow_fetch=True,
                    live_fetch=True,
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
            return self.send_json({"success": True, "title": rewritten["title"], "text": rewritten["text"], "rewrite_mode": rewritten["mode"]})

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
            store, result = update_card_from_client(store, section, index, data.get("item") or data)
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

    # Server role: Handle direct card/settings state updates.
    def do_PUT(self):
        path = urllib.parse.urlparse(self.path).path
        if TRACE_HTTP:
            trace(f"PUT {path}")
        data = read_json_body(self)
        store = load_store()

        if path.startswith(f"{API_BASE}/news/"):
            item_id = path.split("/")[-1]
            item = find_item(store["items"], item_id)
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
            save_store(store)
            return self.send_json({"success": True, "item": normalize_item(item, "news")})

        if path.startswith(f"{API_BASE}/content/"):
            parts = path.strip("/").split("/")
            if len(parts) < 4:
                return self.send_json({"error": "Invalid content path"}, 400)
            section, item_id = parts[2], parts[3]
            if section not in SECTION_KEYS:
                return self.send_json({"error": "Invalid section"}, 400)
            item = find_item(store[section], item_id)
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
            save_store(store)
            return self.send_json({"success": True, "item": normalize_item(item, SECTION_TO_CONTENT_TYPE.get(section, "news")), "section": section})

        if path.startswith(f"{API_BASE}/feature/"):
            feature_mode = path.split("/")[-1]
            if feature_mode not in FEATURE_MODES:
                return self.send_json({"error": "Invalid feature mode"}, 400)
            store["feature_mode"] = feature_mode
            save_store(store)
            return self.send_json({"success": True, "feature_mode": feature_mode, "feature_item": get_feature_item(store)})

        if path == f"{API_BASE}/state":
            restored = {
                "items": data.get("items") if isinstance(data.get("items"), list) else store.get("items", []),
                "movies": data.get("movies") if isinstance(data.get("movies"), list) else store.get("movies", []),
                "courses": data.get("courses") if isinstance(data.get("courses"), list) else store.get("courses", []),
                "template": {**store.get("template", {}), **(data.get("template") if isinstance(data.get("template"), dict) else {})},
                "feature_mode": data.get("feature_mode") if data.get("feature_mode") in FEATURE_MODES else store.get("feature_mode", "course"),
            }
            save_store(restored)
            restored = load_store()
            return self.send_json({
                "success": True,
                "items": visible_items(restored, "items"),
                "movies": restored.get("movies", []),
                "courses": restored.get("courses", []),
                "template": restored["template"],
                "feature_mode": restored["feature_mode"],
                "feature_item": get_feature_item(restored),
                "needs_fetch": missing_display_sections(restored),
                "needs_fetch_required": missing_sections(restored),
                "previous_counts": previous_generation_counts(),
            })

        if path == f"{API_BASE}/reorder/items":
            ids = data.get("ids") or []
            if not isinstance(ids, list):
                return self.send_json({"error": "ids must be a list"}, 400)
            by_id = {i["id"]: i for i in store["items"]}
            reordered = [by_id[i] for i in ids if i in by_id]
            for item in store["items"]:
                if item["id"] not in ids:
                    reordered.append(item)
            store["items"] = reorder_positions(reordered)
            save_store(store)
            return self.send_json({"success": True, "items": visible_items(store, "items")})

        return self.send_json({"error": "Route not found"}, 404)

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = 8000
    try:
        # Start the AI updates background daemon
        start_background_daemon()
        
        with ThreadedTCPServer((host, port), BackendHandler) as httpd:
            print(f"Running: http://{host}:{port}/UI.html", flush=True)
            trace(f"Serving static files from {FRONTEND_DIR}")
            trace(f"API base {API_BASE}; pipeline backend\\ai_update_pipeline")
            trace(f"HTTP tracing is {'on' if TRACE_HTTP else 'off'}")
            httpd.serve_forever()
    except OSError as exc:
        print(f"Could not start server on http://{host}:{port}: {exc}", flush=True)
        print("Another server is probably still running. Stop old terminals or run:", flush=True)
        print("  netstat -ano | findstr :8000", flush=True)
        print("  taskkill /PID <PID> /F", flush=True)
        raise



