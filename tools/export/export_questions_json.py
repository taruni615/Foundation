"""Export every textbook question from MySQL as JSON, grouped class -> subject.

Questions only: the ``answer`` column is deliberately never read. Many bank rows
carry a misaligned answer (it holds the *next* question's text -- a known
extraction-side data bug documented in CLAUDE.md), so an answer-free export is
the one view of the bank that is trustworthy end to end.

Output tree (default ``exports/questions/``)::

    all_questions_by_class_subject.json   every class/subject/book/chapter
    by-class-subject/class-10_physics.json    one file per class+subject pair
    index.json                                counts only, no question text

Usage::

    python tools/export/export_questions_json.py
    python tools/export/export_questions_json.py --out-dir some/dir
    python tools/export/export_questions_json.py --class 9 --subject Physics
    python tools/export/export_questions_json.py --include-duplicate-books
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List

# This file lives in tools/export/ -- put the repo root on sys.path.
sys.path.append(str(Path(__file__).resolve().parents[2]))

import pymysql  # noqa: E402

from edu_pipeline.shared.db_config import (  # noqa: E402
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
)
from edu_pipeline.storage.database import derive_attributes  # noqa: E402

# Book slugs that duplicate another slug already in the bank. "10 PHYSICS
# FOUNDATION" and "10_physics_foundation" are the same eight chapters loaded
# twice; the human-readable slug wins because derive_attributes() can only
# recover class="10" from that form.
DUPLICATE_BOOK_SLUGS = {"10_physics_foundation"}

# Control characters that are legal in MySQL but noise in a JSON export.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]")

QUERY = """
SELECT
    r.id,
    r.book_slug,
    c.chapter_number,
    r.chapter_name,
    c.page_range,
    r.question,
    r.question_type,
    r.difficulty,
    r.subtopic,
    r.cognitive_level,
    r.learning_objective
FROM qa_content_row r
LEFT JOIN qa_chapter c ON r.chapter_id = c.chapter_id
ORDER BY r.book_slug, c.chapter_number, r.id
"""


def clean(value: Any) -> Any:
    """Strip control characters from strings; pass everything else through."""
    if isinstance(value, str):
        return _CONTROL_RE.sub("", value).strip()
    return value


def class_sort_key(label: str) -> tuple:
    """Numeric classes first in numeric order, then anything unrecognised."""
    return (0, int(label)) if label.isdigit() else (1, 0)


def fetch_rows() -> List[Dict[str, Any]]:
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(QUERY)
            return list(cursor.fetchall())
    finally:
        conn.close()


def build_tree(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Nest flat rows into class -> subject -> book -> chapter -> questions."""
    classes: Dict[str, Any] = OrderedDict()

    for row in rows:
        book_slug = row["book_slug"] or ""
        attrs = derive_attributes(book_slug)
        cls = attrs["class"] or "Unspecified"
        subject = attrs["subject"] or "Unspecified"

        cls_node = classes.setdefault(
            cls, {"class": cls, "question_count": 0, "subjects": OrderedDict()}
        )
        sub_node = cls_node["subjects"].setdefault(
            subject, {"subject": subject, "question_count": 0, "books": OrderedDict()}
        )
        book_node = sub_node["books"].setdefault(
            book_slug,
            {
                "book_slug": book_slug,
                "board": attrs["board"],
                "question_count": 0,
                "chapters": OrderedDict(),
            },
        )

        chapter_number = row["chapter_number"]
        chapter_key = chapter_number if chapter_number is not None else row["chapter_name"]
        chapter_node = book_node["chapters"].setdefault(
            chapter_key,
            {
                "chapter_number": chapter_number,
                "chapter_name": clean(row["chapter_name"]) or "",
                "page_range": clean(row["page_range"]) or "",
                "question_count": 0,
                "questions": [],
            },
        )

        chapter_node["questions"].append(
            {
                "id": row["id"],
                "question": clean(row["question"]) or "",
                "question_type": clean(row["question_type"]) or "",
                "difficulty": clean(row["difficulty"]) or "",
                "subtopic": clean(row["subtopic"]) or "",
                "cognitive_level": clean(row["cognitive_level"]) or "",
                "learning_objective": clean(row["learning_objective"]) or "",
            }
        )
        for node in (chapter_node, book_node, sub_node, cls_node):
            node["question_count"] += 1

    # Collapse the OrderedDicts into sorted lists.
    out_classes = []
    for cls in sorted(classes, key=class_sort_key):
        cls_node = classes[cls]
        subjects = []
        for subject in sorted(cls_node["subjects"]):
            sub_node = cls_node["subjects"][subject]
            books = []
            for slug in sorted(sub_node["books"]):
                book_node = sub_node["books"][slug]
                chapters = sorted(
                    book_node["chapters"].values(),
                    key=lambda ch: (ch["chapter_number"] is None, ch["chapter_number"] or 0),
                )
                books.append({**book_node, "chapters": chapters})
            subjects.append({**sub_node, "books": books})
        out_classes.append({**cls_node, "subjects": subjects})

    total = sum(c["question_count"] for c in out_classes)
    return {"question_count": total, "classes": out_classes}


