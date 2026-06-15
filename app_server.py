#!/usr/bin/env python3
"""Web app backend for the textbook extraction pipeline.

Adds the *write/action* endpoints the read-only ``viewer_api.py`` never had:
upload a PDF, run extraction (with live progress), view + edit the extracted
content, preview it grouped by category, and insert it into MySQL.

Run from the repo root::

    python app_server.py
    # then open http://127.0.0.1:8000/

No third-party web framework -- just the standard library, mirroring the style
of ``viewer_api.py``.  Heavy lifting (Mathpix, Ollama, MySQL) is delegated to
the existing pipeline scripts, so this server works with the books already in
``outputs/`` even when those external services are offline.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parent
WEBAPP_DIR = REPO_ROOT / "webapp"
OUTPUTS_DIR = REPO_ROOT / "outputs"
INPUT_PDF_DIR = REPO_ROOT / "Input_PDFs"
DEFAULT_PORT = int(os.environ.get("APP_PORT", "8000"))

# Pipeline helpers (imported lazily-safe: viewer_api.py imports the same way).
from final_to_qa_table import build_qa_table_export  # noqa: E402
from topicwise_pipeline import (  # noqa: E402
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
)

# ---------------------------------------------------------------------------
# Attribute vocabulary (left-hand selectors)
# ---------------------------------------------------------------------------
# The pipeline only ever inferred these from the PDF filename.  We expose them
# as explicit, user-friendly choices and stitch them back into the data so a
# non-technical user never has to touch a filename.
BOARDS = ["Foundation", "CBSE", "ICSE", "State Board", "Other"]
SUBJECTS = ["Physics", "Chemistry", "Biology", "Mathematics", "Science", "Other"]
CLASSES = ["6", "7", "8", "9", "10", "11", "12"]

# ---------------------------------------------------------------------------
# Extraction job registry
# ---------------------------------------------------------------------------
JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]+", "", str(text or ""), flags=re.UNICODE).strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def book_dir(book: str) -> Path:
    return OUTPUTS_DIR / book


def final_json_path(book: str) -> Path:
    return book_dir(book) / f"{book}_final.json"


def qa_json_path(book: str) -> Path:
    return book_dir(book) / f"{book}_qa_table.json"


def list_existing_books() -> List[Dict[str, Any]]:
    books: List[Dict[str, Any]] = []
    if OUTPUTS_DIR.is_dir():
        for child in sorted(OUTPUTS_DIR.iterdir()):
            if not child.is_dir():
                continue
            final_file = child / f"{child.name}_final.json"
            if final_file.is_file():
                topic_count = 0
                try:
                    with open(final_file, "r", encoding="utf-8") as fh:
                        doc = json.load(fh)
                    topic_count = len(doc.get("topics") or [])
                except Exception:
                    pass
                books.append({
                    "book": child.name,
                    "topic_count": topic_count,
                    "has_qa_table": qa_json_path(child.name).is_file(),
                    "guess": guess_attributes_from_name(child.name),
                })
    return books


def list_input_pdfs() -> List[str]:
    if not INPUT_PDF_DIR.is_dir():
        return []
    return sorted(p.name for p in INPUT_PDF_DIR.iterdir() if p.suffix.lower() == ".pdf")


def guess_attributes_from_name(name: str) -> Dict[str, str]:
    low = name.lower()
    subject = ""
    for s in SUBJECTS:
        if s.lower() in low:
            subject = s
            break
    cls = ""
    m = re.search(r"class\s*(\d{1,2})", low) or re.search(r"(\d{1,2})\s*th", low)
    if m:
        cls = m.group(1)
    board = "Foundation" if "foundation" in low else ""
    return {"board": board, "subject": subject, "class": cls}


# ---------------------------------------------------------------------------
# HTTP plumbing
# ---------------------------------------------------------------------------
def _set_cors(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename")


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    _set_cors(handler)
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------------------
# Extraction worker
# ---------------------------------------------------------------------------
CACHED_STEPS = [
    "Reading the PDF",
    "Converting pages to text",
    "Splitting into topics",
    "Organising questions & answers",
    "Finalising extracted content",
]


def run_extraction_job(job_id: str, pdf_filename: str, book: str, force_real: bool) -> None:
    def update(**kw: Any) -> None:
        with JOBS_LOCK:
            JOBS[job_id].update(kw)

    final_file = final_json_path(book)

    # Fast path: a finished extraction already exists -> reuse it, but still
    # animate the steps so the user gets feedback (and so the UX is identical
    # to a fresh run).
    if final_file.is_file() and not force_real:
        for i, label in enumerate(CACHED_STEPS):
            update(step=i, step_label=label, message=label, progress=int((i + 1) / len(CACHED_STEPS) * 100))
            time.sleep(0.5)
        update(state="done", book=book, ready=True, progress=100,
                message="Extraction complete (loaded existing result).")
        return

    # Real path: drive the actual pipeline. Needs Mathpix + Ollama configured.
    pdf_path = INPUT_PDF_DIR / pdf_filename
    if not pdf_path.is_file():
        update(state="error", error=f"PDF not found: {pdf_filename}")
        return

    update(step=0, step_label=CACHED_STEPS[0], message="Starting extraction pipeline…", progress=2)
    cmd = [sys.executable, str(REPO_ROOT / "textbook_extract_pipeline.py"), str(pdf_path)]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        update(state="error", error=f"Could not start pipeline: {exc}")
        return

    tail: List[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        tail.append(line)
        tail[:] = tail[-12:]
        # Surface the pipeline's own "Step N/6" markers as progress.
        m = re.search(r"Step\s+(\d+)\s*/\s*(\d+)", line)
        if m:
            cur, total = int(m.group(1)), int(m.group(2))
            update(progress=min(99, int(cur / total * 100)))
        update(message=line, log="\n".join(tail))
    proc.wait()

    if proc.returncode == 0 and final_file.is_file():
        update(state="done", book=book, ready=True, progress=100,
                message="Extraction complete.")
    else:
        update(state="error", progress=100,
               error="Extraction failed. This usually means Mathpix or Ollama "
                     "is not configured in this environment.",
               log="\n".join(tail))


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------
class AppHandler(BaseHTTPRequestHandler):
    server_version = "PipelineApp/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        _set_cors(self)
        self.end_headers()

    # -- GET ---------------------------------------------------------------
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        qs = parse_qs(parsed.query)
        try:
            if path == "/api/attributes":
                self.api_attributes()
            elif path == "/api/extract/status":
                self.api_extract_status(qs)
            elif path == "/api/extraction":
                self.api_get_extraction(qs)
            elif path == "/api/pdf":
                self.api_get_pdf(qs)
            elif path == "/api/preview":
                self.api_preview(qs)
            elif path.startswith("/api/"):
                json_response(self, 404, {"error": f"Unknown API route: {path}"})
            else:
                self.serve_static(path)
        except BrokenPipeError:
            pass
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    # -- POST --------------------------------------------------------------
    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == "/api/upload":
                self.api_upload()
            elif path == "/api/extract":
                self.api_extract()
            elif path == "/api/save-extraction":
                self.api_save_extraction()
            elif path == "/api/save-preview":
                self.api_save_preview()
            elif path == "/api/insert":
                self.api_insert()
            else:
                json_response(self, 404, {"error": f"Unknown API route: {path}"})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    # -- API: attributes ---------------------------------------------------
    def api_attributes(self) -> None:
        pdfs = []
        for name in list_input_pdfs():
            stem = name[:-4]
            pdfs.append({
                "filename": name,
                "book": stem,
                "guess": guess_attributes_from_name(stem),
                "extracted": final_json_path(stem).is_file(),
            })
        json_response(self, 200, {
            "boards": BOARDS,
            "subjects": SUBJECTS,
            "classes": CLASSES,
            "input_pdfs": pdfs,
            "existing_books": list_existing_books(),
        })

    # -- API: upload -------------------------------------------------------
    def api_upload(self) -> None:
        filename = self.headers.get("X-Filename") or ""
        filename = os.path.basename(unquote(filename)).strip()
        if not filename.lower().endswith(".pdf"):
            json_response(self, 400, {"error": "Please upload a .pdf file."})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            json_response(self, 400, {"error": "Empty upload."})
            return
        data = self.rfile.read(length)
        INPUT_PDF_DIR.mkdir(parents=True, exist_ok=True)
        dest = INPUT_PDF_DIR / filename
        with open(dest, "wb") as fh:
            fh.write(data)
        stem = filename[:-4]
        json_response(self, 200, {
            "filename": filename,
            "book": stem,
            "guess": guess_attributes_from_name(stem),
            "already_extracted": final_json_path(stem).is_file(),
            "bytes": len(data),
        })

    # -- API: extract ------------------------------------------------------
    def api_extract(self) -> None:
        body = read_json_body(self)
        pdf_filename = (body.get("pdf") or "").strip()
        book = (body.get("book") or "").strip()
        force_real = bool(body.get("force"))
        if not book and pdf_filename:
            book = pdf_filename[:-4] if pdf_filename.lower().endswith(".pdf") else pdf_filename
        if not book:
            json_response(self, 400, {"error": "Choose a PDF to extract first."})
            return
        if not pdf_filename:
            pdf_filename = f"{book}.pdf"

        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[job_id] = {
                "state": "running", "step": 0, "step_label": CACHED_STEPS[0],
                "progress": 0, "message": "Queued…", "book": book, "ready": False,
                "total_steps": len(CACHED_STEPS),
            }
        threading.Thread(
            target=run_extraction_job,
            args=(job_id, pdf_filename, book, force_real),
            daemon=True,
        ).start()
        json_response(self, 200, {"job_id": job_id, "book": book})

    def api_extract_status(self, qs: Dict[str, List[str]]) -> None:
        job_id = (qs.get("job_id") or [""])[0]
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            payload = dict(job) if job else None
        if not payload:
            json_response(self, 404, {"error": "Unknown job."})
            return
        json_response(self, 200, payload)

    # -- API: extracted content (split-screen, editable) -------------------
    def api_get_extraction(self, qs: Dict[str, List[str]]) -> None:
        book = (qs.get("book") or [""])[0].strip()
        path = final_json_path(book)
        if not path.is_file():
            json_response(self, 404, {"error": f"No extraction found for {book!r}."})
            return
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        json_response(self, 200, {"book": book, "document": doc})

    def api_save_extraction(self) -> None:
        body = read_json_body(self)
        book = (body.get("book") or "").strip()
        document = body.get("document")
        if not book or not isinstance(document, dict):
            json_response(self, 400, {"error": "book and document are required."})
            return
        path = final_json_path(book)
        if not path.is_file():
            json_response(self, 404, {"error": f"No extraction found for {book!r}."})
            return
        # Keep a one-shot backup of the original extraction.
        backup = path.with_suffix(".json.orig")
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(document, fh, ensure_ascii=False, indent=2)
        json_response(self, 200, {"saved": True, "book": book})

    # -- API: serve the original PDF (split-screen left) -------------------
    def api_get_pdf(self, qs: Dict[str, List[str]]) -> None:
        book = (qs.get("book") or [""])[0].strip()
        pdf_path: Optional[Path] = None
        final_file = final_json_path(book)
        if final_file.is_file():
            try:
                with open(final_file, "r", encoding="utf-8") as fh:
                    meta = (json.load(fh).get("metadata") or {})
                src = str(meta.get("source_pdf") or "").replace("\\", "/")
                if src:
                    cand = (REPO_ROOT / src).resolve()
                    if str(cand).startswith(str(REPO_ROOT.resolve())) and cand.is_file():
                        pdf_path = cand
            except Exception:
                pass
        if pdf_path is None:
            cand = INPUT_PDF_DIR / f"{book}.pdf"
            if cand.is_file():
                pdf_path = cand
        if pdf_path is None:
            json_response(self, 404, {"error": "Original PDF not found."})
            return
        data = pdf_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'inline; filename="{pdf_path.name}"')
        _set_cors(self)
        self.end_headers()
        self.wfile.write(data)

    # -- API: preview (qa_table grouped by category) -----------------------
    def api_preview(self, qs: Dict[str, List[str]]) -> None:
        book = (qs.get("book") or [""])[0].strip()
        book_slug = (qs.get("book_slug") or [""])[0].strip() or None
        final_file = final_json_path(book)
        if not final_file.is_file():
            json_response(self, 404, {"error": f"No extraction found for {book!r}."})
            return
        export = build_qa_table_export(str(final_file), book_slug=book_slug)
        # Persist so the insert step (and any preview edits) have a file to use.
        out_path = qa_json_path(book)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(export, fh, ensure_ascii=False, indent=2)

        rows = export.get("rows") or []
        by_section: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for r in rows:
            by_section[r.get("section_type", "?")] = by_section.get(r.get("section_type", "?"), 0) + 1
            by_type[r.get("question_type", "?")] = by_type.get(r.get("question_type", "?"), 0) + 1
        json_response(self, 200, {
            "book": book,
            "metadata": export.get("metadata"),
            "topics": export.get("topics"),
            "rows": rows,
            "summary": {"total_rows": len(rows), "by_section": by_section, "by_question_type": by_type},
        })

    def api_save_preview(self) -> None:
        body = read_json_body(self)
        book = (body.get("book") or "").strip()
        rows = body.get("rows")
        if not book or not isinstance(rows, list):
            json_response(self, 400, {"error": "book and rows are required."})
            return
        path = qa_json_path(book)
        if not path.is_file():
            json_response(self, 404, {"error": "Run preview before saving edits."})
            return
        with open(path, "r", encoding="utf-8") as fh:
            export = json.load(fh)
        # Merge edited question/answer text back by row id.
        edits = {str(r.get("id")): r for r in rows if r.get("id") is not None}
        for r in export.get("rows") or []:
            e = edits.get(str(r.get("id")))
            if e:
                r["question"] = e.get("question", r.get("question"))
                r["answer"] = e.get("answer", r.get("answer"))
                if e.get("question_type"):
                    r["question_type"] = e["question_type"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(export, fh, ensure_ascii=False, indent=2)
        json_response(self, 200, {"saved": True, "book": book, "rows": len(rows)})

    # -- API: insert into MySQL --------------------------------------------
    def api_insert(self) -> None:
        body = read_json_body(self)
        book = (body.get("book") or "").strip()
        attributes = body.get("attributes") or {}
        replace = bool(body.get("replace"))
        book_slug = (body.get("book_slug") or "").strip()
        if not book:
            json_response(self, 400, {"error": "book is required."})
            return

        qa_path = qa_json_path(book)
        final_file = final_json_path(book)
        if not final_file.is_file():
            json_response(self, 404, {"error": f"No extraction found for {book!r}."})
            return

        # Build a fresh qa_table if the preview step never ran; otherwise reuse
        # the (possibly preview-edited) file on disk.
        if not qa_path.is_file():
            export = build_qa_table_export(str(final_file), book_slug=book_slug or None)
            with open(qa_path, "w", encoding="utf-8") as fh:
                json.dump(export, fh, ensure_ascii=False, indent=2)

        with open(qa_path, "r", encoding="utf-8") as fh:
            document = json.load(fh)

        meta = document.setdefault("metadata", {})
        if book_slug:
            meta["book_slug"] = book_slug
        # Stamp the user-selected attributes onto the stored metadata.
        if attributes:
            meta["attributes"] = attributes

        # Lazy import so the server still boots when pymysql is absent.
        try:
            from insert_qa_table import connect_mysql, insert_qa_table
        except Exception as exc:
            json_response(self, 500, {"error": f"Insert module unavailable: {exc}"})
            return

        try:
            conn = connect_mysql(
                host=DB_HOST, port=DB_PORT, user=DB_USER,
                password=DB_PASSWORD, database=DB_NAME,
            )
        except Exception as exc:
            json_response(self, 502, {
                "error": "Could not connect to the database.",
                "detail": str(exc),
                "hint": f"Expected MySQL at {DB_HOST}:{DB_PORT} (database '{DB_NAME}'). "
                        "Start MySQL or set DB_* environment variables, then try again.",
            })
            return

        try:
            chapter_n, theory_n, content_n = insert_qa_table(
                document, conn, replace_book=replace,
            )
        except Exception as exc:
            json_response(self, 500, {"error": f"Insert failed: {exc}"})
            return
        finally:
            conn.close()

        # Persist metadata changes (attributes/slug) back to the qa_table file.
        with open(qa_path, "w", encoding="utf-8") as fh:
            json.dump(document, fh, ensure_ascii=False, indent=2)

        json_response(self, 200, {
            "inserted": True,
            "book_slug": meta.get("book_slug"),
            "chapters": chapter_n,
            "theory_sections": theory_n,
            "qa_rows": content_n,
        })

    # -- Static files ------------------------------------------------------
    def serve_static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"
        rel = path.lstrip("/").replace("\\", "/")
        if ".." in rel.split("/"):
            self.send_error(403)
            return
        # webapp/ assets first, then fall back to repo files (outputs/, etc.).
        candidate = WEBAPP_DIR / rel
        if not candidate.is_file():
            candidate = REPO_ROOT / rel
        if not candidate.is_file():
            self.send_error(404)
            return
        data = candidate.read_bytes()
        mime, _ = mimetypes.guess_type(str(candidate))
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        _set_cors(self)
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = DEFAULT_PORT
    httpd = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Pipeline web app: http://{host}:{port}/")
    print(f"Serving UI from:  {WEBAPP_DIR}")
    print(f"Repo root:        {REPO_ROOT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
