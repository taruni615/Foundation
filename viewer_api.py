#!/usr/bin/env python3
"""HTTP API + static file server for textbook_viewer.html (MySQL qa_* tables).

Usage (from repo root)::

  python viewer_api.py
  # Open http://127.0.0.1:8765/Viewer/textbook_viewer.html

Requires: pip install pymysql
"""

from __future__ import annotations

import html as html_module
import json
import mimetypes
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from io import BytesIO
from urllib.parse import parse_qs, unquote, urlparse

try:
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError:
    print("Install pymysql: pip install pymysql", file=sys.stderr)
    raise

from topicwise_pipeline import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = int(os.environ.get("VIEWER_API_PORT", "8765"))
API_VERSION = "2.1"
API_CAPABILITIES = [
    "books",
    "chapters",
    "chapter",
    "chapter-export",
    "chapter-pdf",
    "topic-export",
]
CONTENT_LIMIT_DEFAULT = 40
CONTENT_LIMIT_MAX = 200
EXPORT_QA_MAX = int(os.environ.get("EXPORT_QA_MAX", "50000"))
PAGE_RANGE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def connect_mysql():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
    )


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def file_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    data: bytes,
    content_type: str,
    filename: str,
    *,
    inline: bool = False,
) -> None:
    disposition = "inline" if inline else "attachment"
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header(
        "Content-Disposition",
        f'{disposition}; filename="{filename}"',
    )
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(data)


def safe_chapter_basename(chapter: Dict[str, Any], *, suffix: str = "") -> str:
    number = int(chapter.get("chapter_number") or 0)
    name = str(chapter.get("chapter_name") or "chapter").strip()
    safe = re.sub(r"[^\w\s-]+", "", name, flags=re.UNICODE).strip()
    safe = re.sub(r"\s+", "_", safe)[:80] or "chapter"
    base = f"Chapter_{number:02d}_{safe}"
    if suffix:
        base += f"_{suffix}"
    return base


def filter_export_payload(payload: Dict[str, Any], scope: str) -> Dict[str, Any]:
    """Limit export to summary (and optionally key points) only."""
    scope = str(scope or "full").strip().lower()
    if scope in ("full", "all", ""):
        return payload

    chapter = dict(payload.get("chapter") or {})
    filtered = {
        "chapter": chapter,
        "theory_sections": [],
        "content_rows": [],
        "content_total": 0,
        "exported_all_content": True,
        "export_scope": scope,
    }

    if scope == "summary":
        filtered["chapter"] = {
            **chapter,
            "key_points": "",
        }
        return filtered

    if scope in ("summary_keypoints", "summary+keypoints", "summary-keypoints"):
        filtered["export_scope"] = "summary_keypoints"
        return filtered

    raise ValueError(f"Unsupported export scope: {scope}")


def export_summary_html(summary: Any) -> str:
    """Render hierarchical ## / ### summary markdown for PDF/HTML export."""
    raw = str(summary or "").strip()
    if not raw:
        return ""

    if re.search(r"<math[\s>]", raw, re.IGNORECASE) or re.search(
        r"<(?:p|div|table|ul|ol|img)\b", raw, re.IGNORECASE
    ):
        return export_rich_block(raw)

    parts: List[str] = []
    chunks = re.split(r"\n(?=#{2,3}\s)", raw.replace("\r", ""))
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        heading_match = re.match(r"^(#{2,3})\s+(.*)$", chunk)
        if heading_match:
            level = len(heading_match.group(1))
            heading = heading_match.group(2).strip()
            body = chunk[heading_match.end():].strip()
            tag = "h3" if level == 2 else "h4"
            parts.append(f"<{tag}>{html_module.escape(heading)}</{tag}>")
            if body:
                parts.append(export_rich_block(body))
            continue
        parts.append(export_rich_block(chunk))

    return "".join(parts) if parts else export_rich_block(raw)


