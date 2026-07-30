"""HTTP payload helpers for importing and converting PDF versions.

The current product stores uploaded PDFs as binary version records. It does
not reconstruct newsletter cards from PDF text or layout.
"""

from __future__ import annotations

import base64
import datetime
import io
import json
from email.parser import BytesParser
from email.policy import default as email_default_policy

def attach_newsletter_json_to_pdf(pdf_bytes: bytes, newsletter_payload: dict) -> bytes:
    """Embed the editable newsletter payload in an exported PDF attachment."""
    if not isinstance(newsletter_payload, dict) or not newsletter_payload.get("items"):
        return pdf_bytes
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(pdf_bytes))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        if reader.metadata:
            metadata = {
                str(key): str(value)
                for key, value in dict(reader.metadata).items()
                if value is not None
            }
            if metadata:
                writer.add_metadata(metadata)

        payload = dict(newsletter_payload)
        payload_metadata = (
            dict(payload.get("metadata"))
            if isinstance(payload.get("metadata"), dict)
            else {}
        )
        payload_metadata.update(
            {
                "embedded_in_pdf": True,
                "embedded_schema": "ainewsletter_version_v1",
                "embedded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        )
        payload["metadata"] = payload_metadata
        attachment = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        writer.add_attachment("ainewsletter-version.json", attachment)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()
    except Exception:
        # Exporting the rendered PDF remains useful even if attachment metadata
        # cannot be added to an unusual or damaged PDF.
        return pdf_bytes


def read_json_body_from_handler(handler) -> dict:
    """Read a JSON request body, returning an empty object for invalid input."""
    try:
        length = int(handler.headers.get("Content-Length", 0) or 0)
    except (TypeError, ValueError):
        length = 0
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def decode_pdf_base64(value) -> bytes:
    """Decode a raw or data-URL base64 PDF value."""
    text = str(value or "").strip()
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    if not text:
        return b""
    return base64.b64decode(text, validate=False)


def read_multipart_upload(
    handler,
    field_name: str = "pdf",
    max_bytes: int = 25 * 1024 * 1024,
) -> tuple[bytes | None, str, str]:
    """Read one PDF part from an HTTP multipart request."""
    try:
        length = int(handler.headers.get("Content-Length", 0) or 0)
    except (TypeError, ValueError):
        length = 0
    if length <= 0:
        return None, "", "empty upload"
    if length > max_bytes:
        handler.rfile.read(length)
        return None, "", "file too large"

    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        handler.rfile.read(length)
        return None, "", "expected multipart/form-data"

    body = handler.rfile.read(length)
    header = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n\r\n"
    ).encode("utf-8", errors="ignore")
    message = BytesParser(policy=email_default_policy).parsebytes(header + body)
    if not message.is_multipart():
        return None, "", "invalid multipart upload"

    fallback = None
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename() or ""
        payload = part.get_payload(decode=True) or b""
        if not payload:
            continue
        if name == field_name:
            return payload, filename, ""
        if filename.lower().endswith(".pdf") and fallback is None:
            fallback = (payload, filename)
    if fallback:
        return fallback[0], fallback[1], ""
    return None, "", "no pdf file found"
