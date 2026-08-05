#!/usr/bin/env python3
"""Read-only adapter: MySQL ``qa_*`` tables -> in-memory :class:`BookRepository`.

The notes generator (and anything else built on ``RepositoryService``) reads a
``*_final.json`` document produced by the extraction pipeline. When a book has
already been extracted and loaded into MySQL, that document is redundant: the
theory it needs is sitting in ``qa_chapter`` + ``qa_theory_chapter``.

This module rebuilds the *subset of the v3.1 document shape that the notes path
actually reads* straight from the database, so notes can be regenerated without
re-running OCR / extraction and without a ``*_final.json`` on disk.

Deliberately narrow and strictly additive:

* **Read-only.** Nothing here writes to MySQL. Only ``SELECT``s are issued.
* **No pipeline import.** Importing this module does not pull in the extraction
  pipeline, Ollama, or the web server.
* **Nothing existing is touched.** The synthesised repository points at a
  *separate* output root (``edu_pipeline/workspace_db`` by default), so an
  existing ``edu_pipeline/workspace/<book>/`` tree is never read or overwritten.

The reconstructed document is **not** a full ``*_final.json`` — questions,
images and per-topic MathML are not rebuilt, because the notes path does not use
them. It is not a substitute for the extraction output and must never be written
over one; see :func:`synthetic_final_path`.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Set

from edu_pipeline.repository.models import BookRepository

# Output root for DB-sourced runs. Kept separate from ``edu_pipeline/workspace``
# so a DB-backed regeneration can never overwrite pipeline extraction output.
DB_OUTPUT_DIRNAME = "workspace_db"

# Marks documents built here, so a reader can tell them apart from real
# extraction output at a glance.
DB_DOCUMENT_SOURCE = "mysql:qa_tables"


def default_output_root() -> str:
    """Default root for DB-sourced artefacts, beside the pipeline workspace.

    Anchored to ``PACKAGE_ROOT`` rather than the current working directory. The
    extraction pipeline's ``OUTPUT_DIR`` is deliberately CWD-relative and so must
    be run from the repository root; nothing here needs that constraint, and
    honouring it would scatter output under whichever directory the CLI happened
    to be invoked from.
    """
    from edu_pipeline.shared.paths import PACKAGE_ROOT

    return os.path.join(str(PACKAGE_ROOT), DB_OUTPUT_DIRNAME)


def synthetic_final_path(book_slug: str, output_root: Optional[str] = None) -> str:
    """Path a DB-sourced repository *pretends* to have been loaded from.

    Nothing writes this file. It exists so the existing sidecar helpers
    (``study_notes_json_path_from_final`` / ``_study_notes_topics_dir_from_final``),
    which derive their output locations from a ``*_final.json`` path, place the
    study-notes files inside ``<output_root>/<book_slug>/`` instead of the
    current directory.
    """
    root = output_root or default_output_root()
    return os.path.join(root, book_slug, f"{book_slug}_final.json")


# ---------------------------------------------------------------------------
# Pure document construction (no DB access -- unit-testable on plain dicts)
# ---------------------------------------------------------------------------
def build_topic(chapter_row: Dict[str, Any],
                theory_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Build one v3.1-shaped ``topics[]`` entry from a chapter + its theory rows.

    ``theory_sections`` uses the ``heading`` / ``markdown`` keys, which is what
    ``RepositoryService.get_topic_theory_text`` reads on v3.1 documents.
    """
    sections: List[Dict[str, Any]] = []
    for row in theory_rows:
        body = str(row.get("topic_explanation") or "").strip()
        if not body:
            continue
        sections.append({
            "heading": str(row.get("topic_name") or "").strip(),
            "markdown": body,
            "section_order": row.get("section_order"),
        })

    return {
        "topic_number": int(chapter_row.get("chapter_number") or 0),
        "chapter_name": str(chapter_row.get("chapter_name") or ""),
        "page_range": str(chapter_row.get("page_range") or ""),
        "theory_sections": sections,
        # Carried through for reference/diffing. The notes generator overwrites
        # ``summary`` with the freshly generated notes; it is never persisted
        # back to MySQL from here.
        "summary": str(chapter_row.get("summary") or ""),
        "key_points_text": str(chapter_row.get("key_points") or ""),
        "db_chapter_id": chapter_row.get("chapter_id"),
    }


def build_document(book_slug: str,
                   chapter_rows: Sequence[Dict[str, Any]],
                   theory_by_chapter: Dict[Any, Sequence[Dict[str, Any]]],
                   ) -> Dict[str, Any]:
    """Assemble the in-memory document from already-fetched rows."""
    topics = [
        build_topic(chapter, theory_by_chapter.get(chapter.get("chapter_id"), []))
        for chapter in chapter_rows
    ]
    return {
        "metadata": {
            "name": book_slug,
            "format_version": "3.1",
            "source": DB_DOCUMENT_SOURCE,
            "topic_count": len(topics),
        },
        "topics": topics,
    }


# ---------------------------------------------------------------------------
# DB access
# ---------------------------------------------------------------------------
def list_books() -> List[str]:
    """Book slugs that have at least one chapter loaded."""
    from edu_pipeline.storage import database as bank_read

    with bank_read._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT book_slug FROM qa_chapter ORDER BY book_slug")
            return [r["book_slug"] for r in cur.fetchall()]


