# This file is part of the AI newsletter system.
"""PDF export helpers for rendering the newsletter preview."""

from __future__ import annotations

import base64
import os
import re
import sys
from html import escape as html_escape
from pathlib import Path

from backend.utils.debug_logging import trace

ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR.parent / "frontend"
UI_HTML_FILE = FRONTEND_DIR / "News.html"
VENV_SITE_PACKAGES = ROOT_DIR.parent / "venv" / "Lib" / "site-packages"
EDGE_EXECUTABLES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]
PDF_EXPORT_PROFILE = os.getenv("PDF_EXPORT_PROFILE", "whatsapp").strip().lower() or "whatsapp"
PDF_EXPORT_SCALE_OVERRIDE = os.getenv("PDF_EXPORT_SCALE", "").strip()

# Performs the resolve frontend html file helper step.
def resolve_frontend_html_file(source_file: str = "") -> Path:
    """Return the frontend HTML file whose styles should shape export."""
    raw_name = Path(str(source_file or "")).name
    if raw_name.lower().endswith(".html"):
        candidate = FRONTEND_DIR / raw_name
        try:
            if candidate.resolve().parent == FRONTEND_DIR.resolve() and candidate.exists():
                return candidate
        except Exception:
            pass
    return UI_HTML_FILE


# Server role: Read inline and linked local UI CSS for PDF export.
def extract_ui_styles(source_file: str = "") -> str:
    html_file = resolve_frontend_html_file(source_file)
    try:
        html = html_file.read_text(encoding="utf-8")
    except Exception:
        return ""
    styles = re.findall(
        r"<style[^>]*>(.*?)</style>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    linked_styles = re.findall(
        r"<link\b(?=[^>]*\brel=[\"'][^\"']*\bstylesheet\b[^\"']*[\"'])"
        r"(?=[^>]*\bhref=[\"']([^\"']+)[\"'])[^>]*>",
        html,
        flags=re.IGNORECASE,
    )
    for href in linked_styles:
        if re.match(r"^(?:[a-z]+:|//|/)", href, flags=re.IGNORECASE):
            continue
        candidate = html_file.parent / href.split("?", 1)[0].split("#", 1)[0]
        try:
            resolved = candidate.resolve()
            if resolved.parent != FRONTEND_DIR.resolve() or resolved.suffix.lower() != ".css":
                continue
            styles.append(resolved.read_text(encoding="utf-8"))
        except Exception as exc:
            trace(f"PDF linked stylesheet skipped for {href}: {exc}")
    return "\n\n".join(strip_print_media_blocks(style) for style in styles)


# Server role: Inline local Effra fonts so Playwright PDF rendering does not
# depend on resolving relative font URLs from generated HTML.
def embedded_pdf_font_css() -> str:
    font_specs = [
        ("Avenir", "Effra_Rg.ttf", "400"),
        ("Avenir", "Effra_Md.ttf", "500"),
        ("Effra Medium Heading", "Effra_Md.ttf", "700"),
    ]
    rules = []
    for family, filename, weight in font_specs:
        path = FRONTEND_DIR / "fonts" / filename
        try:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        except Exception as exc:
            trace(f"PDF font embed skipped for {filename}: {exc}")
            continue
        rules.append(
            f"""
    @font-face {{
      font-family: "{family}";
      src: url("data:font/ttf;base64,{encoded}") format("truetype");
      font-weight: {weight};
      font-style: normal;
      font-display: block;
    }}"""
        )
    return "\n".join(rules)


# Server role: Remove print-only CSS before browser-rendered PDF export.
def strip_print_media_blocks(css: str) -> str:
    marker = "@media print"
    output = []
    index = 0
    while True:
        start = css.find(marker, index)
        if start < 0:
            output.append(css[index:])
            break
        output.append(css[index:start])
        brace = css.find("{", start)
        if brace < 0:
            index = start + len(marker)
            continue
        depth = 0
        end = brace
        while end < len(css):
            char = css[end]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end += 1
                    break
            end += 1
        index = end
    return "".join(output)


