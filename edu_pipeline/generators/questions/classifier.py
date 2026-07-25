#!/usr/bin/env python3
"""Classify textbook questions into standard question types (rule-based)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

# Canonical labels (exact strings for exports / DB).
QUESTION_TYPES = (
    "MCQ",
    "Assertion-Reason",
    "Numerical",
    "Conceptual",
    "Short Answer",
    "Long Answer",
    "Case Study",
    "Match the Following",
    "Fill in the Blanks",
    "True/False",
    "Diagram Based",
    "Formula Based",
    "HOTS",
    "Application Based",
    "Activity Based",
    "Practice Question",
    "Exercise Question",
    "Illustration Question",
)

SECTION_DEFAULT_TYPE = {
    "illustration": "Illustration Question",
    "example": "Illustration Question",
    "check_your_knowledge": "Practice Question",
    "textbook_exercise": "Exercise Question",
    "exercise": "Exercise Question",
}

_MCQ_RE = re.compile(
    r"\([abcd]\)|\([ABCD]\)|\boption\s+[abcd]\b|\boptions?\s*:\s*",
    re.IGNORECASE,
)
_NUMERIC_RE = re.compile(
    r"\b(find|calculate|compute|determine|evaluate|solve|how\s+(?:much|many|long|fast)|"
    r"what\s+is\s+the\s+(?:value|magnitude|speed|distance|force|resistance|current))\b",
    re.IGNORECASE,
)
_UNITS_RE = re.compile(
    r"\d+\s*(?:cm|mm|km|m\/s|m\s*s|kg|g|hz|w|v|a|°|ohm|Ω|mol|l\b|litre|second|min)\b",
    re.IGNORECASE,
)
_FORMULA_RE = re.compile(
    r"\b(formula|derive|derivation|using\s+the\s+(?:relation|equation|expression)|"
    r"prove\s+that|law\s+of)\b",
    re.IGNORECASE,
)
_DIAGRAM_RE = re.compile(
    r"\b(fig\.?|figure|diagram|image|graph|shown\s+in|refer\s+to\s+the\s+(?:fig|diagram)|"
    r"as\s+shown\s+below|in\s+the\s+given\s+figure)\b",
    re.IGNORECASE,
)
_CASE_STUDY_RE = re.compile(
    r"\b(case\s+study|read\s+the\s+passage|passage\s+based|based\s+on\s+the\s+(?:passage|paragraph)|"
    r"study\s+the\s+following\s+information)\b",
    re.IGNORECASE,
)
_ACTIVITY_RE = re.compile(
    r"\b(activity|experiment|practical|laboratory|lab\s+work|perform\s+the\s+experiment)\b",
    re.IGNORECASE,
)
_HOTS_RE = re.compile(
    r"\b(hots|higher\s+order|analyse\s+and|analyze\s+and|critically|evaluate\s+and|"
    r"justify\s+your|infer\s+from|synthesize)\b",
    re.IGNORECASE,
)
_APPLICATION_RE = re.compile(
    r"\b(real[\s-]?life|daily\s+life|practical\s+application|application\s+of|"
    r"in\s+everyday|situation\s+where)\b",
    re.IGNORECASE,
)
_CONCEPTUAL_RE = re.compile(
    r"\b(concept|principle|fundamental|understand|significance\s+of|importance\s+of|"
    r"state\s+the\s+law|what\s+do\s+you\s+mean)\b",
    re.IGNORECASE,
)


def _plain(text: str) -> str:
    """Strip HTML/MathML tags for pattern matching."""
    if not text:
        return ""
    t = re.sub(r"<[^>]+>", " ", text)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _first_sentence_start(text: str) -> str:
    plain = _plain(text)
    if not plain:
        return ""
    first = re.split(r"[.?!]\s+", plain, maxsplit=1)[0].strip().lower()
    return first


def classify_question(
    question: str,
    *,
    section_type: str = "",
    subsection: str = "",
) -> str:
    """
    Classify a single question using stakeholder rules (most specific first).
    """
    q = question or ""
    plain = _plain(q)
    combined = f"{subsection} {plain}".lower()
    start = _first_sentence_start(q)

    # 2. Assertion–Reason
    if "assertion" in combined and "reason" in combined:
        return "Assertion-Reason"

    # 1. MCQ
    if _MCQ_RE.search(plain):
        return "MCQ"

    # True/False
    if re.search(r"\btrue\s*/\s*false\b|\btrue\s+or\s+false\b", combined):
        return "True/False"

    # Match the Following
    if re.search(r"\bmatch\s+(?:the\s+)?following\b", combined):
        return "Match the Following"

    # Fill in the Blanks
    if re.search(
        r"\bfill\s+in\s+the\s+blanks?\b|\bcomplete\s+the\s+(?:sentence|statement)\b|____+",
        combined,
    ):
        return "Fill in the Blanks"

    # 6. Case Study
    if _CASE_STUDY_RE.search(combined):
        return "Case Study"

    # 7. Diagram Based
    if _DIAGRAM_RE.search(combined):
        return "Diagram Based"

    # 9. Activity Based
    if _ACTIVITY_RE.search(combined):
        return "Activity Based"

    # 8. Formula Based (before generic numerical when explicit)
    if _FORMULA_RE.search(combined):
        return "Formula Based"

    # 3. Numerical
    if _NUMERIC_RE.search(plain) or _UNITS_RE.search(plain):
        return "Numerical"
    if re.search(r"\d+\s*[\+\-\×\÷\=\^]", plain):
        return "Numerical"

    # 4. Short Answer
    if re.match(r"^(define|what\s+is|what\s+are|name\s+(?:the|any|two|three|four|five))",
                start):
        return "Short Answer"

    # 5. Long Answer
    if re.match(r"^(explain|describe|discuss|why)\b", start):
        return "Long Answer"

    # 11. HOTS
    if _HOTS_RE.search(combined):
        return "HOTS"

    # 12. Application Based
    if _APPLICATION_RE.search(combined):
        return "Application Based"

    # 10. Conceptual
    if _CONCEPTUAL_RE.search(combined):
        return "Conceptual"

    # Section-driven defaults (illustration / exercise / practice)
    section = (section_type or "").strip().lower()
    if section in SECTION_DEFAULT_TYPE:
        return SECTION_DEFAULT_TYPE[section]

    return "Exercise Question"


def classify_item(item: Dict[str, Any]) -> Dict[str, str]:
    """Return {"question": ..., "question_type": ...} for one row/item."""
    question = (
        item.get("question")
        or item.get("problem")
        or item.get("problem_markdown")
        or item.get("prompt_markdown")
        or item.get("prompt")
        or ""
    )
    qtype = classify_question(
        question,
        section_type=str(item.get("section_type") or item.get("source_type") or ""),
        subsection=str(item.get("title") or item.get("subsection_title") or ""),
    )
    return {"question": question, "question_type": qtype}


def classify_items(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    return [classify_item(it) for it in items]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Classify textbook questions")
    parser.add_argument("question", nargs="?", help="Single question text")
    parser.add_argument("--section-type", default="", help="e.g. exercise, illustration")
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Classify all qa_content_row rows (prints JSON array to stdout)",
    )
    parser.add_argument("--book-slug", default="", help="Filter DB rows by book_slug")
    parser.add_argument("--limit", type=int, default=0, help="Max rows from DB")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="With --from-db, print type counts instead of full JSON",
    )
    parser.add_argument(
        "--backfill-db",
        action="store_true",
        help="UPDATE qa_content_row.question_type for all rows (uses section_type when re-reading JSON is unavailable)",
    )
    args = parser.parse_args()

    if args.backfill_db:
        import pymysql
        from pymysql.cursors import DictCursor

        from topicwise_pipeline import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset="utf8mb4",
            cursorclass=DictCursor,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, question FROM qa_content_row ORDER BY id"
                )
                rows = cur.fetchall()
                updated = 0
                for row in rows:
                    qtype = classify_question(row.get("question") or "")
                    cur.execute(
                        "UPDATE qa_content_row SET question_type = %s WHERE id = %s",
                        (qtype, row["id"]),
                    )
                    updated += 1
                conn.commit()
        finally:
            conn.close()
        print(json.dumps({"updated": updated}, ensure_ascii=False))
        return

    if args.from_db:
        import pymysql
        from pymysql.cursors import DictCursor

        from topicwise_pipeline import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

        sql = "SELECT id, question, book_slug FROM qa_content_row"
        params: List[Any] = []
        if args.book_slug:
            sql += " WHERE book_slug = %s"
            params.append(args.book_slug)
        sql += " ORDER BY id"
        if args.limit > 0:
            sql += " LIMIT %s"
            params.append(args.limit)

        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset="utf8mb4",
            cursorclass=DictCursor,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()

        out = [
            {
                "id": r["id"],
                "question": r["question"],
                "question_type": classify_question(r["question"] or ""),
            }
            for r in rows
        ]
        if args.summary:
            counts: Dict[str, int] = {}
            for row in out:
                counts[row["question_type"]] = counts.get(row["question_type"], 0) + 1
            print(json.dumps({"total": len(out), "by_type": counts}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(out, ensure_ascii=False))
        return

    if not args.question:
        parser.error("Provide question text or use --from-db")

    result = classify_question(args.question, section_type=args.section_type)
    print(json.dumps({"question": args.question, "question_type": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
