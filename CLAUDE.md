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
make setup                               # dependencies + .env from .env.example
python scripts/app_server.py                      # main web app  → http://127.0.0.1:8000/  (APP_PORT to change)
python scripts/viewer_api.py                      # read-only DB/JSON viewer → http://127.0.0.1:8765/  (VIEWER_API_PORT)
```

Viewers must be reached through the server, not `file://`:
- DB viewer: `http://127.0.0.1:8765/Viewer/textbook_viewer.html`
- JSON viewer: `http://127.0.0.1:8765/Viewer/output_json_viewer.html?json=/edu_pipeline/workspace/<book>/<book>_final.json`

Static assets are served from `edu_pipeline/web/frontend/` first, then from the
repo root — so `/Viewer/...` resolves to the package copy and
`/edu_pipeline/workspace/...` resolves to extraction output.

Quality gates: `make test` (243 tests, no MySQL/Ollama needed), `make lint`,
`make check`. Config lives in `pyproject.toml`; see CONTRIBUTING.md.

Non-runtime utilities live in `tools/` (`tools/export/`, `tools/migration/`) and
are never imported by the application. The CLI entry points live in `scripts/`
and are thin wrappers over `edu_pipeline/`; the package is the implementation.

## Pipeline (command line)

The end-to-end flow, all driven by `scripts/topicwise_pipeline.py` unless noted:

```
PDF → Mathpix OCR (edu_pipeline/materials/cache/<book>_mathpix.md) → topics_md/
    → Ollama (qwen3:8b) key points + summaries → topics_json/
    → merge/relabel (v3.1) + LaTeX→MathML → <book>_final.json
    → <book>_qa_table.json → MySQL (foundation db)
```

Paths below are written as `WS` = `edu_pipeline/workspace` (extraction output)
and `IN` = `edu_pipeline/materials/input` (source PDFs). Both are resolved
**relative to the current working directory**, so always run from the repo root.

Key invocations:

```bash
# Full pipeline from a PDF (images optional)
python -u scripts/topicwise_pipeline.py "edu_pipeline/materials/input/10 PHYSICS FOUNDATION.pdf" --with-images

# Regenerate student summaries only, in place
python -u scripts/topicwise_pipeline.py --summarize-only "edu_pipeline/workspace/<book>/<book>_final.json" --force-summarize --summarize-llm

# Export the DB-ready QA table from a final.json
python scripts/final_to_qa_table.py "edu_pipeline/workspace/<book>/<book>_final.json"

# Load a QA table into MySQL (use --replace-book to overwrite an existing book)
python scripts/insert_qa_table.py "edu_pipeline/workspace/<book>/<book>_qa_table.json"

# Short-notes / study-notes only (never touches *_final.json)
python scripts/short_notes_pipeline.py "10 PHYSICS FOUNDATION"
```

`edu_pipeline/extraction/topic_extractor.py` is the ~7,200-line core and owns most flags (`--topics`,
`--skip-llm`, `--force-llm`, `--merge-final`, `--relabel-final`,
`--export-qa-table`, `--summarize-llm`, `--with-images`, `--fix-mathml`,
`--theory-only`, …). **Important:** it stops at JSON — DB load and viewing are
separate manual steps, and human review is expected before a book is treated as
production-ready.

## Architecture

**`edu_pipeline/extraction/topic_extractor.py` is the shared foundation.** It defines the DB config
(`DB_HOST/PORT/USER/PASSWORD/NAME`), the Ollama client, Mathpix client, JSON
extraction helpers, and pedagogy/relabelling logic. Almost every other module
imports from it rather than duplicating logic (`viewer_api`, `bank_read`,
`insert_qa_table`, `final_to_qa_table`, `mcq_generator`, `short_notes_pipeline`).
Config is env-driven with defaults (see the top of the file); `.env` holds MySQL
credentials and is loaded on server startup.

**Two servers, both stdlib `ThreadingHTTPServer`:**
- `edu_pipeline/web/server.py` (run via `scripts/app_server.py`) — the write/action app: upload PDF, run extraction with live
  progress, edit/preview extracted content, insert to MySQL, plus the question
  bank and assessment/exam APIs. Routes live in the GET/POST dispatch around
  line 332/388 (`/api/extract`, `/api/insert`, `/api/bank/*`, `/api/exams/*`,
  `/api/mcq/*`, `/api/auth/*`, …). It boots even when pymysql/Ollama are absent
  — only the affected routes degrade (bank/mcq modules are imported lazily).
- `edu_pipeline/web/api.py` (run via `scripts/viewer_api.py`) — read-only browsing of the MySQL `qa_*` tables (slated for
  retirement per code comments; `storage/database.py` deliberately owns its own DB
  connection to avoid depending on it).

**Data layers:**
- MySQL database `foundation`, three tables: `qa_chapter` (chapter header +
  summary + key points), `qa_theory_chapter` (theory subsections, FK to
  chapter), `qa_content_row` (one row per Q&A item). Schema in `schema/`.
- `subject` / `class` / `board` are **not columns** — they are derived from
  `book_slug` (see `web/server.guess_attributes_from_name`, mirrored in
  `storage/database.py`). Attribute filters resolve to matching `book_slug` sets
  before hitting SQL.
- `edu_pipeline/assessment/storage.py` is a **file-backed** store (JSON under
  `edu_pipeline/assessment/`:
  `users.json`, `exams.json`, `attempts.json`) for accounts, hosted exams, and
  student attempts. Grading is server-side (correct answers never sent to the
  client before submit); pbkdf2 passwords + HMAC bearer tokens. Works without
  MySQL.