# Server role: Clamp requested PDF dimensions to safe bounds.
def normalize_pdf_dimension(value, fallback):
    try:
        parsed = float(value)
        if parsed > 0:
            return max(1, min(6000, parsed))
    except Exception:
        pass
    return fallback


# Server role: Resolve the default PDF scale from environment/profile.
def default_pdf_scale(profile=""):
    if PDF_EXPORT_SCALE_OVERRIDE:
        try:
            parsed = float(PDF_EXPORT_SCALE_OVERRIDE)
            if parsed > 0:
                return max(1.0, min(3.0, parsed))
        except Exception:
            pass
    profile = (profile or PDF_EXPORT_PROFILE or "").strip().lower()
    if profile in {"quality", "print", "high_quality", "hires"}:
        return 2.0
    return 1.0


# Server role: Clamp requested PDF export scale.
def normalize_pdf_scale(value, fallback=None):
    if fallback is None:
        fallback = default_pdf_scale()
    try:
        parsed = float(value)
        if parsed > 0:
            return max(1.0, min(3.0, parsed))
    except Exception:
        pass
    return fallback


# Server role: Wrap preview HTML with server CSS for PDF rendering.
def build_preview_pdf_document(preview_html: str, width: float, height: float, origin: str, direction: str = "rtl", scale: float = 1.0, source_file: str = "") -> str:
    """Wrap the live preview HTML in a clean document for Playwright export."""
    css = extract_ui_styles(source_file)
    if "cultural-assistant" in preview_html and ".cultural-assistant-strip" not in css:
        css = extract_ui_styles("News.html")
    font_css = embedded_pdf_font_css()
    direction = "ltr" if str(direction).lower() == "ltr" else "rtl"
    width = normalize_pdf_dimension(width, 1000)
    height = normalize_pdf_dimension(height, 1340)
    scale = normalize_pdf_scale(scale)
    output_width = normalize_pdf_dimension(width * scale, width)
    output_height = normalize_pdf_dimension(height * scale, height)
    safe_origin = html_escape(origin or "")
    return f"""<!doctype html>
<html lang="ar" dir="{direction}">
<head>
  <meta charset="utf-8">
  <base href="{safe_origin}/">
  <style>
{font_css}
{css}
    @page {{ size: {output_width}px {output_height}px; margin: 0; }}
    html, body {{
      margin: 0 !important;
      padding: 0 !important;
      width: {output_width}px !important;
      min-width: {output_width}px !important;
      min-height: {output_height}px !important;
      background: transparent !important;
      overflow: visible !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .pdf-backend-root {{
      width: {output_width}px !important;
      height: {output_height}px !important;
      margin: 0 !important;
      padding: 0 !important;
      overflow: visible !important;
      background: transparent !important;
    }}
    .pdf-backend-root .preview-window {{
      width: max-content !important;
      height: max-content !important;
      max-height: none !important;
      overflow: visible !important;
      padding: 0 !important;
      margin: 0 !important;
      border: 0 !important;
      box-shadow: none !important;
      background: transparent !important;
      backdrop-filter: none !important;
      -webkit-backdrop-filter: none !important;
      transform: scale({scale}) !important;
      transform-origin: top left !important;
    }}
    .pdf-backend-root .page {{
      width: {width}px !important;
      max-width: {width}px !important;
      min-width: {width}px !important;
      height: {height}px !important;
      min-height: {height}px !important;
      margin: 0 !important;
      transform: none !important;
      scale: 1 !important;
      box-sizing: border-box !important;
    }}
  </style>
</head>
<body>
  <div class="pdf-backend-root">{preview_html}</div>
</body>
</html>"""


WHATSAPP_PDF_PROFILES = {"whatsapp", "wa", "mobile", "share", "compressed"}


