#!/usr/bin/env python3
"""Load the study-notes export into MySQL.

Reads ``exports/notes/all_notes_flat.json`` (produced by
``tools/export/notes_to_json.py``) and fills the four tables created by
``schema/notes_tables.sql``:

    notes_chapter → notes_topic → notes_formula / notes_derivation

Idempotent: every row is written with ``INSERT ... ON DUPLICATE KEY UPDATE``
against the natural keys (``book_slug`` + ``chapter_number`` for a chapter,
``note_id`` for a topic), so re-running updates in place rather than
duplicating. The formula and derivation cards belonging to a topic are deleted
and rewritten each run, since their only identity is their order within a topic.

Usage::

    python scripts/insert_notes.py                     # load / update
    python scripts/insert_notes.py --dry-run           # report, touch nothing
    python scripts/insert_notes.py --truncate          # empty the tables first
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edu_pipeline.shared import db_config as cfg  # noqa: E402

DEFAULT_IN = "exports/notes/all_notes_flat.json"

_CHAPTER_SQL = """
INSERT INTO notes_chapter
    (book_slug, book_title, class, subject, chapter_number, chapter_name,
     prerequisites, source)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    book_title = VALUES(book_title),
    class = VALUES(class),
    subject = VALUES(subject),
    chapter_name = VALUES(chapter_name),
    prerequisites = VALUES(prerequisites),
    source = VALUES(source),
    chapter_id = LAST_INSERT_ID(chapter_id)
"""

_TOPIC_SQL = """
INSERT INTO notes_topic
    (chapter_id, note_id, topic_order, topic_number, topic, estimated_time,
     difficulty, importance, quick_summary, real_life, definition, key_idea,
     working_principle, memory_hook, advanced, applications, points, mistakes)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    chapter_id = VALUES(chapter_id),
    topic_order = VALUES(topic_order),
    topic_number = VALUES(topic_number),
    topic = VALUES(topic),
    estimated_time = VALUES(estimated_time),
    difficulty = VALUES(difficulty),
    importance = VALUES(importance),
    quick_summary = VALUES(quick_summary),
    real_life = VALUES(real_life),
    definition = VALUES(definition),
    key_idea = VALUES(key_idea),
    working_principle = VALUES(working_principle),
    memory_hook = VALUES(memory_hook),
    advanced = VALUES(advanced),
    applications = VALUES(applications),
    points = VALUES(points),
    mistakes = VALUES(mistakes),
    topic_id = LAST_INSERT_ID(topic_id)
"""

_FORMULA_SQL = """
INSERT INTO notes_formula
    (topic_id, card_order, name, difficulty, formula, variables,
     when_to_use, common_mistakes, shortcut)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_DERIVATION_SQL = """
INSERT INTO notes_derivation
    (topic_id, card_order, title, why, assumptions, steps, result,
     exam_perspective)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""


def as_json(value: Any) -> str:
    """Serialise a list/dict for a MySQL JSON column (never None)."""
    return json.dumps(value or [], ensure_ascii=False)


def text(value: Any) -> str:
    return "" if value is None else str(value)


def importance(value: Any) -> Any:
    """The spec stores importance as an int; the PDF path cannot recover it."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def connect():
    import pymysql

    return pymysql.connect(
        host=cfg.DB_HOST, port=int(cfg.DB_PORT), user=cfg.DB_USER,
        password=cfg.DB_PASSWORD, database=cfg.DB_NAME,
        charset="utf8mb4", autocommit=False,
    )