def export_rich_block(text: Any) -> str:
    """Embed DB HTML/MathML or escape plain text for export documents."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if (
        "<math" in lowered
        or "<table" in lowered
        or "<img" in lowered
        or "<p" in lowered
        or "<div" in lowered
        or "<ul" in lowered
        or "<ol" in lowered
    ):
        return f'<div class="rich">{raw}</div>'
    escaped = html_module.escape(raw).replace("\n", "<br>\n")
    return f'<div class="rich"><p>{escaped}</p></div>'


def split_key_points_export(text: Any) -> List[str]:
    if not text or not str(text).strip():
        return []
    return [line.strip() for line in str(text).splitlines() if line.strip()]


def simplify_mathml_for_pdf(html: str) -> str:
    """Replace MathML with readable italic text for PDF engines that lack MathJax."""

    def _math_repl(match: re.Match[str]) -> str:
        inner = match.group(0)
        text = re.sub(r"<[^>]+>", " ", inner)
        text = html_module.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            text = "[math]"
        return f'<span class="math-fallback"><i>{html_module.escape(text)}</i></span>'

    out = re.sub(r"<math[\s>][\s\S]*?</math>", _math_repl, html, flags=re.IGNORECASE)
    out = re.sub(r"<script[\s>][\s\S]*?</script>", "", out, flags=re.IGNORECASE)
    return out


def html_to_pdf_bytes(html: str) -> bytes:
    """Convert export HTML to PDF (xhtml2pdf, with fpdf2 text fallback)."""
    html = simplify_mathml_for_pdf(html)
    try:
        from xhtml2pdf import pisa

        buffer = BytesIO()
        result = pisa.CreatePDF(html, dest=buffer, encoding="utf-8")
        if result.err:
            raise RuntimeError(f"PDF layout errors: {result.err}")
        data = buffer.getvalue()
        if data:
            return data
    except Exception as exc:
        last_err: Exception = exc
    else:
        last_err = RuntimeError("xhtml2pdf produced empty PDF")

    raise RuntimeError(
        f"Could not build PDF ({last_err}). Try format=html and use Print / Save as PDF."
    ) from last_err


def build_chapter_pdf_bytes(payload: Dict[str, Any]) -> bytes:
    html = build_chapter_export_html(payload, for_pdf=True)
    try:
        return html_to_pdf_bytes(html)
    except RuntimeError:
        return build_chapter_pdf_fpdf(payload)


def _pdf_safe_text(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"<math[\s>][\s\S]*?</math>", " [math] ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.encode("latin-1", errors="replace").decode("latin-1")


def build_chapter_pdf_fpdf(payload: Dict[str, Any]) -> bytes:
    """Plain-text PDF fallback when HTML-to-PDF is unavailable."""
    from fpdf import FPDF

    chapter = payload.get("chapter") or {}
    theory = payload.get("theory_sections") or []
    rows = payload.get("content_rows") or []

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", style="B", size=14)
    title = _pdf_safe_text(
        f"{chapter.get('chapter_number', '')}. {chapter.get('chapter_name', '')}"
    )
    pdf.multi_cell(0, 8, title)
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(
        0,
        6,
        _pdf_safe_text(
            f"Book: {chapter.get('book_slug', '')}  |  Pages: {chapter.get('page_range', '')}"
        ),
    )
    pdf.ln(4)

    def section_heading(label: str) -> None:
        pdf.set_font("Helvetica", style="B", size=12)
        pdf.multi_cell(0, 7, _pdf_safe_text(label))
        pdf.set_font("Helvetica", size=10)

    def body_block(text: Any) -> None:
        block = _pdf_safe_text(str(text or ""))
        if block:
            pdf.multi_cell(0, 5, block)
            pdf.ln(2)

    summary = chapter.get("summary")
    if summary and str(summary).strip():
        section_heading("Summary")
        body_block(summary)

    kps = split_key_points_export(chapter.get("key_points"))
    if kps:
        section_heading("Key points")
        for idx, kp in enumerate(kps, start=1):
            pdf.set_font("Helvetica", style="B", size=10)
            pdf.multi_cell(0, 5, _pdf_safe_text(f"Key point {idx}"))
            pdf.set_font("Helvetica", size=10)
            body_block(kp)

    if theory:
        section_heading("Theory")
        for idx, sec in enumerate(theory, start=1):
            pdf.set_font("Helvetica", style="B", size=10)
            pdf.multi_cell(
                0,
                5,
                _pdf_safe_text(sec.get("topic_name") or f"Section {idx}"),
            )
            pdf.set_font("Helvetica", size=10)
            body_block(sec.get("topic_explanation"))

    if rows:
        section_heading(f"Questions & answers ({len(rows)})")
        for idx, row in enumerate(rows, start=1):
            pdf.set_font("Helvetica", style="B", size=10)
            pdf.multi_cell(
                0,
                5,
                _pdf_safe_text(
                    f"#{idx} {row.get('question_type', '')} (id {row.get('id', '')})"
                ),
            )
            pdf.set_font("Helvetica", size=10)
            pdf.multi_cell(0, 5, _pdf_safe_text("Question:"))
            body_block(row.get("question"))
            if row.get("answer"):
                pdf.multi_cell(0, 5, _pdf_safe_text("Answer:"))
                body_block(row.get("answer"))
            pdf.ln(1)

    out = pdf.output()
    return out if isinstance(out, (bytes, bytearray)) else out.encode("latin-1")


def build_chapter_export_html(payload: Dict[str, Any], *, for_pdf: bool = False) -> str:
    chapter = payload.get("chapter") or {}
    theory = payload.get("theory_sections") or []
    rows = payload.get("content_rows") or []
    title = f"{chapter.get('chapter_number', '')}. {chapter.get('chapter_name', '')}".strip()
    book = chapter.get("book_slug") or ""
    page_range = chapter.get("page_range") or ""

    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{html_module.escape(title)}</title>",
        "<style>",
        "body{font-family:Georgia,serif;max-width:900px;margin:24px auto;line-height:1.5;color:#111}",
        "h1,h2,h3{color:#0f172a} .muted{color:#555;font-size:14px}",
        ".section{border:1px solid #ddd;border-radius:8px;padding:12px;margin:14px 0}",
        ".label{font-size:11px;text-transform:uppercase;color:#666;margin-bottom:6px}",
        ".key-point{border-left:3px solid #2563eb;padding:8px 12px;margin:8px 0;background:#f8fafc}",
        ".rich img{max-width:100%} table{border-collapse:collapse;width:100%}",
        "th,td{border:1px solid #ccc;padding:6px} .math-fallback{font-style:italic}",
        "@media print{body{margin:12px}}",
        "</style>",
    ]
    if not for_pdf:
        parts.extend([
            "<script>",
            "window.MathJax={tex:{inlineMath:[['$','$'],['\\\\(','\\\\)']],displayMath:[['$$','$$'],['\\\\[','\\\\]']]},",
            "options:{skipHtmlTags:['script','noscript','style','textarea','pre','code','img']}};",
            "</script>",
            '<script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>',
        ])
    parts.extend([
        "</head><body>",
        f"<h1>{html_module.escape(title)}</h1>",
        f'<p class="muted">Book: {html_module.escape(str(book))} · Pages: {html_module.escape(str(page_range))} · '
        f"Exported from Foundation Textbooks DB viewer</p>",
    ])

    summary = chapter.get("summary")
    if summary and str(summary).strip():
        parts.append("<h2>Summary</h2><div class='section'>")
        parts.append(export_summary_html(summary))
        parts.append("</div>")

    kps = split_key_points_export(chapter.get("key_points"))
    if kps:
        parts.append("<h2>Key points</h2>")
        for idx, kp in enumerate(kps, start=1):
            parts.append(f"<div class='section'><h3>Key point {idx}</h3>")
            parts.append(f"<div class='key-point'>{export_rich_block(kp)}</div></div>")

    if theory:
        parts.append("<h2>Theory</h2>")
        for idx, sec in enumerate(theory, start=1):
            sec_title = sec.get("topic_name") or f"Section {idx}"
            parts.append(f"<div class='section'><h3>{html_module.escape(str(sec_title))}</h3>")
            parts.append(export_rich_block(sec.get("topic_explanation")))
            parts.append("</div>")

    if rows:
        parts.append(f"<h2>Questions &amp; answers ({len(rows)})</h2>")
        for idx, row in enumerate(rows, start=1):
            qtype = row.get("question_type") or ""
            parts.append("<div class='section'>")
            parts.append(
                f"<h3>#{idx} {html_module.escape(str(qtype))} "
                f"<span class='muted'>(id {row.get('id', '')})</span></h3>"
            )
            parts.append("<div class='label'>Question</div>")
            parts.append(export_rich_block(row.get("question")))
            if row.get("answer"):
                parts.append("<div class='label'>Answer</div>")
                parts.append(export_rich_block(row.get("answer")))
            parts.append("</div>")

    parts.append("</body></html>")
    return "".join(parts)


def topic_to_export_payload(topic: Dict[str, Any], book_slug: str) -> Dict[str, Any]:
    """Map a *_final.json topic object to the chapter export shape."""
    key_lines: List[str] = []
    for kp in topic.get("key_points") or []:
        if isinstance(kp, dict):
            text = str(kp.get("text") or "").strip()
        else:
            text = str(kp).strip()
        if text:
            key_lines.append(text)

    theory_sections: List[Dict[str, Any]] = []
    for sec in topic.get("theory_sections") or []:
        if not isinstance(sec, dict):
            continue
        theory_sections.append({
            "topic_name": sec.get("topics") or sec.get("title") or "Section",
            "topic_explanation": sec.get("markdown") or sec.get("topic_explanation") or "",
            "section_kind": sec.get("section_kind") or "",
        })

    content_rows: List[Dict[str, Any]] = []
    row_id = 0
    for bucket in (
        "illustrations",
        "check_your_knowledge_items",
        "textbook_exercises",
        "exercises",
    ):
        for ex in topic.get(bucket) or []:
            if not isinstance(ex, dict):
                continue
            row_id += 1
            content_rows.append({
                "id": ex.get("id", row_id),
                "question": (
                    ex.get("problem")
                    or ex.get("problem_markdown")
                    or ex.get("question")
                    or ""
                ),
                "answer": (
                    ex.get("solution")
                    or ex.get("solution_markdown")
                    or ex.get("answer")
                    or ""
                ),
                "question_type": ex.get("question_type") or ex.get("type") or bucket,
            })

    return {
        "chapter": {
            "chapter_number": topic.get("topic_number"),
            "chapter_name": topic.get("chapter_name") or topic.get("topic_name"),
            "book_slug": book_slug,
            "page_range": topic.get("page_range"),
            "summary": topic.get("summary"),
            "key_points": "\n".join(key_lines),
            "concept_map": topic.get("concept_map"),
        },
        "theory_sections": theory_sections,
        "content_rows": content_rows,
    }


def parse_page_range(page_range: str) -> Tuple[int, int]:
    """Inclusive 1-based page numbers from strings like ``1-76``."""
    text = str(page_range or "").strip()
    match = PAGE_RANGE_RE.fullmatch(text)
    if not match:
        raise ValueError(f"Invalid page_range: {page_range!r}")
    start, end = int(match.group(1)), int(match.group(2))
    if start < 1 or end < start:
        raise ValueError(f"Invalid page_range: {page_range!r}")
    return start, end


def resolve_repo_file(rel_path: str) -> Path:
    rel = unquote(str(rel_path or "")).lstrip("/").replace("\\", "/")
    if ".." in rel.split("/"):
        raise ValueError("Invalid path")
    file_path = (REPO_ROOT / rel).resolve()
    root = REPO_ROOT.resolve()
    if not str(file_path).startswith(str(root)):
        raise ValueError("Path outside repository")
    return file_path


def load_final_json_topics(json_rel: str) -> Tuple[Path, Dict[str, Any], List[Dict[str, Any]]]:
    json_path = resolve_repo_file(json_rel)
    if not json_path.is_file() or not json_path.name.endswith("_final.json"):
        raise FileNotFoundError(f"Not a *_final.json file: {json_rel}")
    with open(json_path, "r", encoding="utf-8") as handle:
        document = json.load(handle)
    topics = document.get("topics") or []
    if not isinstance(topics, list):
        raise ValueError("topics[] missing in final JSON")
    return json_path, document, topics


def extract_chapter_pdf_bytes(pdf_path: Path, page_range: str) -> bytes:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise RuntimeError("Install pypdf: pip install pypdf") from exc

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    start_page, end_page = parse_page_range(page_range)
    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    writer = PdfWriter()
    for page_num in range(start_page, end_page + 1):
        index = page_num - 1
        if 0 <= index < total:
            writer.add_page(reader.pages[index])
    if not writer.pages:
        raise ValueError(f"No pages in range {page_range} (PDF has {total} pages)")

    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def parse_int(value: Optional[str], default: int, *, minimum: int = 0, maximum: Optional[int] = None) -> int:
    try:
        n = int(value) if value is not None else default
    except (TypeError, ValueError):
        n = default
    n = max(minimum, n)
    if maximum is not None:
        n = min(n, maximum)
    return n


class ViewerAPIHandler(BaseHTTPRequestHandler):
    server_version = "ViewerAPI/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path.startswith("/api/"):
            self._handle_api(path, qs)
            return
        self._serve_static(path)

    def _handle_api(self, path: str, qs: Dict[str, List[str]]) -> None:
        try:
            if path == "/api/capabilities":
                json_response(self, 200, {
                    "version": API_VERSION,
                    "capabilities": API_CAPABILITIES,
                })
                return
            if path == "/api/books":
                json_response(self, 200, {"books": list_books()})
                return
            if path == "/api/chapters":
                book_slug = (qs.get("book_slug") or [""])[0].strip()
                if not book_slug:
                    json_response(self, 400, {"error": "book_slug is required"})
                    return
                json_response(self, 200, {"chapters": list_chapters(book_slug)})
                return
            m = re.fullmatch(r"/api/chapter/(\d+)", path)
            if m:
                chapter_id = int(m.group(1))
                offset = parse_int((qs.get("offset") or ["0"])[0], 0, minimum=0)
                limit = parse_int(
                    (qs.get("limit") or [str(CONTENT_LIMIT_DEFAULT)])[0],
                    CONTENT_LIMIT_DEFAULT,
                    minimum=1,
                    maximum=CONTENT_LIMIT_MAX,
                )
                json_response(self, 200, get_chapter(chapter_id, offset=offset, limit=limit))
                return
            if path == "/api/chapter-pdf":
                self._handle_chapter_pdf(qs)
                return
            if path == "/api/chapter-export":
                self._handle_chapter_export(qs)
                return
            if path == "/api/topic-export":
                self._handle_topic_export(qs)
                return
            json_response(
                self,
                404,
                {
                    "error": (
                        f"API route not found: {path}. "
                        "Stop and restart: python viewer_api.py"
                    ),
                },
            )
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def _handle_chapter_pdf(self, qs: Dict[str, List[str]]) -> None:
        try:
            json_rel = (qs.get("json") or [""])[0].strip()
            topic_raw = (qs.get("topic") or qs.get("topic_number") or [""])[0].strip()
            if not json_rel or not topic_raw:
                json_response(self, 400, {"error": "json and topic are required"})
                return

            _json_path, document, topics = load_final_json_topics(json_rel)
            topic_number = int(topic_raw)
            topic = next(
                (t for t in topics if int(t.get("topic_number") or 0) == topic_number),
                None,
            )
            if not topic:
                json_response(self, 404, {"error": f"topic {topic_number} not found"})
                return

            page_range = str(topic.get("page_range") or "").strip()
            if not page_range:
                json_response(self, 400, {"error": "topic has no page_range"})
                return

            metadata = document.get("metadata") or {}
            pdf_rel = str(metadata.get("source_pdf") or "").strip().replace("\\", "/")
            if not pdf_rel:
                json_response(self, 400, {"error": "metadata.source_pdf missing"})
                return

            pdf_path = resolve_repo_file(pdf_rel)
            pdf_bytes = extract_chapter_pdf_bytes(pdf_path, page_range)

            chapter_name = (
                topic.get("chapter_name")
                or topic.get("topic_name")
                or f"topic_{topic_number}"
            )
            safe_name = re.sub(r"[^\w\s-]+", "", chapter_name, flags=re.UNICODE).strip()
            safe_name = re.sub(r"\s+", "_", safe_name)[:80] or f"topic_{topic_number}"
            filename = f"Topic_{topic_number:02d}_{safe_name}_pp_{page_range.replace('-', '_')}.pdf"

            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(pdf_bytes)))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(pdf_bytes)
        except FileNotFoundError as exc:
            json_response(self, 404, {"error": str(exc)})
        except (ValueError, RuntimeError) as exc:
            json_response(self, 400, {"error": str(exc)})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def _handle_chapter_export(self, qs: Dict[str, List[str]]) -> None:
        try:
            chapter_raw = (qs.get("chapter_id") or [""])[0].strip()
            if not chapter_raw:
                json_response(self, 400, {"error": "chapter_id is required"})
                return
            chapter_id = int(chapter_raw)
            fmt = (qs.get("format") or ["html"])[0].strip().lower()
            scope = (qs.get("scope") or ["full"])[0].strip().lower()
            inline = (qs.get("inline") or ["0"])[0].strip().lower() in ("1", "true", "yes")

            payload = get_chapter_full(chapter_id)
            if payload.get("error"):
                json_response(self, 400, payload)
                return

            try:
                payload = filter_export_payload(payload, scope)
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
                return

            chapter = payload.get("chapter") or {}
            summary_text = str(chapter.get("summary") or "").strip()
            if scope == "summary" and not summary_text:
                json_response(self, 400, {"error": "This chapter has no summary to export"})
                return

            suffix = "summary" if scope == "summary" else ""
            basename = safe_chapter_basename(chapter, suffix=suffix)

            if fmt == "json":
                body = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
                file_response(
                    self,
                    200,
                    body,
                    "application/json; charset=utf-8",
                    f"{basename}.json",
                    inline=inline,
                )
                return

            if fmt == "pdf":
                pdf_bytes = build_chapter_pdf_bytes(payload)
                file_response(
                    self,
                    200,
                    pdf_bytes,
                    "application/pdf",
                    f"{basename}.pdf",
                    inline=inline,
                )
                return

            if fmt != "html":
                json_response(self, 400, {"error": f"Unsupported format: {fmt}"})
                return

            html_doc = build_chapter_export_html(payload).encode("utf-8")
            file_response(
                self,
                200,
                html_doc,
                "text/html; charset=utf-8",
                f"{basename}.html",
                inline=inline,
            )
        except ValueError as exc:
            json_response(self, 400, {"error": str(exc)})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def _handle_topic_export(self, qs: Dict[str, List[str]]) -> None:
        try:
            json_rel = (qs.get("json") or [""])[0].strip()
            topic_raw = (qs.get("topic") or qs.get("topic_number") or [""])[0].strip()
            if not json_rel or not topic_raw:
                json_response(self, 400, {"error": "json and topic are required"})
                return

            _json_path, document, topics = load_final_json_topics(json_rel)
            topic_number = int(topic_raw)
            topic = next(
                (t for t in topics if int(t.get("topic_number") or 0) == topic_number),
                None,
            )
            if not topic:
                json_response(self, 404, {"error": f"topic {topic_number} not found"})
                return

            metadata = document.get("metadata") or {}
            book_slug = str(metadata.get("name") or "book")
            payload = topic_to_export_payload(topic, book_slug)
            payload["content_total"] = len(payload.get("content_rows") or [])
            payload["exported_all_content"] = True

            fmt = (qs.get("format") or ["pdf"])[0].strip().lower()
            scope = (qs.get("scope") or ["full"])[0].strip().lower()
            inline = (qs.get("inline") or ["0"])[0].strip().lower() in ("1", "true", "yes")

            try:
                payload = filter_export_payload(payload, scope)
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
                return

            chapter = payload.get("chapter") or {}
            summary_text = str(chapter.get("summary") or "").strip()
            if scope == "summary" and not summary_text:
                json_response(self, 400, {"error": "This topic has no summary to export"})
                return

            suffix = "summary" if scope == "summary" else ""
            basename = safe_chapter_basename(chapter, suffix=suffix)

            if fmt == "json":
                body = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
                file_response(
                    self,
                    200,
                    body,
                    "application/json; charset=utf-8",
                    f"{basename}.json",
                    inline=inline,
                )
                return
            if fmt == "html":
                html_doc = build_chapter_export_html(payload).encode("utf-8")
                file_response(
                    self,
                    200,
                    html_doc,
                    "text/html; charset=utf-8",
                    f"{basename}.html",
                    inline=inline,
                )
                return
            if fmt == "pdf":
                pdf_bytes = build_chapter_pdf_bytes(payload)
                file_response(
                    self,
                    200,
                    pdf_bytes,
                    "application/pdf",
                    f"{basename}.pdf",
                    inline=inline,
                )
                return
            json_response(self, 400, {"error": f"Unsupported format: {fmt}"})
        except FileNotFoundError as exc:
            json_response(self, 404, {"error": str(exc)})
        except (ValueError, RuntimeError) as exc:
            json_response(self, 400, {"error": str(exc)})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def _serve_static(self, path: str) -> None:
        if path == "/":
            path = "/Viewer/textbook_viewer.html"
        rel = path.lstrip("/").replace("\\", "/")
        if ".." in rel.split("/"):
            self.send_error(403)
            return
        file_path = REPO_ROOT / rel
        if not file_path.is_file():
            self.send_error(404)
            return
        data = file_path.read_bytes()
        mime, _ = mimetypes.guess_type(str(file_path))
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def list_books() -> List[Dict[str, Any]]:
    with connect_mysql() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT book_slug,
                       COUNT(*) AS chapter_count,
                       MAX(updated_at) AS updated_at
                FROM qa_chapter
                GROUP BY book_slug
                ORDER BY book_slug
                """
            )
            return list(cur.fetchall())