# Server role: Read JPEG quality attempts for WhatsApp-friendly PDFs.
def whatsapp_pdf_quality_values():
    """Return JPEG quality retry levels for the single WhatsApp/browser PDF."""
    try:
        configured = int(os.getenv("PDF_EXPORT_WHATSAPP_JPEG_QUALITY", "95") or "95")
    except Exception:
        configured = 95
    configured = max(45, min(95, configured))
    values = [configured, 92, 88, 82, 76, 68, 60]
    unique = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


# Server role: Read the target max byte size for WhatsApp-friendly PDFs.
def whatsapp_pdf_target_bytes():
    """Soft size target; export still succeeds if quality retries cannot reach it."""
    try:
        mb = float(os.getenv("PDF_EXPORT_WHATSAPP_MAX_MB", "10") or "10")
    except Exception:
        mb = 10.0
    return max(1, min(25, mb)) * 1024 * 1024


# Server role: Read raster scale for WhatsApp-friendly PDF screenshots.
def whatsapp_pdf_raster_scale():
    """Increase capture sharpness without changing the exported PDF page size."""
    raw_value = (
        os.getenv("PDF_EXPORT_WHATSAPP_RASTER_SCALE", "").strip()
        or os.getenv("PDF_EXPORT_WHATSAPP_SCALE", "2.0").strip()
    )
    try:
        parsed = float(raw_value)
    except Exception:
        parsed = 2.0
    return max(1.0, min(3.0, parsed))


# Server role: Choose Playwright device scale for PDF rendering.
def pdf_device_scale_factor(profile: str, pdf_scale: float) -> float:
    """Pick Playwright raster density separately from the visible PDF scale."""
    profile = (profile or "").strip().lower()
    if profile in WHATSAPP_PDF_PROFILES:
        return whatsapp_pdf_raster_scale()
    return min(2.0, normalize_pdf_scale(pdf_scale))


# Server role: Extract source-card link rectangles for image-based PDFs.
def extract_whatsapp_pdf_links(rendered_page, output_width: float, output_height: float) -> list[dict]:
    """Read clickable card/source rectangles from the rendered preview."""
    try:
        raw_links = rendered_page.evaluate("""() => {
          const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 1000;
          const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 1600;
          const seen = new Set();
          const cleanHref = href => {
            try {
              const url = new URL(href, document.baseURI);
              if (!['http:', 'https:'].includes(url.protocol)) return '';
              return url.href;
            } catch {
              return '';
            }
          };
          const rectFor = element => {
            const rect = element.getBoundingClientRect();
            const left = Math.max(0, Math.min(viewportWidth, rect.left));
            const top = Math.max(0, Math.min(viewportHeight, rect.top));
            const right = Math.max(0, Math.min(viewportWidth, rect.right));
            const bottom = Math.max(0, Math.min(viewportHeight, rect.bottom));
            return {x:left, y:top, w:Math.max(0, right - left), h:Math.max(0, bottom - top)};
          };
          const add = (element, href, label) => {
            const url = cleanHref(href);
            if (!url) return;
            const rect = rectFor(element);
            if (rect.w < 8 || rect.h < 8) return;
            const key = `${url}|${Math.round(rect.x)}|${Math.round(rect.y)}|${Math.round(rect.w)}|${Math.round(rect.h)}`;
            if (seen.has(key)) return;
            seen.add(key);
            links.push({...rect, href:url, label:String(label || 'Open source')});
          };
          const links = [];
          document.querySelectorAll('.news-card[data-url], .feature-card[data-url], .movie-card[data-url]').forEach(card => {
            add(card, card.dataset.url || '', card.querySelector('.card-title,.movie-title')?.textContent || 'Open card source');
          });
          document.querySelectorAll('a[href]').forEach(anchor => {
            add(anchor, anchor.getAttribute('href') || '', anchor.textContent || 'Open source');
          });
          return links;
        }""")
    except Exception as exc:
        trace(f"PDF whatsapp link extraction skipped: {exc}")
        return []

    links = []
    scale_x = normalize_pdf_dimension(output_width, 1000) / max(1, normalize_pdf_dimension(output_width, 1000))
    scale_y = normalize_pdf_dimension(output_height, 1600) / max(1, normalize_pdf_dimension(output_height, 1600))
    for raw in raw_links or []:
        try:
            href = str(raw.get("href") or "").strip()
            if not href.startswith(("http://", "https://")):
                continue
            x = max(0.0, min(float(output_width), float(raw.get("x") or 0) * scale_x))
            y = max(0.0, min(float(output_height), float(raw.get("y") or 0) * scale_y))
            w = max(1.0, min(float(output_width) - x, float(raw.get("w") or 0) * scale_x))
            h = max(1.0, min(float(output_height) - y, float(raw.get("h") or 0) * scale_y))
            label = re.sub(r"\s+", " ", str(raw.get("label") or "Open source")).strip()[:120]
            links.append({"href": href, "x": x, "y": y, "w": w, "h": h, "label": label})
        except Exception:
            continue
    return links[:40]


