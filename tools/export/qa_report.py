"""Audit the exported question bank against the 16 QA categories.

Runs over ``exports/questions/flat/all_questions_flat.json`` and reports what
is still wrong after the export pipeline's automatic corrections. Writes a
machine-readable ``exports/questions/qa_report.json`` (every offending
question_id, grouped by issue) and prints a summary.

The checks are deliberately split into what a rule engine can *decide* and what
it can only *flag*. Verifying that a marked answer is mathematically correct,
or that an explanation is not hallucinated, requires solving each question --
that is an LLM job, not a regex job, and is reported as "not machine-checkable"
rather than silently passed.

Usage::

    python tools/export/qa_report.py
    python tools/export/qa_report.py --limit-ids 20
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.append(str(Path(__file__).resolve().parents[2]))

DEFAULT_IN = "exports/questions/flat/all_questions_flat.json"
DEFAULT_OUT = "exports/questions/qa_report.json"

BACKSLASH = chr(92)
_LATEX = re.compile(re.escape(BACKSLASH) + r"(?:hline|frac|begin|end|longdiv|quad|cline|textbf)")
_OCR_CHARS = {"�": "U+FFFD replacement char", "◻": "U+25FB placeholder square"}
_MATH_TAG = re.compile(r"<math[^>]*>.*?</math>", re.S)
_TABLE_TAG = re.compile(r"<table.*?</table>", re.S)


def plain(text: str) -> str:
    text = _MATH_TAG.sub(" M ", text or "")
    text = _TABLE_TAG.sub(" T ", text)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def audit(rows: List[Dict[str, Any]]) -> "OrderedDict[str, Dict[str, Any]]":
    issues: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    def record(category: str, name: str, ids: List[Any], note: str = "") -> None:
        issues.setdefault(category, {})[name] = {"count": len(ids), "ids": ids, "note": note}

    with_options = [r for r in rows if r.get("options")]

    # 1. Answer validation ---------------------------------------------------
    record("1. answers", "answer id not among the options",
           [r["question_id"] for r in with_options
            if r.get("answer") and r["answer"] not in [o["id"] for o in r["options"]]])
    record("1. answers", "options present but no answer key",
           [r["question_id"] for r in with_options if not r.get("answer")],
           "bank's answer column was misaligned or absent for these rows")
    record("1. answers", "answer correctness vs the maths", [],
           "NOT machine-checkable: needs each question solved (LLM pass)")

    # 2. Explanation validation ---------------------------------------------
    record("2. explanations", "missing explanation",
           [r["question_id"] for r in rows if not r.get("explanation")])
    dup_expl = defaultdict(list)
    for row in rows:
        if row.get("explanation"):
            dup_expl[row["explanation"].strip()].append(row["question_id"])
    record("2. explanations", "explanation reused across questions",
           [i for v in dup_expl.values() if len(v) > 1 for i in v[1:]])
    record("2. explanations", "explanation contradicts the answer", [],
           "NOT machine-checkable: needs semantic comparison (LLM pass)")

    # 3. Duplicate content ---------------------------------------------------
    seen = defaultdict(list)
    for row in rows:
        seen[re.sub(r"\s+", " ", row.get("question", "")).strip()].append(row)
    record("3. duplicates", "same question text repeated",
           [r["question_id"] for v in seen.values() if len(v) > 1 for r in v[1:]],
           "survivors are in different chapters; same-chapter pairs were removed")

    # 4. Question type -------------------------------------------------------
    record("4. question types", "typed MCQ but has no options",
           [r["question_id"] for r in rows
            if r.get("question_type") == "MCQ" and not r.get("options")],
           "source row lost its option list during extraction")
    record("4. question types", "still typed Numerical (not converted to MCQ)",
           [r["question_id"] for r in rows if r.get("question_type") == "Numerical"])

    # 5. Options -------------------------------------------------------------
    record("5. options", "duplicate option text",
           [r["question_id"] for r in with_options
            if len({o["text"].strip() for o in r["options"]}) != len(r["options"])])
    record("5. options", "empty option text",
           [r["question_id"] for r in with_options
            if any(not o["text"].strip() for o in r["options"])])
    record("5. options", "option ids not sequential from A",
           [r["question_id"] for r in with_options
            if [o["id"] for o in r["options"]] != ["A", "B", "C", "D", "E"][: len(r["options"])]])
    record("5. options", "fewer than 4 options",
           [r["question_id"] for r in with_options if len(r["options"]) < 4])

    # 6/7. Maths and LaTeX ---------------------------------------------------
    record("6. maths / latex", "raw LaTeX left in the text",
           [r["question_id"] for r in rows if _LATEX.search(r.get("question", ""))])
    record("6. maths / latex", "escaped MathML (renders as markup, fixed in PDF)",
           [r["question_id"] for r in rows if "&lt;math" in r.get("question", "")],
           "PDF renderer decodes these; JSON keeps the source bytes")
    record("6. maths / latex", "unbalanced <math> tags",
           [r["question_id"] for r in rows
            if r.get("question", "").count("<math") != r.get("question", "").count("</math")])

    # 8. OCR artefacts -------------------------------------------------------
    for char, label in _OCR_CHARS.items():
        record("8. ocr", label,
               [r["question_id"] for r in rows if char in r.get("question", "")])
    record("8. ocr", "markdown '##' heading left in the question",
           [r["question_id"] for r in rows if "##" in r.get("question", "")])
    record("8. ocr", "inline SOLUTION block left in the question",
           [r["question_id"] for r in rows
            if re.search(r"\bSOLUTION\s*:", r.get("question", ""), re.I)])

    # 9. Tables --------------------------------------------------------------
    record("9. tables", "unbalanced <table> tags",
           [r["question_id"] for r in rows
            if r.get("question", "").count("<table") != r.get("question", "").count("</table")])

    # 10. Diagrams -----------------------------------------------------------
    record("10. diagrams", "refers to a figure that is not embedded",
           [r["question_id"] for r in rows
            if re.search(r"\b(?:fig|figure|diagram)\b\s*[.:]?\s*\d", plain(r.get("question", "")), re.I)
            and "<img" not in r.get("question", "")],
           "source PDFs were OCR'd to text; images were never carried across")

    # 11/14. Formatting and numbering ----------------------------------------
    record("11. formatting", "question longer than 3000 characters",
           [r["question_id"] for r in rows if len(r.get("question", "")) > 3000],
           "residual absorbed content the trimmer could not bound safely")
    ids = [r.get("question_id") for r in rows]
    record("14. numbering", "duplicate question_id",
           [i for i, n in Counter(ids).items() if n > 1])

    # 12. Theory leakage -----------------------------------------------------
    record("12. theory leakage", "question opens with a definition/note marker",
           [r["question_id"] for r in rows
            if re.match(r"^\s*(?:NOTE|DEFINITION|REMARK|EXAMPLE)\s*[:.]",
                        plain(r.get("question", "")), re.I)])

    # 13. Structure ----------------------------------------------------------
    record("13. structure", "missing class / subject / chapter",
           [r["question_id"] for r in rows
            if not (r.get("class") and r.get("subject") and r.get("chapter"))])
    record("13. structure", "topic falls back to the chapter name",
           [r["question_id"] for r in rows
            if (r.get("topic") or "").strip().lower() == (r.get("chapter") or "").strip().lower()],
           "no trustworthy sub-topic heading existed for these rows")

    # 15. Units --------------------------------------------------------------
    record("15. units", "number and unit split by a stray space or dot",
           [r["question_id"] for r in rows
            if re.search(r"\d\s+\.\s*\d|\d\s{2,}(?:cm|mm|km|kg|g|ml|l|m)\b",
                         plain(r.get("question", "")), re.I)])

    # 16. Generated content --------------------------------------------------
    record("16. generated", "options generated by the LLM (Numerical -> MCQ)",
           [r["question_id"] for r in rows if r.get("converted_from") == "Numerical"],
           "each accepted only when two independent solves agreed")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", default=DEFAULT_IN)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--limit-ids", type=int, default=50,
                        help="how many example ids to store per issue")
    args = parser.parse_args()

    with open(args.src, encoding="utf-8") as handle:
        data = json.load(handle)
    rows = data["questions"] if isinstance(data, dict) else data

    issues = audit(rows)
    total = 0
    print(f"Audited {len(rows)} questions from {args.src}\n")
    for category, checks in issues.items():
        print(category.upper())
        for name, info in checks.items():
            flag = "  ok " if info["count"] == 0 else "  !! "
            note = f"   [{info['note']}]" if info["note"] else ""
            print(f"{flag}{info['count']:6d}  {name}{note}")
            total += info["count"]
        print()
    print(f"Total flagged rows across all checks: {total}")

    payload = OrderedDict([
        ("source", args.src),
        ("questions_audited", len(rows)),
        ("issues", OrderedDict(
            (category, OrderedDict(
                (name, OrderedDict([
                    ("count", info["count"]),
                    ("note", info["note"]),
                    ("example_question_ids", info["ids"][: args.limit_ids]),
                ]))
                for name, info in checks.items()))
            for category, checks in issues.items())),
    ])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