def load(rows: List[Dict[str, Any]], truncate: bool) -> Dict[str, int]:
    counts = {"chapters": 0, "topics": 0, "formulas": 0, "derivations": 0}
    conn = connect()
    try:
        with conn.cursor() as cur:
            if truncate:
                cur.execute("SET FOREIGN_KEY_CHECKS = 0")
                for table in ("notes_derivation", "notes_formula",
                              "notes_topic", "notes_chapter"):
                    cur.execute(f"TRUNCATE TABLE {table}")
                cur.execute("SET FOREIGN_KEY_CHECKS = 1")
                print("  truncated the four notes tables")

            chapter_ids: Dict[tuple, int] = {}
            for row in rows:
                key = (row["book"], row["chapter_number"])
                if key not in chapter_ids:
                    cur.execute(_CHAPTER_SQL, (
                        row["book"], text(row.get("book_title")),
                        text(row.get("class")), text(row.get("subject")),
                        row["chapter_number"], text(row.get("chapter")),
                        as_json(row.get("chapter_prerequisites")),
                        text(row.get("source")),
                    ))
                    chapter_ids[key] = cur.lastrowid
                    counts["chapters"] += 1
                chapter_id = chapter_ids[key]

                cur.execute(_TOPIC_SQL, (
                    chapter_id, row["note_id"], row.get("topic_order") or 1,
                    text(row.get("topic_number")), text(row.get("topic")),
                    text(row.get("estimated_time")), text(row.get("difficulty")),
                    importance(row.get("importance")),
                    text(row.get("quick_summary")), text(row.get("real_life")),
                    text(row.get("definition")), text(row.get("key_idea")),
                    text(row.get("working_principle")), text(row.get("memory_hook")),
                    text(row.get("advanced")),
                    as_json(row.get("applications")), as_json(row.get("points")),
                    as_json(row.get("mistakes")),
                ))
                topic_id = cur.lastrowid
                counts["topics"] += 1

                # Cards have no identity beyond their order, so replace them.
                cur.execute("DELETE FROM notes_formula WHERE topic_id = %s", (topic_id,))
                cur.execute("DELETE FROM notes_derivation WHERE topic_id = %s", (topic_id,))

                for order, card in enumerate(row.get("formulas") or [], start=1):
                    cur.execute(_FORMULA_SQL, (
                        topic_id, order, text(card.get("name")),
                        text(card.get("difficulty")), text(card.get("formula")),
                        text(card.get("variables")), text(card.get("when_to_use")),
                        text(card.get("common_mistakes")), text(card.get("shortcut")),
                    ))
                    counts["formulas"] += 1

                for order, card in enumerate(row.get("derivations") or [], start=1):
                    cur.execute(_DERIVATION_SQL, (
                        topic_id, order, text(card.get("title")),
                        text(card.get("why")), as_json(card.get("assumptions")),
                        as_json(card.get("steps")), text(card.get("result")),
                        text(card.get("exam_perspective")),
                    ))
                    counts["derivations"] += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return counts


def verify() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            for table in ("notes_chapter", "notes_topic",
                          "notes_formula", "notes_derivation"):
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                print(f"  {table:18s} {cur.fetchone()[0]:5d} rows")
            cur.execute(
                "SELECT c.class, c.subject, COUNT(DISTINCT c.chapter_id), COUNT(t.topic_id) "
                "FROM notes_chapter c LEFT JOIN notes_topic t "
                "ON t.chapter_id = c.chapter_id "
                "GROUP BY c.class, c.subject "
                "ORDER BY CAST(c.class AS UNSIGNED), c.subject"
            )
            print("\n  class subject          chapters topics")
            for cls, subject, chapters, topics in cur.fetchall():
                print(f"  {cls:>5s} {subject:16s} {chapters:8d} {topics:6d}")
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", default=DEFAULT_IN)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--truncate", action="store_true",
                        help="empty the notes tables before loading")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if args.verify_only:
        verify()
        return 0

    with open(args.source, encoding="utf-8") as handle:
        data = json.load(handle)
    rows = data["notes"] if isinstance(data, dict) else data
    print(f"Loaded {args.source}: {len(rows)} topics")

    if args.dry_run:
        chapters = {(r["book"], r["chapter_number"]) for r in rows}
        print(f"  would write {len(chapters)} chapters, {len(rows)} topics, "
              f"{sum(len(r.get('formulas') or []) for r in rows)} formulas, "
              f"{sum(len(r.get('derivations') or []) for r in rows)} derivations")
        return 0

    counts = load(rows, args.truncate)
    print(f"  wrote {counts['chapters']} chapters, {counts['topics']} topics, "
          f"{counts['formulas']} formulas, {counts['derivations']} derivations")
    print("\nVerification:")
    verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