# Server role: Build an HTML wrapper for a rasterized one-page PDF.
def build_image_pdf_document(jpeg_base64: str, width: float, height: float, links: list[dict] | None = None) -> str:
    """Build a one-image PDF document that opens reliably in mobile messengers."""
    width = normalize_pdf_dimension(width, 1000)
    height = normalize_pdf_dimension(height, 1600)
    link_html = []
    for index, link in enumerate(links or []):
        href = html_escape(str(link.get("href") or ""), quote=True)
        if not href:
            continue
        label = html_escape(str(link.get("label") or f"Open link {index + 1}"), quote=True)
        x = max(0.0, min(width, float(link.get("x") or 0)))
        y = max(0.0, min(height, float(link.get("y") or 0)))
        w = max(1.0, min(width - x, float(link.get("w") or 0)))
        h = max(1.0, min(height - y, float(link.get("h") or 0)))
        link_html.append(
            f'<a href="{href}" title="{label}" '
            f'style="left:{x:.2f}px;top:{y:.2f}px;width:{w:.2f}px;height:{h:.2f}px">{label}</a>'
        )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    @page {{ size: {width}px {height}px; margin: 0; }}
    html, body {{
      margin: 0 !important;
      padding: 0 !important;
      width: {width}px !important;
      height: {height}px !important;
      overflow: hidden !important;
      background: #fff !important;
    }}
    img {{
      display: block;
      width: {width}px;
      height: {height}px;
      object-fit: fill;
    }}
    .pdf-link-layer {{
      position: absolute;
      inset: 0;
      width: {width}px;
      height: {height}px;
      z-index: 2;
    }}
    .pdf-link-layer a {{
      position: absolute;
      display: block;
      overflow: hidden;
      color: rgba(255,255,255,0.001);
      background: rgba(255,255,255,0.001);
      font-size: 1px;
      line-height: 1;
      text-decoration: none;
    }}
  </style>
