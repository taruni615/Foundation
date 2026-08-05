#!/usr/bin/env python3
"""Backfill the PRD question-tagging columns on ``qa_content_row``.

Applies ``generators.questions.tagger`` to bank rows and writes the results into
the ``difficulty``, ``subtopic``, ``cognitive_level`` and ``learning_objective``
columns added by ``schema/add_question_tagging_columns.sql``.

Subtopic resolution needs the chapter's theory-section headings, so rows are
processed **one chapter at a time**: the headings are fetched once per chapter
and reused for all of its questions rather than re-queried per row.

Read-only against everything except those four columns -- question text, answers
and types are never modified.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from edu_pipeline.generators.questions.tagger import tag_items

from .database import _connect

# Columns this module is allowed to write.  Kept explicit so a future edit
# cannot widen the UPDATE by accident.
TAG_COLUMNS = ("difficulty", "subtopic", "cognitive_level", "learning_objective")

_UPDATE_SQL = """
UPDATE qa_content_row
   SET difficulty = %s, subtopic = %s, cognitive_level = %s, learning_objective = %s
 WHERE id = %s
"""


def _headings_for_chapters(cur, chapter_ids: Sequence[Any]) -> Dict[Any, List[str]]:
    """Theory-section names per chapter, ordered as they appear in the book."""
    if not chapter_ids:
        return {}
    placeholders = ",".join(["%s"] * len(chapter_ids))
    cur.execute(
        "SELECT chapter_id, topic_name FROM qa_theory_chapter "
        f"WHERE chapter_id IN ({placeholders}) ORDER BY chapter_id, section_order",
        tuple(chapter_ids),
    )
    out: Dict[Any, List[str]] = {}
    for row in cur.fetchall():
        out.setdefault(row["chapter_id"], []).append(row["topic_name"] or "")
    return out


def chapters_to_tag(book_slug: str = "", only_untagged: bool = True) -> List[Any]:
    """Chapter ids holding rows that still need tagging."""
    where = []
    params: List[Any] = []
    if book_slug:
        where.append("book_slug = %s")
        params.append(book_slug)
    if only_untagged:
        where.append("(cognitive_level = '' OR cognitive_level IS NULL)")
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    cn = _connect()
    try:
        with cn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT chapter_id FROM qa_content_row{clause} ORDER BY chapter_id",
                tuple(params),
            )
            return [r["chapter_id"] for r in cur.fetchall()]
    finally:
        cn.close()


def backfill(
    book_slug: str = "",
    only_untagged: bool = True,
    limit: Optional[int] = None,
    dry_run: bool = False,
    progress: Optional[Any] = None,
) -> Dict[str, Any]:
    """Tag bank rows chapter by chapter.

    ``only_untagged`` restricts the pass to rows whose ``cognitive_level`` is
    still empty, so a re-run costs nothing and an interrupted run resumes where
    it stopped.  ``limit`` caps the number of rows updated (useful for a smoke
    test before committing to the full bank).
    """
    chapter_ids = chapters_to_tag(book_slug, only_untagged)
    stats: Dict[str, Any] = {
        "chapters": 0,
        "rows_read": 0,
        "rows_updated": 0,
        "with_subtopic": 0,
        "by_difficulty": {},
        "by_cognitive_level": {},
        "dry_run": dry_run,
    }
    if not chapter_ids:
        return stats

    row_where = ["chapter_id = %s"]
    if book_slug:
        row_where.append("book_slug = %s")
    if only_untagged:
        row_where.append("(cognitive_level = '' OR cognitive_level IS NULL)")
    row_sql = (
        "SELECT id, chapter_id, chapter_name, question, question_type "
        "FROM qa_content_row WHERE " + " AND ".join(row_where) + " ORDER BY id"
    )

    cn = _connect()
    try:
        for chapter_id in chapter_ids:
            if limit is not None and stats["rows_updated"] >= limit:
                break

            with cn.cursor() as cur:
                params: List[Any] = [chapter_id]
                if book_slug:
                    params.append(book_slug)
                cur.execute(row_sql, tuple(params))
                rows = cur.fetchall()
                if not rows:
                    continue
                headings = _headings_for_chapters(cur, [chapter_id])

            if limit is not None:
                rows = rows[: max(0, limit - stats["rows_updated"])]

            tagged = tag_items(rows, headings)
            stats["chapters"] += 1
            stats["rows_read"] += len(rows)

            payload = []
            for t in tagged:
                if t.get("subtopic"):
                    stats["with_subtopic"] += 1
                stats["by_difficulty"][t["difficulty"]] = (
                    stats["by_difficulty"].get(t["difficulty"], 0) + 1
                )
                stats["by_cognitive_level"][t["cognitive_level"]] = (
                    stats["by_cognitive_level"].get(t["cognitive_level"], 0) + 1
                )
                payload.append(
                    (
                        t["difficulty"],
                        t["subtopic"],
                        t["cognitive_level"],
                        t["learning_objective"],
                        t["id"],
                    )
                )

            if not dry_run and payload:
                with cn.cursor() as cur:
                    cur.executemany(_UPDATE_SQL, payload)
                cn.commit()
            stats["rows_updated"] += len(payload)

            if progress:
                progress(chapter_id, len(payload), stats["rows_updated"])
    finally:
        cn.close()

    return stats


def coverage(book_slug: str = "") -> Dict[str, Any]:
    """How much of the bank currently carries tags."""
    where = " WHERE book_slug = %s" if book_slug else ""
    params = (book_slug,) if book_slug else ()
    cn = _connect()
    try:
        with cn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM qa_content_row{where}", params)
            total = cur.fetchone()["n"]

            joiner = " AND " if where else " WHERE "
            cur.execute(
                f"SELECT COUNT(*) AS n FROM qa_content_row{where}"
                f"{joiner}cognitive_level <> ''",
                params,
            )
            tagged = cur.fetchone()["n"]

            cur.execute(
                f"SELECT COUNT(*) AS n FROM qa_content_row{where}{joiner}subtopic <> ''",
                params,
            )
            with_sub = cur.fetchone()["n"]

            cur.execute(
                f"SELECT difficulty, COUNT(*) AS n FROM qa_content_row{where}"
                " GROUP BY difficulty ORDER BY n DESC",
                params,
            )
            by_diff = {r["difficulty"]: r["n"] for r in cur.fetchall()}

            cur.execute(
                f"SELECT cognitive_level, COUNT(*) AS n FROM qa_content_row{where}"
                " GROUP BY cognitive_level ORDER BY n DESC",
                params,
            )
            by_cog = {r["cognitive_level"] or "(untagged)": r["n"] for r in cur.fetchall()}
    finally:
        cn.close()

    return {
        "total": total,
        "tagged": tagged,
        "untagged": total - tagged,
        "with_subtopic": with_sub,
        "pct_tagged": round(100 * tagged / total, 1) if total else 0.0,
        "by_difficulty": by_diff,
        "by_cognitive_level": by_cog,
    }