**MCQ generation** (both Ollama-powered, additive, read-only w.r.t. DB):
- `generators/questions/mcq_generator.py` — converts theory/open-ended questions into auto-gradable MCQs.
- `generators/questions/similarity.py` — generates fresh MCQs similar to existing bank MCQs.

**Frontend** (`edu_pipeline/web/frontend/webapp/`, vanilla JS ES modules, no
build): a small SPA shell (`src/shell/` — router, registry, sidenav) over a store
(`src/state/`), with two feature modules — `src/modules/bank/` (question bank
browse/detail) and `src/modules/exams/` (dashboard, create, adaptive, analytics,
login views). API clients in `src/api/`. Standalone HTML viewers live in
`edu_pipeline/web/frontend/Viewer/`.

## External dependencies & their env vars

- **Mathpix** (PDF OCR): `MATHPIX_APP_ID`, `MATHPIX_APP_KEY`. Results cached in
  `edu_pipeline/materials/cache/` so re-runs skip OCR. The cache is **not**
  version-controlled but is kept on disk — deleting it means paying for OCR again.
- **Ollama** (local LLM, default model `qwen3:8b`): `OLLAMA_BASE_URL`,
  `OLLAMA_MODEL`, `OLLAMA_TIMEOUT`. Used for key points, summaries, MCQ generation.
- **MySQL**: `DB_SOCKET` (UNIX socket, preferred) or `DB_HOST`/`DB_PORT` (TCP
  fallback), `DB_USER`, `DB_PASSWORD`, `DB_NAME` (default `foundation`).

## Layer responsibilities & dependency flow

```
        shared/         infrastructure: paths, db_config, logger, events,
          ▲             config, constants, json_utils. Imports nothing else.
          │
  ┌───────┴────────┬──────────────┬───────────────┐
  │                │              │               │
extraction/    repository/       ai/         assessment/
PDF → topics    *_final.json    providers,    exams, attempts,
→ *_final.json  load/query      prompts,      accounts
                (data access    services      (file-backed)
                 only)
  │                │              │               │
  └───────┬────────┴──────────────┘               │
          │                                       │
     generators/          storage/                │
     orchestrate:         QA-table export,        │
     notes + questions    MySQL load,             │
          │               bank queries            │
          └───────────────┬───────────────────────┘
                          │
                        web/    HTTP + frontend (composes everything)
```

- **Repositories** (`repository/`) only load, save and query `*_final.json`. No
  business logic, no LLM calls, no DB.
- **Services** (`ai/services/`) hold domain logic. Each AI service follows the
  same shape: *validate input → load prompt → execute model → parse response →
  validate output → return domain dict*, with `{"ok": bool, ...}` results rather
  than exceptions.
- **Generators** (`generators/`) orchestrate: read from a repository, call a
  service, persist. They should not contain extraction or DB logic.
- **`workflow.py`** is the only module allowed to import across all layers; it is
  the orchestrator, not a layer.

Two known deviations are accepted (not accidental):
- `storage/` imports `classify_question` from `generators/questions/classifier.py`.
  The classifier is a pure rule engine that belongs in a domain package, but it
  backs the public `scripts/question_type_classifier.py` wrapper, so it cannot move
  without renaming a public module.
- `extraction/topic_extractor.py` lazily calls into `generators` and `storage`
  for question typing and QA-table export. These were previously hidden behind
  root-wrapper imports; they are now explicit, and remain lazy to avoid cycles.

## Conventions worth respecting

- Servers use **stdlib only** — do not introduce Flask/FastAPI/etc. to match the
  existing style.
- Prefer importing helpers from `scripts/topicwise_pipeline.py` over re-implementing
  extraction/DB/LLM logic.
- Cross-layer helpers live in `edu_pipeline/shared/` — import from there rather
  than copying:
  - `shared/paths.py` — `PACKAGE_ROOT`, `PROJECT_ROOT`, `load_dotenv()`, and the
    CWD-relative `OUTPUT_DIR` / `MATHPIX_CACHE_DIR`
  - `shared/db_config.py` — `DB_HOST/PORT/USER/PASSWORD/NAME/CHARSET/COLLATION`.
    Deliberately **not** re-exported from `shared/__init__` so the env reads stay
    after `load_dotenv()` in `web/server.py`.
  - `shared/json_utils.py` — `extract_json_object()` for parsing LLM replies
  - `shared/constants.py` — `QA_SECTION_KEYS` (question arrays in `topics[]`)
  - `shared/logger.py` — `PipelineLogger`
- **Never import the root wrapper scripts from inside `edu_pipeline/`.** Use the
  real module (`from edu_pipeline.storage import database as bank_read`), not
  `import bank_read`. The wrappers exist for CLI users; importing them from the
  package inverts the dependency and only works when the repo root is on
  `sys.path`.
- One deliberate duplication remains: `storage/database.derive_attributes` and
  `web/server.guess_attributes_from_name` implement the same rule but are **not**
  identical (the server's `SUBJECTS` list carries an extra `"Other"` entry and
  its input is not `None`-safe). Keep them in sync by hand; do not merge them
  without deciding which behaviour is canonical.
- New capabilities have been added **additively**: importing a module must not
  pull in the heavy pipeline or require Ollama/MySQL at import time (use lazy
  imports and graceful degradation), so the app keeps working with the books
  already in `edu_pipeline/workspace/` when external services are offline.
- Output JSON format is **v3.1**; `<book>_final.json` is the source of truth,
  `<book>_qa_table.json` is the DB-ready flattening.

Further detail: `README.md` and `docs/PIPELINE_WORKFLOW.md`.