def build_index(tree: Dict[str, Any]) -> Dict[str, Any]:
    """Counts-only mirror of the tree -- useful for a quick sanity check."""
    return {
        "question_count": tree["question_count"],
        "classes": [
            {
                "class": c["class"],
                "question_count": c["question_count"],
                "subjects": [
                    {
                        "subject": s["subject"],
                        "question_count": s["question_count"],
                        "books": [
                            {
                                "book_slug": b["book_slug"],
                                "question_count": b["question_count"],
                                "chapters": [
                                    {
                                        "chapter_number": ch["chapter_number"],
                                        "chapter_name": ch["chapter_name"],
                                        "question_count": ch["question_count"],
                                    }
                                    for ch in b["chapters"]
                                ],
                            }
                            for b in s["books"]
                        ],
                    }
                    for s in c["subjects"]
                ],
            }
            for c in tree["classes"]
        ],
    }


def write_json(path: Path, payload: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default="exports/questions",
        help="output directory (default: exports/questions)",
    )
    parser.add_argument(
        "--class",
        dest="only_class",
        action="append",
        help="restrict to this class, e.g. --class 9 (repeatable)",
    )
    parser.add_argument(
        "--subject",
        dest="only_subject",
        action="append",
        help="restrict to this subject, e.g. --subject Physics (repeatable)",
    )
    parser.add_argument(
        "--include-duplicate-books",
        action="store_true",
        help=f"keep re-loaded duplicate slugs ({', '.join(sorted(DUPLICATE_BOOK_SLUGS))})",
    )
    parser.add_argument(
        "--keep-blank",
        action="store_true",
        help="keep rows whose question text is empty (dropped by default)",
    )
    args = parser.parse_args()

    print("Connecting to MySQL...")
    rows = fetch_rows()
    print(f"Fetched {len(rows)} question rows.")

    if not args.include_duplicate_books:
        before = len(rows)
        rows = [r for r in rows if r["book_slug"] not in DUPLICATE_BOOK_SLUGS]
        if before != len(rows):
            print(f"Skipped {before - len(rows)} rows from duplicate book slugs.")

    if not args.keep_blank:
        before = len(rows)
        rows = [r for r in rows if clean(r["question"])]
        if before != len(rows):
            print(f"Skipped {before - len(rows)} rows with empty question text.")

    if args.only_class:
        wanted = {c.strip() for c in args.only_class}
        rows = [r for r in rows if derive_attributes(r["book_slug"])["class"] in wanted]
    if args.only_subject:
        wanted = {s.strip().lower() for s in args.only_subject}
        rows = [
            r for r in rows if derive_attributes(r["book_slug"])["subject"].lower() in wanted
        ]

    if not rows:
        print("No rows matched the filters -- nothing written.")
        return 1

    tree = build_tree(rows)
    out_dir = Path(args.out_dir)

    combined = out_dir / "all_questions_by_class_subject.json"
    size = write_json(combined, tree)
    print(f"Wrote {combined} ({tree['question_count']} questions, {size / 1e6:.1f} MB)")

    write_json(out_dir / "index.json", build_index(tree))
    print(f"Wrote {out_dir / 'index.json'}")

    for cls in tree["classes"]:
        for subject in cls["subjects"]:
            name = f"class-{cls['class']}_{subject['subject']}.json".lower().replace(" ", "-")
            path = out_dir / "by-class-subject" / name
            write_json(
                path,
                {
                    "class": cls["class"],
                    "subject": subject["subject"],
                    "question_count": subject["question_count"],
                    "books": subject["books"],
                },
            )
            print(f"  {path}  ({subject['question_count']} questions)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
