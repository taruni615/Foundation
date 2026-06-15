#!/usr/bin/env python3
"""Load a *_qa_table.json file into qa_chapter, qa_theory_chapter, qa_content_row.

qa_chapter (header): book_slug, chapter_number, chapter_name, page_range,
  summary, key_points — chapter_id is the numeric unique ID.

qa_theory_chapter: id, chapter_id (FK), topic_name, topic_explanation.

qa_content_row: id, chapter_id (FK), book_slug, chapter_name, question, answer, question_type.

Requires: pip install pymysql

Usage::

  python insert_qa_table.py "outputs/10TH BIOLOGY FOUNDATION/10TH BIOLOGY FOUNDATION_qa_table.json"
  python insert_qa_table.py --replace-book path/to/book_qa_table.json
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any, Dict, List, Tuple

try:
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError:
    print("Install pymysql: pip install pymysql", file=sys.stderr)
    raise

from question_type_classifier import classify_question
from topicwise_pipeline import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    expand_image_tokens_to_data_urls,
    plain_section_title,
)

KEY_POINTS_JOIN = "\n"
MARKDOWN_H2_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _heading_from_markdown(markdown: str) -> str:
    match = MARKDOWN_H2_RE.search(markdown or "")
    return match.group(1).strip() if match else ""


def _env(primary: str, fallback: str, default: str = "") -> str:
    return os.environ.get(primary) or os.environ.get(fallback) or default


def key_points_to_text(key_points: Any) -> str:
    """Flatten key_points[].text into one TEXT column."""
    if not isinstance(key_points, list):
        return ""
    lines: List[str] = []
    for item in key_points:
        if isinstance(item, dict):
            text = (item.get("text") or "").strip()
            if text:
                lines.append(text)
        elif isinstance(item, str) and item.strip():
            lines.append(item.strip())
    return KEY_POINTS_JOIN.join(lines)


def chapter_number_from_topic(topic: Dict[str, Any]) -> int:
    return int(topic.get("topic_number") or topic.get("chapter_number") or 0)


def chapter_number_from_row(row: Dict[str, Any]) -> int:
    if row.get("chapter_number") is not None:
        return int(row["chapter_number"])
    if row.get("topic_number") is not None:
        return int(row["topic_number"])
    raise ValueError("row missing chapter_number / topic_number")


def load_qa_table(path: str) -> Dict[str, Any]:
    import json

    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def connect_mysql(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
):
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


def delete_book_rows(cursor, book_slug: str) -> None:
    cursor.execute("DELETE FROM qa_chapter WHERE book_slug = %s", (book_slug,))


UPSERT_CHAPTER = """
INSERT INTO qa_chapter (
  book_slug, chapter_number, chapter_name, page_range, summary, key_points
) VALUES (
  %(book_slug)s, %(chapter_number)s, %(chapter_name)s,
  %(page_range)s, %(summary)s, %(key_points)s
)
ON DUPLICATE KEY UPDATE
  chapter_name = VALUES(chapter_name),
  page_range = VALUES(page_range),
  summary = VALUES(summary),
  key_points = VALUES(key_points),
  updated_at = CURRENT_TIMESTAMP
"""

UPSERT_THEORY = """
INSERT INTO qa_theory_chapter (
  chapter_id, topic_name, topic_explanation, section_order
) VALUES (
  %(chapter_id)s, %(topic_name)s, %(topic_explanation)s, %(section_order)s
)
ON DUPLICATE KEY UPDATE
  topic_name = VALUES(topic_name),
  topic_explanation = VALUES(topic_explanation),
  updated_at = CURRENT_TIMESTAMP
