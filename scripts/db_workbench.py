#!/usr/bin/env python3
"""Run notes / MCQ conversion / MCQ generation straight off the MySQL bank.

The full pipeline (PDF -> Mathpix OCR -> topic split -> LLM -> ``*_final.json``
-> MySQL) is expensive and only needs to run once per book. Once a book is in
the database, the three *downstream* jobs need nothing from that pipeline --
they only need theory text and question rows, both of which MySQL already holds.

This entry point exposes exactly those three jobs against the database:

    notes    -- regenerate structured study notes from ``qa_theory_chapter``
    convert  -- turn theory/open-ended questions into auto-gradable MCQs
    similar  -- generate fresh MCQs modelled on existing bank MCQs

It is strictly additive and safe to run alongside everything else:

* **Read-only against MySQL.** No subcommand writes to the database. Results
  land in JSON files you review before deciding to load anything.
* **The extraction pipeline is untouched.** ``*_final.json``, ``*_qa_table.json``
  and ``edu_pipeline/workspace/`` are never read or written. DB-sourced notes go
  to a separate ``edu_pipeline/workspace_db/`` tree.
* **Existing behaviour is reused, not reimplemented.** Notes go through the same
  ``generate_short_notes`` the pipeline uses; conversion and generation call the
  same functions as ``scripts/mcq_generator.py`` / ``scripts/mcq_similar.py``.

Examples::

    python scripts/db_workbench.py health
    python scripts/db_workbench.py books
    python scripts/db_workbench.py books --book "10 PHYSICS FOUNDATION"

    # Study notes for chapters 1 and 2, read from MySQL theory
    python scripts/db_workbench.py notes "10 PHYSICS FOUNDATION" --topics 1,2

    # Convert 20 theory questions in one book into MCQs
    python scripts/db_workbench.py convert --book "10 PHYSICS FOUNDATION" --limit 20

    # Two fresh MCQs for each of 10 existing MCQs in one chapter
    python scripts/db_workbench.py similar --chapter 666 --per-item 2 --limit 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Entry points live in scripts/; make the repository root importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edu_pipeline.shared.paths import PROJECT_ROOT, load_dotenv

# Credentials must be in the environment BEFORE any pipeline/bank module is
# imported -- several of them freeze DB_* / OLLAMA_* at import time. Every
# heavy import below is therefore deferred into the command functions.
load_dotenv(PROJECT_ROOT / ".env")

# Anchored to the repository, not the working directory, so the CLI writes to the
# same place whether it is invoked from the repo root or from scripts/.
DEFAULT_OUT_DIR = str(PROJECT_ROOT / "edu_pipeline" / "workspace_db")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _write_json(path: str, payload: Any) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
    return path


def _require_ollama() -> bool:
    """Print a clear message and return False when Ollama/the model is missing."""
    from edu_pipeline.generators.questions import mcq_generator as mg

    status = mg.health()
    if not status.get("ollama_ok"):
        print(f"Ollama not reachable: {status.get('error')}", file=sys.stderr)
        print("Start Ollama, or point OLLAMA_MODEL at an installed model.",
              file=sys.stderr)
        return False
    print(f"Using Ollama model: {status.get('model')}")
    return True


def _resolve_book_or_exit(name: str) -> str:
    from edu_pipeline.storage import db_repository as dbrepo

    slug = dbrepo.resolve_book(name)
    if slug:
        return slug
    print(f"No unique book matching: {name!r}", file=sys.stderr)
    print("Run 'python scripts/db_workbench.py books' to see the exact slugs.",
          file=sys.stderr)
    raise SystemExit(1)


def _filters_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    """Build a ``storage.database`` filter dict from the shared bank options."""
    filters: Dict[str, Any] = {}
    if getattr(args, "subject", None):
        filters["subject"] = args.subject
    if getattr(args, "klass", None):
        filters["class"] = args.klass
    if getattr(args, "book", None):
        filters["book"] = args.book
    if getattr(args, "chapter", None):
        filters["chapter"] = args.chapter
    return filters


def _add_bank_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--subject", action="append", default=[],
                        help="filter by subject (repeatable)")
    parser.add_argument("--class", dest="klass", action="append", default=[],
                        help="filter by class (repeatable)")
    parser.add_argument("--book", action="append", default=[],
                        help="filter by exact book_slug (repeatable)")
    parser.add_argument("--chapter", action="append", default=[],
                        help="filter by chapter_id (repeatable)")
    parser.add_argument("--list-chapters", action="store_true",
                        help="list matching chapter ids and exit (no LLM needed)")


def _list_chapters(filters: Dict[str, Any]) -> int:
    from edu_pipeline.storage import database as bank_read

    chapters = bank_read.compute_facets(filters).get("chapter", [])
    if not chapters:
        print("No chapters found for that filter.")
        return 0
    for ch in chapters:
        print(f"  --chapter {ch['value']}   {ch.get('label', '')}  "
              f"({ch['count']} questions)")
    return 0


# ---------------------------------------------------------------------------
# health / books
# ---------------------------------------------------------------------------
def cmd_health(args: argparse.Namespace) -> int:
    from edu_pipeline.storage import db_repository as dbrepo

    db = dbrepo.health()
    conn = db.get("connection") or {}
    if conn:
        print(f"MySQL via  : {conn.get('transport')} -> {conn.get('target')}  "
              f"(user={conn.get('user')}, db={conn.get('database')})")

    if db.get("db_ok"):
        print(f"MySQL      : ok  ({db['chapters']} chapters, "
              f"{db['theory_sections']} theory sections, {db['questions']} questions)")
    else:
        print(f"MySQL      : FAILED  {db.get('error')}")
        # pymysql blames the host even for socket failures; say what really broke.
        if conn.get("transport") == "unix_socket" and not conn.get("socket_exists"):
            print(f"             -> no socket file at {conn.get('target')}.")
            print("             Point DB_SOCKET at the real socket, or comment it "
                  "out in .env to use DB_HOST/DB_PORT over TCP.")

    from edu_pipeline.generators.questions import mcq_generator as mg

    llm = mg.health()
    if llm.get("ollama_ok"):
        print(f"Ollama     : ok  (model {llm.get('model')})  <- convert / similar")
    else:
        print(f"Ollama     : FAILED  {llm.get('error')}")

    # `notes` does NOT use OLLAMA_MODEL -- it runs NOTES_MODEL with
    # NOTES_FALLBACK_MODEL behind it. Checking only the line above would report
    # a healthy Ollama for a notes run that is about to fail on both models.
    _report_notes_models()
    return 0 if db.get("db_ok") else 2


def _report_notes_models() -> None:
    from edu_pipeline.shared.config import ConfigService

    cfg = ConfigService.get().llm
    try:
        import requests

        resp = requests.get(f"{cfg.base_url}/api/tags", timeout=10)
        resp.raise_for_status()
        installed = {m.get("name", "") for m in resp.json().get("models", [])}
    except Exception as exc:
        print(f"Notes model: unknown  (could not list Ollama models: {exc})")
        return

    def _present(name: str) -> bool:
        # Ollama reports "qwen3:8b"; accept a bare "qwen3" as matching it too.
        return bool(name) and (
            name in installed
            or any(i.split(":")[0] == name.split(":")[0] for i in installed)
        )

    primary_ok = _present(cfg.notes_model)
    fallback_ok = _present(cfg.notes_fallback_model)
    mark = "ok" if primary_ok else ("fallback only" if fallback_ok else "MISSING")
    print(f"Notes model: {mark}  (NOTES_MODEL={cfg.notes_model}"
          f"{'' if primary_ok else ' [not installed]'}, "
          f"NOTES_FALLBACK_MODEL={cfg.notes_fallback_model}"
          f"{'' if fallback_ok else ' [not installed]'})  <- notes")
    if not (primary_ok or fallback_ok):
        print("             -> 'notes' will fail. Pull one, or set "
              "NOTES_MODEL to an installed model.")


def cmd_books(args: argparse.Namespace) -> int:
    from edu_pipeline.storage import db_repository as dbrepo

    if args.book:
        slug = _resolve_book_or_exit(args.book)
        rows = dbrepo.book_overview(slug)
        print(f"{slug}  ({len(rows)} chapter(s))")
        for r in rows:
            print(f"  ch {r['chapter_number']:>2}  id={r['chapter_id']:<6} "
                  f"{r['theory_sections']:>4} theory  {r['questions']:>5} questions  "
                  f"{r['chapter_name']}")
        return 0

    books = dbrepo.list_books()
    if not books:
        print("No books found in the database.")
        return 1
    print(f"Books in the database ({len(books)}):")
    for slug in books:
        print(f"  - {slug}")
    print("\nUse --book \"<slug>\" to list that book's chapters.")
    return 0


# ---------------------------------------------------------------------------
# notes -- theory from MySQL -> structured study notes
# ---------------------------------------------------------------------------
def cmd_notes(args: argparse.Namespace) -> int:
    from edu_pipeline.storage import db_repository as dbrepo

    book_slug = _resolve_book_or_exit(args.book)

    topic_filter = None
    if args.topics:
        topic_filter = {int(p.strip()) for p in args.topics.split(",") if p.strip()}

    repo = dbrepo.load_book(book_slug, topic_filter=topic_filter, output_root=args.out_dir)

    topics = repo.topics
    if not topics:
        print(f"No chapters found for {book_slug!r}"
              + (f" matching topics {sorted(topic_filter)}" if topic_filter else ""),
              file=sys.stderr)
        return 1

    usable = sum(1 for t in topics if t.get("theory_sections"))
    print(f"Loaded {len(topics)} chapter(s) from database "
          f"({usable} with theory sections).")
    if not usable:
        print("None of the selected chapters have theory text in "
              "theory_sections; nothing to summarise.", file=sys.stderr)
        return 1

    if not _require_ollama():
        return 2

    # Importing the generator sets the notes-mode env toggles it relies on.
    from edu_pipeline.generators.notes.generator import generate_short_notes

    written = generate_short_notes(repo)
    if not written:
        print("No study notes were written.", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Helper to generate notes for a single book (used by notes_all)
# ---------------------------------------------------------------------------
def _generate_notes_for_book(book_slug: str, topics: Optional[set[int]], out_dir: str) -> int:
    from edu_pipeline.storage import db_repository as dbrepo
    from edu_pipeline.generators.notes.generator import generate_short_notes

    repo = dbrepo.load_book(book_slug, topic_filter=topics, output_root=out_dir)
    if not repo.topics:
        print(f"No chapters found for {book_slug!r}", file=sys.stderr)
        return 1
    usable = sum(1 for t in repo.topics if t.get("theory_sections"))
    if not usable:
        print(f"Book {book_slug!r} has no theory sections", file=sys.stderr)
        return 1
    if not _require_ollama():
        return 2
    written = generate_short_notes(repo)
    if not written:
        print(f"No notes written for {book_slug!r}", file=sys.stderr)
        return 1
    return 0

# ---------------------------------------------------------------------------
# notes_all -- generate notes for every book in the database (or filtered)
# ---------------------------------------------------------------------------
def cmd_notes_all(args: argparse.Namespace) -> int:
    from edu_pipeline.storage import db_repository as dbrepo

    # Build optional topic filter as a set of ints if provided
    topic_filter = None
    if args.topics:
        topic_filter = {int(p.strip()) for p in args.topics.split(",") if p.strip()}

    # Determine which books to process
    if args.book:
        # User passed explicit book slugs (repeatable)
        slugs = args.book
    else:
        slugs = dbrepo.list_books()

    if not slugs:
        print("No books found to process.", file=sys.stderr)
        return 1

    exit_code = 0
    for slug in slugs:
        print(f"Generating notes for book: {slug}")
        rc = _generate_notes_for_book(slug, topic_filter, args.out_dir)
        if rc != 0:
            print(f"Failed for {slug} (code {rc})", file=sys.stderr)
            exit_code = rc if exit_code == 0 else exit_code
    return exit_code


# ---------------------------------------------------------------------------
# convert -- theory/open-ended bank rows -> MCQs
# ---------------------------------------------------------------------------
def cmd_convert(args: argparse.Namespace) -> int:
    from edu_pipeline.generators.questions import mcq_generator as mg

    filters = _filters_from_args(args)
    if args.type:
        filters["type"] = args.type
    if args.list_chapters:
        return _list_chapters(filters)

    if not _require_ollama():
        return 2

    from edu_pipeline.storage import database as bank_read

    try:
        candidates = mg._iter_theory_bank_items(filters, args.limit)
    except Exception as exc:
        print(f"Could not read the question bank: {exc}", file=sys.stderr)
        return 2
    if not candidates:
        print("No convertible theory questions matched that filter.")
        return 0
    print(f"Found {len(candidates)} theory question(s) to convert.")

    items: List[Dict[str, Any]] = []
    for it in candidates:
        # The bank summary omits the model answer; fetch it per row.
        try:
            detail = bank_read.get_item(it["id"])
            answer = ((detail or {}).get("item") or {}).get("answer", "")
        except Exception:
            answer = ""
        items.append({
            "id": it["id"],
            "question": it.get("stem", ""),
            "answer": answer,
            "subject": it.get("subject", ""),
            "chapter_name": it.get("chapter_name", ""),
            "question_type": it.get("question_type", ""),
        })

    result: Dict[str, List[Dict[str, Any]]] = {"mcqs": [], "errors": []}
    t0 = time.time()
    for i, src in enumerate(items, 1):
        print(f"[{i}/{len(items)}] #{src['id']} ({src['question_type']}) ... ",
              end="", flush=True)
        one = mg.convert_items([src])
        result["mcqs"].extend(one["mcqs"])
        result["errors"].extend(one["errors"])
        print("ok" if one["mcqs"]
              else f"skip ({one['errors'][0]['reason'] if one['errors'] else '?'})")

    out = _write_json(args.out, result)
    print(f"\nDone in {time.time() - t0:.1f}s -> {out}")
    print(f"  converted: {len(result['mcqs'])}   skipped: {len(result['errors'])}")
    return 0


# ---------------------------------------------------------------------------
# similar -- existing bank MCQs -> fresh similar MCQs
# ---------------------------------------------------------------------------
def cmd_similar(args: argparse.Namespace) -> int:
    from edu_pipeline.generators.questions import similarity as sim

    filters = _filters_from_args(args)
    filters["type"] = args.source_type or ["MCQ"]
    if args.list_chapters:
        return _list_chapters(filters)

    if not _require_ollama():
        return 2

    try:
        sources = sim._fetch_source_mcqs(filters, args.limit)
    except Exception as exc:
        print(f"Could not read the question bank: {exc}", file=sys.stderr)
        return 2
    if not sources:
        print("No matching source MCQs found for that filter.")
        return 0

    print(f"Generating ~{args.per_item} similar MCQ(s) for each of "
          f"{len(sources)} source MCQ(s)...")
    t0 = time.time()
    result = sim.generate_from_sources(sources, per_item=args.per_item)

    out = _write_json(args.out, result)
    print(f"\nDone in {time.time() - t0:.1f}s -> {out}")
    print(f"  generated: {len(result['mcqs'])}   errors/skipped: {len(result['errors'])}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="db_workbench",
        description="Notes / MCQ conversion / MCQ generation sourced from the "
                    "MySQL bank, without re-running the extraction pipeline.",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_health = sub.add_parser("health", help="check MySQL + Ollama reachability")
    p_health.set_defaults(func=cmd_health)

    p_books = sub.add_parser("books", help="list books, or one book's chapters")
    p_books.add_argument("--book", default="", help="book slug (or unique substring)")
    p_books.set_defaults(func=cmd_books)

    p_notes = sub.add_parser(
        "notes",
        help="regenerate study notes from theory stored in MySQL",
        description="Reads theory from MySQL and writes study-notes "
                    "JSON. MySQL is not modified.",
    )
    p_notes.add_argument("book", help="book slug (or unique substring)")
    p_notes.add_argument("--topics", default=None,
                         help="comma-separated chapter numbers (e.g. 1,2,3)")
    p_notes.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                         help=f"output root for study notes (default {DEFAULT_OUT_DIR})")
    p_notes.set_defaults(func=cmd_notes)

    # ---------------------------------------------------------------------------
    # notes_all -- generate notes for all books (or filtered list)
    # ---------------------------------------------------------------------------
    p_notes_all = sub.add_parser(
        "notes_all",
        help="generate study notes for all books (or filtered list) from MySQL",
        description="Iterates over all books in the database and writes study‑notes PDFs using the same pipeline as the 'notes' command.",
    )
    p_notes_all.add_argument("--topics", default=None, help="comma‑separated chapter numbers (e.g. 1,2,3) to limit theory sections")
    p_notes_all.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help=f"output root for study notes (default {DEFAULT_OUT_DIR})")
    p_notes_all.add_argument("--book", action="append", default=[], help="specific book slug(s) to process (repeatable); if omitted all books are processed")
    p_notes_all.set_defaults(func=cmd_notes_all)

    p_conv = sub.add_parser(
        "convert",
        help="convert theory/open-ended bank questions into MCQs",
    )
    _add_bank_filter_args(p_conv)
    p_conv.add_argument("--type", action="append", default=[],
                        help="restrict source question_type (repeatable)")
    p_conv.add_argument("--limit", type=int, default=20,
                        help="max questions to convert (default 20)")
    p_conv.add_argument("--out", default=os.path.join(DEFAULT_OUT_DIR, "converted_mcqs.json"),
                        help="output JSON path")
    p_conv.set_defaults(func=cmd_convert)

    p_sim = sub.add_parser(
        "similar",
        help="generate fresh MCQs similar to existing bank MCQs",
    )
    _add_bank_filter_args(p_sim)
    p_sim.add_argument("--source-type", action="append", default=[],
                       help="source question_type(s) to draw from (default: MCQ)")
    p_sim.add_argument("--per-item", type=int, default=2,
                       help="similar MCQs per source (default 2)")
    p_sim.add_argument("--limit", type=int, default=20,
                       help="max source MCQs to draw from (default 20)")
    p_sim.add_argument("--out", default=os.path.join(DEFAULT_OUT_DIR, "similar_mcqs.json"),
                       help="output JSON path")
    p_sim.set_defaults(func=cmd_similar)

    return ap


def _is_db_connection_error(exc: BaseException) -> bool:
    try:
        import pymysql
    except ImportError:
        return False
    return isinstance(exc, pymysql.err.MySQLError)


def _print_db_failure(exc: BaseException) -> None:
    """Explain a connection failure instead of dumping a pymysql traceback.

    pymysql names the *host* even when it dialled a UNIX socket, so the raw
    error reads "on 'localhost' ([Errno 2] No such file or directory)" and sends
    people looking for a network problem that isn't there.
    """
    from edu_pipeline.storage import db_repository as dbrepo

    try:
        conn = dbrepo.connection_target()
    except Exception:
        conn = {}

    print(f"Cannot reach MySQL: {exc}", file=sys.stderr)
    if conn:
        print(f"  tried : {conn.get('transport')} -> {conn.get('target')}  "
              f"(user={conn.get('user')}, db={conn.get('database')})", file=sys.stderr)
    if conn.get("transport") == "unix_socket" and not conn.get("socket_exists"):
        print(f"  cause : no socket file exists at {conn.get('target')} -- this is a "
              "socket problem, not a network one.", file=sys.stderr)
        print("  fix   : comment out DB_SOCKET in .env to connect over TCP using "
              "DB_HOST/DB_PORT,", file=sys.stderr)
        print("          or set DB_SOCKET to the real socket path "
              "(mysqladmin variables | grep -w socket).", file=sys.stderr)
    elif conn.get("transport") == "tcp":
        print(f"  fix   : check MySQL is listening at {conn.get('target')} and that "
              "DB_HOST/DB_PORT in .env point at it.", file=sys.stderr)
    print("  check : python3 db_workbench.py health", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        # Connection failures are configuration, not bugs -- report them
        # legibly. Anything else keeps its traceback.
        if _is_db_connection_error(exc):
            _print_db_failure(exc)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