</head>
<body><img alt="AINewsletter_v02" src="data:image/jpeg;base64,{jpeg_base64}"><div class="pdf-link-layer">{''.join(link_html)}</div></body>
</html>"""


# Server role: Render a compressed image-based PDF for mobile sharing.
def render_whatsapp_image_pdf(browser, rendered_page, output_width: float, output_height: float) -> bytes:
    """
    Rasterize the final newsletter page into a compressed JPEG, then wrap it in
    a single-page PDF. WhatsApp and iOS preview this shape more reliably than a
    complex web/PDF document with many remote images and embedded fonts.
    """
    output_width = normalize_pdf_dimension(output_width, 1000)
    output_height = normalize_pdf_dimension(output_height, 1600)
    links = extract_whatsapp_pdf_links(rendered_page, output_width, output_height)
    target_bytes = whatsapp_pdf_target_bytes()
    best_pdf = None
    best_quality = None
    for quality in whatsapp_pdf_quality_values():
        jpeg_bytes = rendered_page.screenshot(type="jpeg", quality=quality, full_page=False)
        jpeg_base64 = base64.b64encode(jpeg_bytes).decode("ascii")
        image_html = build_image_pdf_document(jpeg_base64, output_width, output_height, links)
        image_page = browser.new_page(viewport={"width": int(output_width), "height": int(output_height)}, device_scale_factor=1)
        try:
            image_page.set_content(image_html, wait_until="load", timeout=15000)
            pdf_bytes = image_page.pdf(
                print_background=True,
                prefer_css_page_size=True,
                width=f"{output_width}px",
                height=f"{output_height}px",
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            image_page.close()
        if best_pdf is None or len(pdf_bytes) < len(best_pdf):
            best_pdf = pdf_bytes
            best_quality = quality
        if len(pdf_bytes) <= target_bytes:
            trace(
                f"PDF whatsapp rasterized quality={quality} "
                f"jpeg={len(jpeg_bytes) / 1024:.1f}KB pdf={len(pdf_bytes) / 1024:.1f}KB links={len(links)}"
            )
            return pdf_bytes
    trace(
        f"PDF whatsapp rasterized best_quality={best_quality} "
        f"pdf={len(best_pdf or b'') / 1024:.1f}KB target={target_bytes / 1024:.1f}KB links={len(links)}"
    )
    return best_pdf or b""


# Server role: Export the frontend preview HTML to PDF bytes.
def export_preview_pdf_bytes(preview_html: str, width: float, height: float, origin: str, direction: str = "rtl", scale=None, profile: str = "", source_file: str = "") -> bytes:
    """Render the browser preview into a PDF using Playwright/Chromium."""
    if not preview_html or "page" not in preview_html:
        raise ValueError("Preview HTML is missing or invalid")
    pdf_profile = (profile or PDF_EXPORT_PROFILE or "whatsapp").strip().lower()
    base_width = normalize_pdf_dimension(width, 1000)
    base_height = normalize_pdf_dimension(height, 1340)
    pdf_scale = normalize_pdf_scale(scale, default_pdf_scale(pdf_profile))
    output_width = normalize_pdf_dimension(base_width * pdf_scale, base_width)
    output_height = normalize_pdf_dimension(base_height * pdf_scale, base_height)
    document_html = build_preview_pdf_document(preview_html, base_width, base_height, origin, direction, pdf_scale, source_file)
    trace(
        f"PDF export profile={pdf_profile} base={base_width:.0f}x{base_height:.0f} "
        f"scale={pdf_scale:.2f} output={output_width:.0f}x{output_height:.0f}"
    )
    try:
        if VENV_SITE_PACKAGES.exists() and str(VENV_SITE_PACKAGES) not in sys.path:
            sys.path.insert(0, str(VENV_SITE_PACKAGES))
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium") from exc

    with sync_playwright() as p:
        try:
            edge_path = next((path for path in EDGE_EXECUTABLES if path.exists()), None)
            if edge_path:
                browser = p.chromium.launch(executable_path=str(edge_path))
            else:
                browser = p.chromium.launch()
        except Exception as exc:
            raise RuntimeError("Chromium/Edge for Playwright could not start. Install Microsoft Edge or run: playwright install chromium") from exc
        try:
            page = browser.new_page(
                viewport={"width": int(output_width), "height": int(output_height)},
                device_scale_factor=pdf_device_scale_factor(pdf_profile, pdf_scale),
            )
            page.emulate_media(media="screen")
            page.set_content(document_html, wait_until="networkidle", timeout=30000)
            page.evaluate("""async () => {
              if (document.fonts && document.fonts.ready) await document.fonts.ready;
              const images = Array.from(document.images || []);
              await Promise.all(images.map(img => img.complete ? true : new Promise(resolve => {
                img.onload = resolve;
                img.onerror = resolve;
                setTimeout(resolve, 15000);
              })));
            }""")
            if pdf_profile in WHATSAPP_PDF_PROFILES:
                return render_whatsapp_image_pdf(browser, page, output_width, output_height)
            return page.pdf(
                print_background=True,
                prefer_css_page_size=True,
                width=f"{output_width}px",
                height=f"{output_height}px",
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            browser.close()