def list_chapters(book_slug: str) -> List[Dict[str, Any]]:
    with connect_mysql() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.chapter_id,
                       c.chapter_number,
                       c.chapter_name,
                       c.page_range,
                       (SELECT COUNT(*) FROM qa_theory_chapter t
                        WHERE t.chapter_id = c.chapter_id) AS theory_count,
                       (SELECT COUNT(*) FROM qa_content_row r
                        WHERE r.chapter_id = c.chapter_id) AS row_count
                FROM qa_chapter c
                WHERE c.book_slug = %s
                ORDER BY c.chapter_number
                """,
                (book_slug,),
            )
            return list(cur.fetchall())


def get_chapter(chapter_id: int, *, offset: int, limit: int) -> Dict[str, Any]:
    with connect_mysql() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT chapter_id, book_slug, chapter_number, chapter_name,
                       page_range, summary, key_points
                FROM qa_chapter
                WHERE chapter_id = %s
                """,
                (chapter_id,),
            )
            chapter = cur.fetchone()
            if not chapter:
                return {"error": "chapter not found"}

            cur.execute(
                """
                SELECT id, topic_name, topic_explanation, section_order
                FROM qa_theory_chapter
                WHERE chapter_id = %s
                ORDER BY section_order
                """,
                (chapter_id,),
            )
            theory_sections = list(cur.fetchall())

            cur.execute(
                "SELECT COUNT(*) AS n FROM qa_content_row WHERE chapter_id = %s",
                (chapter_id,),
            )
            content_total = int(cur.fetchone()["n"])

            cur.execute(
                """
                SELECT id, question, answer, question_type
                FROM qa_content_row
                WHERE chapter_id = %s
                ORDER BY id
                LIMIT %s OFFSET %s
                """,
                (chapter_id, limit, offset),
            )
            content_rows = list(cur.fetchall())

    return {
        "chapter": chapter,
        "theory_sections": theory_sections,
        "content_rows": content_rows,
        "content_total": content_total,
        "content_offset": offset,
        "content_limit": limit,
    }


