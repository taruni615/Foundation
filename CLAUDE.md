# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A pipeline + web app that turns Foundation-series textbook PDFs into structured,
reviewable digital content (chapter summaries, key points, topic-split theory,
and typed Q&A), loads it into MySQL, and serves it through browser viewers and a
question-bank / assessment web app. Everything is Python 3.13 **standard library
only** for the servers (no web framework); external work (OCR, LLM, DB) is
delegated to services and thin helper modules.

## Setup & running

```bash
pip install -r requirements.txt          # requests, latex2mathml, pymysql, pypdf, xhtml2pdf, fpdf2
python app_server.py                      # main web app  → http://127.0.0.1:8000/  (APP_PORT to change)
python viewer_api.py                      # read-only DB/JSON viewer → http://127.0.0.1:8765/  (VIEWER_API_PORT)
```

Viewers must be reached through the server, not `file://`:
- DB viewer: `http://127.0.0.1:8765/Viewer/textbook_viewer.html`
- JSON viewer: `http://127.0.0.1:8765/Viewer/output_json_viewer.html?json=/outputs/<book>/<book>_final.json`

There is no test suite, linter, or build step configured.

## Pipeline (command line)

The end-to-end flow, all driven by `topicwise_pipeline.py` unless noted:

```
PDF → Mathpix OCR (Mathpix_Cache/<book>_mathpix.md) → split into topics_md/
    → Ollama (qwen3:8b) key points + summaries → topics_json/
    → merge/relabel (v3.1) + LaTeX→MathML → <book>_final.json
    → <book>_qa_table.json → MySQL (foundation db)
```

Key invocations:

```bash
# Full pipeline from a PDF (images optional)
python -u topicwise_pipeline.py "Input_PDFs/10 PHYSICS FOUNDATION.pdf" --with-images

# Regenerate student summaries only, in place
python -u topicwise_pipeline.py --summarize-only "outputs/<book>/<book>_final.json" --force-summarize --summarize-llm

# Export the DB-ready QA table from a final.json
python final_to_qa_table.py "outputs/<book>/<book>_final.json"

# Load a QA table into MySQL (use --replace-book to overwrite an existing book)
python insert_qa_table.py "outputs/<book>/<book>_qa_table.json"

# Short-notes / study-notes only (never touches *_final.json)
python short_notes_pipeline.py "10 PHYSICS FOUNDATION"
```

`topicwise_pipeline.py` is the ~6800-line core and owns most flags (`--topics`,
`--skip-llm`, `--force-llm`, `--merge-final`, `--relabel-final`,
`--export-qa-table`, `--summarize-llm`, `--with-images`, `--fix-mathml`,
`--theory-only`, …). **Important:** it stops at JSON — DB load and viewing are
separate manual steps, and human review is expected before a book is treated as
production-ready.

## Architecture

**`topicwise_pipeline.py` is the shared foundation.** It defines the DB config
(`DB_HOST/PORT/USER/PASSWORD/NAME`), the Ollama client, Mathpix client, JSON
extraction helpers, and pedagogy/relabelling logic. Almost every other module
imports from it rather than duplicating logic (`viewer_api`, `bank_read`,
`insert_qa_table`, `final_to_qa_table`, `mcq_generator`, `short_notes_pipeline`).
Config is env-driven with defaults (see the top of the file); `.env` holds MySQL
credentials and is loaded on server startup.

**Two servers, both stdlib `ThreadingHTTPServer`:**
- `app_server.py` — the write/action app: upload PDF, run extraction with live
  progress, edit/preview extracted content, insert to MySQL, plus the question
  bank and assessment/exam APIs. Routes live in the GET/POST dispatch around
  line 332/388 (`/api/extract`, `/api/insert`, `/api/bank/*`, `/api/exams/*`,
  `/api/mcq/*`, `/api/auth/*`, …). It boots even when pymysql/Ollama are absent
  — only the affected routes degrade (bank/mcq modules are imported lazily).
- `viewer_api.py` — read-only browsing of the MySQL `qa_*` tables (slated for
  retirement per code comments; `bank_read.py` deliberately owns its own DB
  connection to avoid depending on it).

**Data layers:**
- MySQL database `foundation`, three tables: `qa_chapter` (chapter header +
  summary + key points), `qa_theory_chapter` (theory subsections, FK to
  chapter), `qa_content_row` (one row per Q&A item). Schema in `schema/`.
- `subject` / `class` / `board` are **not columns** — they are derived from
  `book_slug` (see `app_server.guess_attributes_from_name`, mirrored in
  `bank_read.py`). Attribute filters resolve to matching `book_slug` sets
  before hitting SQL.
- `assessment_store.py` is a **file-backed** store (JSON under `assessment/`:
  `users.json`, `exams.json`, `attempts.json`) for accounts, hosted exams, and
  student attempts. Grading is server-side (correct answers never sent to the
  client before submit); pbkdf2 passwords + HMAC bearer tokens. Works without
  MySQL.

**MCQ generation** (both Ollama-powered, additive, read-only w.r.t. DB):
- `mcq_generator.py` — converts theory/open-ended questions into auto-gradable MCQs.
- `mcq_similar.py` — generates fresh MCQs similar to existing bank MCQs.

**Frontend** (`webapp/`, vanilla JS ES modules, no build): a small SPA shell
(`src/shell/` — router, registry, sidenav) over a store (`src/state/`), with two
feature modules — `src/modules/bank/` (question bank browse/detail) and
`src/modules/exams/` (dashboard, create, adaptive, analytics, login views). API
clients in `src/api/`. Standalone HTML viewers live in `Viewer/`.

## External dependencies & their env vars

- **Mathpix** (PDF OCR): `MATHPIX_APP_ID`, `MATHPIX_APP_KEY`. Results cached in
  `Mathpix_Cache/` so re-runs skip OCR.
- **Ollama** (local LLM, default model `qwen3:8b`): `OLLAMA_BASE_URL`,
  `OLLAMA_MODEL`, `OLLAMA_TIMEOUT`. Used for key points, summaries, MCQ generation.
- **MySQL**: `DB_SOCKET` (UNIX socket, preferred) or `DB_HOST`/`DB_PORT` (TCP
  fallback), `DB_USER`, `DB_PASSWORD`, `DB_NAME` (default `foundation`).

## Conventions worth respecting

- Servers use **stdlib only** — do not introduce Flask/FastAPI/etc. to match the
  existing style.
- Prefer importing helpers from `topicwise_pipeline.py` over re-implementing
  extraction/DB/LLM logic. Where duplication exists (e.g. the vocabulary in
  `bank_read.py` mirroring `app_server.py`), keep both copies in sync.
- New capabilities have been added **additively**: importing a module must not
  pull in the heavy pipeline or require Ollama/MySQL at import time (use lazy
  imports and graceful degradation), so the app keeps working with the books
  already in `outputs/` when external services are offline.
- Output JSON format is **v3.1**; `<book>_final.json` is the source of truth,
  `<book>_qa_table.json` is the DB-ready flattening.

Further detail: `README.md` and `docs/PIPELINE_WORKFLOW.md`.
