#!/usr/bin/env python3
"""Refresh qa_content_row.question_type from *_qa_table.json (section-aware)."""

from __future__ import annotations

import argparse
import glob
import json
import os
from typing import Any, Dict, List, Tuple

import pymysql
from pymysql.cursors import DictCursor

from edu_pipeline.generators.questions.classifier import classify_question
from edu_pipeline.extraction.topic_extractor import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER


def load_rows(path: str) -> Tuple[str, List[Dict[str, Any]]]:
    with open(path, "r", encoding="utf-8") as handle:
        doc = json.load(handle)
    slug = (doc.get("metadata") or {}).get("book_slug") or ""
    return slug, [r for r in (doc.get("rows") or []) if isinstance(r, dict)]


def row_type(row: Dict[str, Any]) -> str:
    if row.get("question_type"):
        return str(row["question_type"])
    return classify_question(
        row.get("question") or "",
        section_type=str(row.get("section_type") or row.get("source_type") or ""),
        subsection=str(row.get("title") or ""),
    )


def refresh_from_json(connection, qa_paths: List[str], *, dry_run: bool) -> int:
    updated = 0
    with connection.cursor() as cur:
        for path in qa_paths:
            book_slug, rows = load_rows(path)
            if not book_slug:
                print(f"Skip (no book_slug): {path}")
                continue
            for row in rows:
                question = row.get("question") or ""
                if not question:
                    continue
                qtype = row_type(row)
                chapter_number = int(
                    row.get("topic_number") or row.get("chapter_number") or 0
                )
                if dry_run:
                    updated += 1
                    continue
                cur.execute(
                    """
                    UPDATE qa_content_row r
                    INNER JOIN qa_chapter c ON c.chapter_id = r.chapter_id
                    SET r.question_type = %s
                    WHERE c.book_slug = %s
                      AND c.chapter_number = %s
                      AND r.question = %s
                    """,
                    (qtype, book_slug, chapter_number, question),
                )
                updated += cur.rowcount
        if not dry_run:
            connection.commit()
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh question_type from QA JSON")
    parser.add_argument(
        "qa_json",
        nargs="*",
        help="Path(s) to *_qa_table.json (default: all under outputs/)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    paths = args.qa_json or sorted(
        glob.glob(os.path.join("outputs", "*", "*_qa_table.json"))
    )
    if not paths:
        print("No *_qa_table.json files found.")
        return 1

    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    try:
        n = refresh_from_json(conn, paths, dry_run=args.dry_run)
    finally:
        conn.close()

    print(f"{'Would update' if args.dry_run else 'Updated'} {n} row(s) from {len(paths)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