def get_chapter_full(chapter_id: int) -> Dict[str, Any]:
    """Full chapter payload for export (all Q&amp;A rows, not paginated)."""
    with connect_mysql() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT chapter_id, book_slug, chapter_number, chapter_name,
                       page_range, summary, key_points
                FROM qa_chapter
                WHERE chapter_id = %s
                """,
                (chapter_id,),
            )
            chapter = cur.fetchone()
            if not chapter:
                return {"error": "chapter not found"}

            cur.execute(
                """
                SELECT id, topic_name, topic_explanation, section_order
                FROM qa_theory_chapter
                WHERE chapter_id = %s
                ORDER BY section_order
                """,
                (chapter_id,),
            )
            theory_sections = list(cur.fetchall())

            cur.execute(
                "SELECT COUNT(*) AS n FROM qa_content_row WHERE chapter_id = %s",
                (chapter_id,),
            )
            content_total = int(cur.fetchone()["n"])

            if content_total > EXPORT_QA_MAX:
                return {
                    "error": (
                        f"Chapter has {content_total} Q&A rows; export limit is {EXPORT_QA_MAX}. "
                        "Set EXPORT_QA_MAX env var to raise the limit."
                    ),
                }

            cur.execute(
                """
                SELECT id, question, answer, question_type
                FROM qa_content_row
                WHERE chapter_id = %s
                ORDER BY id
                """,
                (chapter_id,),
            )
            content_rows = list(cur.fetchall())

    return {
        "chapter": chapter,
        "theory_sections": theory_sections,
        "content_rows": content_rows,
        "content_total": content_total,
        "exported_all_content": True,
    }


def main() -> None:
    host = os.environ.get("VIEWER_API_HOST", "127.0.0.1")
    port = DEFAULT_PORT
    httpd = ThreadingHTTPServer((host, port), ViewerAPIHandler)
    print(f"Serving {REPO_ROOT}")
    print(f"Viewer (DB): http://{host}:{port}/Viewer/textbook_viewer.html")
    print(f"Viewer (JSON): http://{host}:{port}/Viewer/output_json_viewer.html")
    print(f"API:    http://{host}:{port}/api/books")
    print(f"Export: http://{host}:{port}/api/chapter-export?chapter_id=ID&format=pdf")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