def book_overview(book_slug: str) -> List[Dict[str, Any]]:
    """Per-chapter counts for one book, for ``--list-chapters``-style output."""
    from edu_pipeline.storage import database as bank_read

    with bank_read._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.chapter_id, c.chapter_number, c.chapter_name, c.page_range, "
                "  (SELECT COUNT(*) FROM qa_theory_chapter t "
                "     WHERE t.chapter_id = c.chapter_id) AS theory_sections, "
                "  (SELECT COUNT(*) FROM qa_content_row r "
                "     WHERE r.chapter_id = c.chapter_id) AS questions "
                "FROM qa_chapter c WHERE c.book_slug = %s ORDER BY c.chapter_number",
                (book_slug,),
            )
            return list(cur.fetchall())


def resolve_book(name: str) -> Optional[str]:
    """Resolve a user-typed book argument to an exact ``book_slug``.

    Accepts the exact slug, or a unique case-insensitive substring of one.
    Returns ``None`` when nothing matches or the match is ambiguous.
    """
    slugs = list_books()
    wanted = str(name or "").strip()
    if wanted in slugs:
        return wanted
    low = wanted.lower()
    matches = [s for s in slugs if low and low in s.lower()]
    return matches[0] if len(matches) == 1 else None


def load_book(book_slug: str,
              *,
              topic_filter: Optional[Set[int]] = None,
              output_root: Optional[str] = None) -> BookRepository:
    """Load one book out of MySQL as a :class:`BookRepository`.

    ``topic_filter`` limits which chapter numbers are fetched. ``source_path``
    on the returned repository is *synthetic* (see :func:`synthetic_final_path`)
    -- the file does not exist and must not be written.
    """
    from edu_pipeline.storage import database as bank_read

    with bank_read._connect() as conn:
        with conn.cursor() as cur:
            sql = ("SELECT chapter_id, chapter_number, chapter_name, page_range, "
                   "summary, key_points FROM qa_chapter WHERE book_slug = %s")
            params: List[Any] = [book_slug]
            if topic_filter:
                ordered = sorted(topic_filter)
                sql += " AND chapter_number IN (%s)" % ",".join(["%s"] * len(ordered))
                params.extend(ordered)
            cur.execute(sql + " ORDER BY chapter_number", params)
            chapter_rows = list(cur.fetchall())

            theory_by_chapter: Dict[Any, List[Dict[str, Any]]] = {}
            chapter_ids = [r["chapter_id"] for r in chapter_rows]
            if chapter_ids:
                cur.execute(
                    "SELECT chapter_id, section_order, topic_name, topic_explanation "
                    "FROM qa_theory_chapter WHERE chapter_id IN (%s) "
                    "ORDER BY chapter_id, section_order"
                    % ",".join(["%s"] * len(chapter_ids)),
                    chapter_ids,
                )
                for row in cur.fetchall():
                    theory_by_chapter.setdefault(row["chapter_id"], []).append(row)

    document = build_document(book_slug, chapter_rows, theory_by_chapter)
    return BookRepository(
        raw_json=document,
        source_path=synthetic_final_path(book_slug, output_root),
    )


def connection_target() -> Dict[str, Any]:
    """Describe how :func:`storage.database._connect` will reach MySQL.

    pymysql reports the *host* in its error message even when it dialled a UNIX
    socket, so a missing socket file surfaces as the thoroughly misleading
    "Can't connect to MySQL server on 'localhost' ([Errno 2] No such file or
    directory)". Surfacing the transport separately makes that failure legible.
    Never includes the password.
    """
    from edu_pipeline.shared.db_config import DB_HOST, DB_NAME, DB_PORT, DB_USER
    from edu_pipeline.storage import database as bank_read

    if bank_read.DB_SOCKET:
        return {
            "transport": "unix_socket",
            "target": bank_read.DB_SOCKET,
            "socket_exists": os.path.exists(bank_read.DB_SOCKET),
            "user": DB_USER,
            "database": DB_NAME,
        }
    return {
        "transport": "tcp",
        "target": f"{DB_HOST}:{DB_PORT}",
        "user": DB_USER,
        "database": DB_NAME,
    }


def health() -> Dict[str, Any]:
    """Reachability + row counts for the tables this adapter reads.

    Never raises, so callers can report a clear message instead of a traceback.
    """
    try:
        from edu_pipeline.storage import database as bank_read

        with bank_read._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM qa_chapter")
                chapters = int(cur.fetchone()["n"])
                cur.execute("SELECT COUNT(*) AS n FROM qa_theory_chapter")
                theory = int(cur.fetchone()["n"])
                cur.execute("SELECT COUNT(*) AS n FROM qa_content_row")
                questions = int(cur.fetchone()["n"])
        return {"db_ok": True, "chapters": chapters,
                "theory_sections": theory, "questions": questions,
                "connection": connection_target()}
    except Exception as exc:  # pragma: no cover - environment dependent
        try:
            conn_info = connection_target()
        except Exception:
            conn_info = {}
        return {"db_ok": False, "error": str(exc), "connection": conn_info}