"""

INSERT_CONTENT = """
INSERT INTO qa_content_row (
  chapter_id, book_slug, chapter_name, question, answer, question_type
) VALUES (
  %(chapter_id)s, %(book_slug)s, %(chapter_name)s,
  %(question)s, %(answer)s, %(question_type)s
)
"""


def build_chapter_records(
    book_slug: str,
    topics: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """One header row per chapter (topic)."""
    by_number: Dict[int, Dict[str, Any]] = {}
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        chapter_number = chapter_number_from_topic(topic)
        if chapter_number <= 0:
            continue
        by_number[chapter_number] = {
            "book_slug": book_slug,
            "chapter_number": chapter_number,
            "chapter_name": topic.get("chapter_name") or "",
            "page_range": topic.get("page_range") or "",
            "summary": topic.get("summary") or "",
            "key_points": key_points_to_text(topic.get("key_points")),
        }
    return list(by_number.values())


def build_theory_records(
    topics: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """One row per theory_sections[] entry (chapter_number for FK lookup)."""
    records: List[Dict[str, Any]] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        chapter_number = chapter_number_from_topic(topic)
        if chapter_number <= 0:
            continue
        sections = topic.get("theory_sections") or []
        if not sections:
            records.append({
                "chapter_number": chapter_number,
                "topic_name": "",
                "topic_explanation": "",
                "section_order": 1,
            })
            continue
        image_assets = topic.get("image_assets") or {}
        for order, section in enumerate(sections, start=1):
            if not isinstance(section, dict):
                continue
            raw_name = section.get("topics") or section.get("title") or ""
            topic_explanation = section.get("markdown") or ""
            if image_assets and topic_explanation:
                topic_explanation = expand_image_tokens_to_data_urls(
                    topic_explanation, image_assets
                )
            topic_name = plain_section_title(raw_name, max_len=512)
            if not topic_name and topic_explanation:
                topic_name = plain_section_title(
                    _heading_from_markdown(topic_explanation), max_len=512
                )
            if not topic_name and not str(topic_explanation).strip():
                continue
            records.append({
                "chapter_number": chapter_number,
                "topic_name": topic_name or f"Section {order}",
                "topic_explanation": topic_explanation,
                "section_order": order,
            })
    return records


def build_content_records(
    book_slug: str,
    rows: List[Dict[str, Any]],
    chapter_names: Dict[int, str],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slug = row.get("book_slug") or book_slug
        question = row.get("question") or ""
        answer = row.get("answer")
        if not question and not answer:
            continue
        chapter_number = chapter_number_from_row(row)
        chapter_name = row.get("chapter_name") or chapter_names.get(chapter_number, "")
        section_type = str(row.get("section_type") or row.get("source_type") or "")
        question_type = row.get("question_type") or classify_question(
            question,
            section_type=section_type,
            subsection=str(row.get("title") or ""),
        )
        records.append({
            "chapter_number": chapter_number,
            "book_slug": slug,
            "chapter_name": chapter_name,
            "question": question,
            "answer": answer,
            "question_type": question_type,
        })
    return records


def load_chapter_id_map(cursor, book_slug: str) -> Dict[int, int]:
    cursor.execute(
        "SELECT chapter_id, chapter_number FROM qa_chapter WHERE book_slug = %s",
        (book_slug,),
    )
    return {int(r["chapter_number"]): int(r["chapter_id"]) for r in cursor.fetchall()}


def attach_chapter_ids(
    records: List[Dict[str, Any]],
    chapter_id_map: Dict[int, int],
    *,
    label: str,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for rec in records:
        cn = int(rec["chapter_number"])
        chapter_id = chapter_id_map.get(cn)
        if chapter_id is None:
            raise ValueError(f"{label}: no chapter_id for chapter_number {cn}")
        item = {k: v for k, v in rec.items() if k != "chapter_number"}
        item["chapter_id"] = chapter_id
        out.append(item)
    return out


def insert_qa_table(
    document: Dict[str, Any],
    connection,
    *,
    replace_book: bool = False,
) -> Tuple[int, int, int]:
    meta = document.get("metadata") or {}
    book_slug = meta.get("book_slug") or ""
    if not book_slug:
        raise ValueError("metadata.book_slug is required in qa_table JSON")

    topics = [t for t in (document.get("topics") or []) if isinstance(t, dict)]
    rows = [r for r in (document.get("rows") or []) if isinstance(r, dict)]

    chapter_records = build_chapter_records(book_slug, topics)
    theory_records = build_theory_records(topics)
    chapter_names = {r["chapter_number"]: r["chapter_name"] for r in chapter_records}
    content_records = build_content_records(book_slug, rows, chapter_names)

    chapter_numbers = {r["chapter_number"] for r in chapter_records}
    for rec in theory_records + content_records:
        if rec["chapter_number"] not in chapter_numbers:
            raise ValueError(
                f"chapter_number {rec['chapter_number']} has no qa_chapter header"
            )

    with connection.cursor() as cursor:
        if replace_book:
            delete_book_rows(cursor, book_slug)

        if chapter_records:
            cursor.executemany(UPSERT_CHAPTER, chapter_records)

        chapter_id_map = load_chapter_id_map(cursor, book_slug)
        if not chapter_id_map:
            raise ValueError(f"no qa_chapter rows created for book_slug={book_slug!r}")

        theory_db = attach_chapter_ids(theory_records, chapter_id_map, label="theory")
        content_db = attach_chapter_ids(content_records, chapter_id_map, label="content")

        if theory_db:
            cursor.executemany(UPSERT_THEORY, theory_db)
        if content_db:
            cursor.executemany(INSERT_CONTENT, content_db)

    connection.commit()
    return len(chapter_records), len(theory_db), len(content_db)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Insert *_qa_table.json into MySQL")
    parser.add_argument("qa_table_json", help="Path to *_qa_table.json")
    parser.add_argument(
        "--replace-book",
        action="store_true",
        help="DELETE qa_chapter rows for book_slug (CASCADE theory + content)",
    )
    parser.add_argument("--host", default=_env("DB_HOST", "MYSQL_HOST", DB_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(_env("DB_PORT", "MYSQL_PORT", str(DB_PORT))),
    )
    parser.add_argument("--user", default=_env("DB_USER", "MYSQL_USER", DB_USER))
    parser.add_argument(
        "--password",
        default=_env("DB_PASSWORD", "MYSQL_PASSWORD", DB_PASSWORD),
    )
    parser.add_argument(
        "--database",
        default=_env("DB_NAME", "MYSQL_DATABASE", DB_NAME),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse JSON and print counts only; no DB connection",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = os.path.abspath(args.qa_table_json)
    if not os.path.isfile(path):
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    document = load_qa_table(path)
    book_slug = (document.get("metadata") or {}).get("book_slug", "")

    if args.dry_run:
        topics = document.get("topics") or []
        json_rows = document.get("rows") or []
        chapters = build_chapter_records(book_slug, topics)
        theory_n = len(build_theory_records(topics))
        names = {r["chapter_number"]: r["chapter_name"] for r in chapters}
        content_n = len(build_content_records(book_slug, json_rows, names))
        print(f"book_slug={book_slug!r}")
        print(f"qa_chapter headers: {len(chapters)}")
        print(f"qa_theory_chapter sections: {theory_n}")
        print(f"qa_content_row rows: {content_n}")
        return 0

    try:
        conn = connect_mysql(
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            database=args.database,
        )
    except pymysql.err.OperationalError as exc:
        if exc.args and exc.args[0] == 1045:
            print(
                "MySQL access denied. Set DB_PASSWORD (or pass --password). "
                f"Using user={args.user!r} host={args.host!r} database={args.database!r}.",
                file=sys.stderr,
            )
        raise SystemExit(1) from exc

    try:
        chapter_n, theory_n, content_n = insert_qa_table(
            document,
            conn,
            replace_book=args.replace_book,
        )
    finally:
        conn.close()

    print(
        f"Inserted/updated {chapter_n} chapter(s), "
        f"{theory_n} theory section(s), {content_n} Q&A row(s)."
    )
    print(f"book_slug={book_slug!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
