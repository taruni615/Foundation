#!/usr/bin/env python3
"""Independent QA gate for the MCQs produced by scripts/theory_to_mcq.py.

Re-checks every delivered record against the acceptance checklist, without
reusing the generator's own validator, so a bug in the generator cannot pass
itself. Reports per-subject counts and writes offending records to
``outputs/mcq_from_theory/_verification_report.json``.

    python scripts/verify_mcqs.py
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "outputs" / "mcq_from_theory"

REQUIRED = ("question_id", "subject", "chapter", "topic", "question", "question_type",
            "options", "correct_option", "correct_answer", "explanation",
            "difficulty", "blooms_level", "source_type", "tags")

BLOOM = {"Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"}
DIFFICULTY = {"Easy", "Moderate", "Difficult", "Medium", "Hard"}
BANNED = re.compile(r"\b(all|none) of the (above|these)\b|\bboth [a-d] and [a-d]\b", re.I)
MATH_RE = re.compile(r"<math\b.*?</math>", re.S)
TOKEN_RE = re.compile(r"<<M\d+>>")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w<>]+", " ", str(text).lower())).strip()


def check(rec: dict) -> list:
    """Return a list of problems with one record ("" == clean)."""
    bad = []
    for key in REQUIRED:
        if key not in rec:
            bad.append(f"missing_field:{key}")
    if bad:
        return bad

    if rec["question_type"] != "MCQ":
        bad.append("question_type_not_MCQ")
    if rec["source_type"] != "Converted from Theory":
        bad.append("wrong_source_type")
    if not str(rec["question"]).strip():
        bad.append("empty_question")

    opts = rec["options"]
    if not isinstance(opts, dict) or set(opts) != set("ABCD"):
        bad.append("options_not_ABCD")
        return bad
    if any(not str(v).strip() for v in opts.values()):
        bad.append("blank_option")
    if len({norm(v) for v in opts.values()}) != 4:
        bad.append("duplicate_options")
    if any(BANNED.search(str(v)) for v in opts.values()):
        bad.append("banned_option_text")

    lengths = [len(str(v)) for v in opts.values()]
    if max(lengths) > 4 * max(min(lengths), 1) and min(lengths) < 30:
        bad.append("unbalanced_option_lengths")

    if rec["correct_option"] not in opts:
        bad.append("correct_option_not_a_key")
    elif norm(rec["correct_answer"]) != norm(opts[rec["correct_option"]]):
        bad.append("correct_answer_mismatch")

    if len(str(rec["explanation"]).strip()) < 20:
        bad.append("explanation_too_short")
    if rec["blooms_level"] not in BLOOM:
        bad.append("bad_blooms_level")
    if rec["difficulty"] not in DIFFICULTY:
        bad.append("bad_difficulty")
    if not isinstance(rec["tags"], list) or not rec["tags"]:
        bad.append("empty_tags")

    # Placeholders must never leak into delivered text.
    surfaces = [rec["question"], rec["explanation"], *map(str, opts.values())]
    if any(TOKEN_RE.search(s) for s in surfaces):
        bad.append("unrestored_placeholder")

    # Every MathML expression in the stem must be byte-identical to one in the
    # source question or answer -- proof that no formula was rewritten.
    meta = rec.get("metadata") or {}
    source_math = set(MATH_RE.findall(meta.get("original_question", "")
                                      + meta.get("original_answer", "")))
    for expr in MATH_RE.findall(" ".join(surfaces)):
        if expr not in source_math:
            bad.append("altered_mathml")
            break
    return bad


def main() -> int:
    files = sorted(OUT_DIR.glob("*_mcqs.json"))
    if not files:
        print(f"no MCQ files in {OUT_DIR}")
        return 1

    problems, totals = [], Counter()
    seen_ids = set()
    for path in files:
        records = json.loads(path.read_text(encoding="utf-8"))
        subject = path.stem.replace("_mcqs", "")
        clean = 0
        for rec in records:
            issues = check(rec)
            rid = rec.get("question_id")
            if rid in seen_ids:
                issues.append("duplicate_question_id")
            seen_ids.add(rid)
            if issues:
                for issue in issues:
                    totals[issue] += 1
                problems.append({"question_id": rid, "subject": subject, "issues": issues})
            else:
                clean += 1
        totals[f"{subject}:clean"] = clean
        totals[f"{subject}:total"] = len(records)
        inferred = sum(1 for r in records
                       if (r.get("metadata") or {}).get("answer_source") == "inferred")
        totals[f"{subject}:answer_inferred"] = inferred
        print(f"{subject:12} {clean}/{len(records)} clean   ({inferred} answer-inferred)")

    print("\nissues:")
    for key, count in sorted(totals.items()):
        if ":" not in key:
            print(f"  {key:32} {count}")
    if not any(":" not in k for k in totals):
        print("  none")

    (OUT_DIR / "_verification_report.json").write_text(
        json.dumps({"totals": dict(sorted(totals.items())), "problems": problems},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport -> {OUT_DIR / '_verification_report.json'}")
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
