# This file is part of the AI newsletter system.
"""HTTP route handlers for version management (list/get/save/restore/delete,
PDF upload). Schema/migration lives in versions_db.py; PDF text extraction
lives in pdf_import.py - this module only dispatches HTTP requests.
"""

from __future__ import annotations

import datetime
import json
import re
import urllib.parse

import psycopg2

from backend.utils.debug_logging import trace
from backend.storage.newsletter_store import (
    NEWS_JSON_FILE,
    canonical_newsletter_payload,
    publish_current_store,
    save_store,
    store_from_payload,
)
from backend.storage.manage_versions.versions_db import (
    API_BASE,
    backup_versions_db,
    init_versions_db,
    load_current_news_json_text,
    parse_version_id,
    normalize_version_title,
    requested_version_title_from_news,
    save_pdf_version_file,
    serialize_db_datetime,
    title_from_pdf_filename,
    version_title_exists,
    version_title_from_news,
    versions_db,
)
from backend.storage.manage_versions.pdf_import import (
    decode_pdf_base64,
    read_json_body_from_handler,
    read_multipart_upload,
)


def handle_versions_get(handler, path):
    if path == f"{API_BASE}/versions":
        init_versions_db()
        user = handler.current_user() if hasattr(handler, "current_user") else None
        is_admin = bool(user and user.get("is_admin"))
        con = versions_db()
        try:
            # PDF BYTEA change: report PDF size from PostgreSQL binary data while
            # leaving JSON content-size behavior unchanged.
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, issue_number, title, created_at,
                           CASE
                               WHEN COALESCE(kind, 'json') = 'pdf' THEN COALESCE(octet_length(pdf_data), 0)
                               ELSE length(content)
                           END,
                           kind, pdf_path, original_filename, COALESCE(hidden_from_users, FALSE)
                    FROM versions
                    WHERE (%s OR NOT COALESCE(hidden_from_users, FALSE))
                    ORDER BY created_at DESC, id DESC
                    """,
                    (is_admin,),
                )
                rows = cur.fetchall()
        finally:
            con.close()
        items = []
        for row in rows:
            kind = (row[5] or "json").strip() or "json"
            size = row[4] or 0
            items.append({
                "id": row[0],
                "issue_number": row[1],
                "title": row[2],
                "created_at": serialize_db_datetime(row[3]),
                "content_size": size,
                "kind": kind,
                "original_filename": row[7] or "",
                "hidden_from_users": bool(row[8]),
            })
        handler.send_json([
            item for item in items
        ])
        return True

    pdf_version_id = parse_version_id(path, "/pdf")
    if pdf_version_id is not None:
        init_versions_db()
        con = versions_db()
        try:
            # PDF BYTEA change: load binary data directly from PostgreSQL instead
            # of resolving and reading the deprecated local pdf_path.
            with con.cursor() as cur:
                cur.execute(
                    "SELECT title, kind, pdf_data, original_filename, COALESCE(hidden_from_users, FALSE) FROM versions WHERE id = %s",
                    (pdf_version_id,),
                )
                row = cur.fetchone()
        finally:
            con.close()
        if not row:
            handler.send_json({"error": "not found"}, 404)
            return True
        user = handler.current_user() if hasattr(handler, "current_user") else None
        if row[4] and not (user and user.get("is_admin")):
            handler.send_json({"error": "not found"}, 404)
            return True
        if (row[1] or "json") != "pdf":
            handler.send_json({"error": "version is not a PDF"}, 400)
            return True
        if row[2] is None:
            handler.send_json({"error": "PDF data not found"}, 404)
            return True
        # PDF BYTEA change: psycopg2 returns BYTEA as memoryview; convert it to
        # bytes before streaming with the unchanged application/pdf response.
        payload = bytes(row[2])
        display_name = str(row[0] or row[3] or f"version_{pdf_version_id}.pdf").strip()
        display_name = re.sub(r"[\r\n\\/]+", "_", display_name).strip("._ ") or f"version_{pdf_version_id}"
        if not display_name.lower().endswith(".pdf"):
            display_name = f"{display_name}.pdf"
        quoted_name = urllib.parse.quote(display_name)
        handler.send_response(200)
        handler.send_header("Content-Type", "application/pdf")
        handler.send_header("Content-Disposition", f"inline; filename*=UTF-8''{quoted_name}")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)
        return True

    export_version_id = parse_version_id(path, "/export")
    if export_version_id is not None:
        init_versions_db()
        con = versions_db()
        try:
            # PostgreSQL change: retrieve export content through a psycopg2 cursor.
            with con.cursor() as cur:
                cur.execute(
                    "SELECT content, COALESCE(hidden_from_users, FALSE), title FROM versions WHERE id = %s",
                    (export_version_id,),
                )
                row = cur.fetchone()
        finally:
            con.close()
        if not row:
            handler.send_json({"error": "not found"}, 404)
            return True
        user = handler.current_user() if hasattr(handler, "current_user") else None
        if row[1] and not (user and user.get("is_admin")):
            handler.send_json({"error": "not found"}, 404)
            return True
        payload = str(row[0] or "{}").encode("utf-8")
        display_name = re.sub(
            r"[\r\n\\/]+",
            "_",
            str(row[2] or f"version_{export_version_id}"),
        ).strip("._ ") or f"version_{export_version_id}"
        if not display_name.lower().endswith(".json"):
            display_name = f"{display_name}.json"
        quoted_name = urllib.parse.quote(display_name)
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header(
            "Content-Disposition",
            f"attachment; filename=newsletter.json; filename*=UTF-8''{quoted_name}",
        )
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)
        return True

    version_id = parse_version_id(path)
    if version_id is not None:
        init_versions_db()
        con = versions_db()
        try:
            # PostgreSQL change: retrieve one version with a parameterized cursor.
            with con.cursor() as cur:
                cur.execute(
                    "SELECT id, issue_number, title, created_at, content, kind, COALESCE(hidden_from_users, FALSE) FROM versions WHERE id = %s",
                    (version_id,),
                )
                row = cur.fetchone()
        finally:
            con.close()
        if not row:
            handler.send_json({"error": "not found"}, 404)
            return True
        user = handler.current_user() if hasattr(handler, "current_user") else None
        if row[6] and not (user and user.get("is_admin")):
            handler.send_json({"error": "not found"}, 404)
            return True
        try:
            content = canonical_newsletter_payload(json.loads(row[4] or "{}"))
        except Exception:
            content = row[4] or "{}"
        handler.send_json({
            "id": row[0],
            "issue_number": row[1],
            "title": row[2],
            "created_at": serialize_db_datetime(row[3]),
            "content": content,
            "kind": row[5] or "json",
        })
        return True

    return False


# Handles handle versions post for the HTTP API layer.
def handle_versions_post(handler, path):
    convert_pdf_version_id = parse_version_id(path, "/pdf")
    if convert_pdf_version_id is not None:
        data = read_json_body_from_handler(handler)
        try:
            pdf_bytes = decode_pdf_base64(data.get("pdf_base64") or data.get("pdf"))
        except Exception:
            handler.send_json({"success": False, "error": "invalid pdf payload"}, 400)
            return True
        if not pdf_bytes:
            handler.send_json({"success": False, "error": "empty PDF payload"}, 400)
            return True
        filename = str(data.get("filename") or f"version_{convert_pdf_version_id}.pdf").strip()
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"
        init_versions_db()
        con = versions_db()
        try:
            with con.cursor() as cur:
                cur.execute("SELECT id, title, kind FROM versions WHERE id = %s", (convert_pdf_version_id,))
                row = cur.fetchone()
                if not row:
                    handler.send_json({"success": False, "error": "not found"}, 404)
                    return True
                cur.execute(
                    """
                    UPDATE versions
                    SET kind = 'pdf', pdf_data = %s, pdf_path = NULL, original_filename = %s
                    WHERE id = %s
                    """,
                    (psycopg2.Binary(pdf_bytes), filename, convert_pdf_version_id),
                )
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
        backup_versions_db()
        handler.send_json({
            "success": True,
            "id": convert_pdf_version_id,
            "kind": "pdf",
            "size": len(pdf_bytes),
        })
        return True

    if path == f"{API_BASE}/versions/import-pdf":
        pdf_bytes, filename, upload_error = read_multipart_upload(handler, field_name="pdf")
        if upload_error:
            handler.send_json({"success": False, "error": upload_error}, 400)
            return True
        trace(f"PDF import upload filename={filename or '-'} bytes={len(pdf_bytes or b'')}")
        if not pdf_bytes:
            handler.send_json({"success": False, "error": "empty PDF upload"}, 400)
            return True
        try:
            title = normalize_version_title(title_from_pdf_filename(filename))
            init_versions_db()
            con = versions_db()
            try:
                if version_title_exists(con, title):
                    handler.send_json({
                        "success": False,
                        "error": "version title already exists",
                        "code": "duplicate_version_title",
                        "title": title,
                    }, 409)
                    return True
                # PDF BYTEA change: insert PDF metadata first to obtain the ID
                # used by the binary update in the same PostgreSQL transaction.
                with con.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO versions (issue_number, title, content, kind, original_filename)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (None, title, "", "pdf", filename or "imported.pdf"),
                    )
                    new_id = cur.fetchone()[0]
                # PDF BYTEA change: store the uploaded bytes in the same database
                # transaction; no local file is created and pdf_path stays NULL.
                save_pdf_version_file(new_id, pdf_bytes, filename, connection=con)
                con.commit()
            finally:
                con.close()
            backup_versions_db()
            trace(f"PDF import saved PostgreSQL bytes version_id={new_id} title={title!r} bytes={len(pdf_bytes)}")
        except psycopg2.errors.UniqueViolation:
            handler.send_json({
                "success": False,
                "error": "version title already exists",
                "code": "duplicate_version_title",
                "title": title,
            }, 409)
            return True
        except Exception as exc:
            trace(f"PDF import failed: {exc}")
            handler.send_json({"success": False, "error": str(exc)}, 500)
            return True
        handler.send_json({
            "success": True,
            "id": new_id,
            "title": title,
            "kind": "pdf",
            "size": len(pdf_bytes),
        })
        return True

    if path == f"{API_BASE}/versions":
        init_versions_db()
        content = load_current_news_json_text()
        if not content.strip():
            handler.send_json({"error": "no content"}, 400)
            return True
        issue_number, title = version_title_from_news(content)
        title = normalize_version_title(requested_version_title_from_news(content) or title)
        con = versions_db()
        try:
            if version_title_exists(con, title):
                handler.send_json({
                    "error": "version title already exists",
                    "code": "duplicate_version_title",
                    "title": title,
                }, 409)
                return True
            # PostgreSQL change: save the current newsletter and return its new
            # identity while preserving the existing POST response.
            with con.cursor() as cur:
                cur.execute(
                    "INSERT INTO versions (issue_number, title, content) VALUES (%s, %s, %s) RETURNING id",
                    (issue_number, title, content),
                )
                new_id = cur.fetchone()[0]
            con.commit()
        except psycopg2.errors.UniqueViolation:
            con.rollback()
            handler.send_json({
                "error": "version title already exists",
                "code": "duplicate_version_title",
                "title": title,
            }, 409)
            return True
        finally:
            con.close()
        backup_versions_db()
        publish_current_store()
        handler.send_json({"id": new_id, "title": title, "published": True})
        return True

    restore_version_id = parse_version_id(path, "/restore")
    if restore_version_id is not None:
        init_versions_db()
        con = versions_db()
        try:
            # PostgreSQL change: load restore content through a safe parameterized query.
            with con.cursor() as cur:
                cur.execute("SELECT content, kind FROM versions WHERE id = %s", (restore_version_id,))
                row = cur.fetchone()
        finally:
            con.close()
        if not row:
            handler.send_json({"error": "not found"}, 404)
            return True
        if (row[1] or "json") == "pdf":
            handler.send_json({"error": "PDF versions open as files and cannot be restored for editing"}, 400)
            return True
        try:
            payload = canonical_newsletter_payload(json.loads(row[0] or "{}"))
        except Exception:
            handler.send_json({"error": "Stored version content is not valid JSON"}, 500)
            return True
        # news.json is the one editable workspace for every generated/manual
        # version. Saving through save_store also makes the write atomic and
        # guarantees the exact same schema used by normal generation.
        save_store(store_from_payload(payload), existing_payload={}, already_normalized=True)
        canonical_content = NEWS_JSON_FILE.read_text(encoding="utf-8")
        con = versions_db()
        try:
            with con.cursor() as cur:
                cur.execute(
                    "UPDATE versions SET content = %s WHERE id = %s",
                    (canonical_content, restore_version_id),
                )
            con.commit()
        finally:
            con.close()
        handler.send_json({"ok": True, "canonicalized": True})
        return True

    return False


# Handles handle versions put for the HTTP API layer.
def handle_versions_put(handler, path, data):
    version_id = parse_version_id(path)
    if version_id is None:
        return False
    title = normalize_version_title(data.get("title") or "")
    created_at = str(data.get("created_at") or "").strip()
    hidden_present = "hidden_from_users" in data
    hidden_from_users = bool(data.get("hidden_from_users")) if hidden_present else None
    save_current = bool(data.get("save_current") or data.get("update_content"))
    content = load_current_news_json_text() if save_current else ""
    issue_number = None
    if save_current:
        if not content.strip():
            handler.send_json({"error": "no content"}, 400)
            return True
        issue_number, derived_title = version_title_from_news(content)
        # Existing versions retain their human name; new names are resolved
        # after loading the current row below.
    parsed_created_at = None
    if created_at:
        try:
            date_text = created_at.replace("Z", "+00:00")
            parsed = datetime.datetime.fromisoformat(date_text)
            if isinstance(parsed, datetime.datetime):
                parsed_created_at = parsed.replace(tzinfo=None)
        except Exception:
            try:
                parsed_created_at = datetime.datetime.combine(
                    datetime.date.fromisoformat(created_at),
                    datetime.time.min,
                )
            except Exception:
                handler.send_json({"error": "invalid created_at"}, 400)
                return True
    if not title and not save_current and not parsed_created_at and not hidden_present:
        handler.send_json({"error": "title, created_at, hidden_from_users, or save_current is required"}, 400)
        return True
    init_versions_db()
    con = versions_db()
    try:
        # PostgreSQL change: keep PDF overwrite protection using a psycopg2 cursor.
        with con.cursor() as cur:
            cur.execute("SELECT kind, title FROM versions WHERE id = %s", (version_id,))
            existing = cur.fetchone()
        if save_current and existing and (existing[0] or "json") == "pdf":
            handler.send_json({"error": "PDF versions cannot be edited or overwritten"}, 400)
            return True
        if title and version_title_exists(con, title, exclude_id=version_id):
            handler.send_json({
                "error": "version title already exists",
                "code": "duplicate_version_title",
                "title": title,
            }, 409)
            return True
        # PostgreSQL change: update content or title with %s parameters while
        # retaining the same row-count behavior expected by the API.
        with con.cursor() as cur:
            if save_current:
                title = title or (str(existing[1] or "").strip() if existing else "") or derived_title
                cur.execute(
                    """
                    UPDATE versions
                    SET issue_number = %s, title = %s, content = %s
                    WHERE id = %s
                    """,
                    (issue_number, title, content, version_id),
                )
            else:
                updates = []
                values = []
                if title:
                    updates.append("title = %s")
                    values.append(title)
                if parsed_created_at:
                    updates.append("created_at = %s")
                    values.append(parsed_created_at)
                if hidden_present:
                    updates.append("hidden_from_users = %s")
                    values.append(hidden_from_users)
                cur.execute(
                    f"UPDATE versions SET {', '.join(updates)} WHERE id = %s",
                    (*values, version_id),
                )
            updated = cur.rowcount
        con.commit()
    except psycopg2.errors.UniqueViolation:
        con.rollback()
        handler.send_json({
            "error": "version title already exists",
            "code": "duplicate_version_title",
            "title": title,
        }, 409)
        return True
    finally:
        con.close()
    if not updated:
        handler.send_json({"error": "not found"}, 404)
        return True
    if save_current:
        backup_versions_db()
        # Updating an existing archived version is an edit, not a publish.
        # Keep news_published.json pointing at the last version created through
        # POST /api/versions so end users never jump to whichever old version
        # an admin happened to edit most recently.
    response = {
        "ok": True,
        "id": version_id,
        "title": title or (str(existing[1] or "").strip() if existing else ""),
        "updated_content": save_current,
        "published": False,
    }
    if hidden_present:
        response["hidden_from_users"] = hidden_from_users
    handler.send_json(response)
    return True


# Handles handle versions delete for the HTTP API layer.
def handle_versions_delete(handler, path):
    version_id = parse_version_id(path)
    if version_id is None:
        return False
    init_versions_db()
    con = versions_db()
    try:
        # PDF BYTEA change: deleting a version now removes its PostgreSQL row and
        # embedded bytes together. Legacy files are intentionally left untouched.
        with con.cursor() as cur:
            cur.execute("DELETE FROM versions WHERE id = %s", (version_id,))
            deleted = cur.rowcount
        con.commit()
    finally:
        con.close()
    if not deleted:
        handler.send_json({"error": "not found"}, 404)
        return True
    backup_versions_db()
    handler.send_json({"ok": True})
    return True

