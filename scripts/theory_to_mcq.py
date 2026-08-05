#!/usr/bin/env python3
"""CLI: convert theory questions in outputs/subjectwise_json/ into MCQs.

    python scripts/theory_to_mcq.py --triage                 # report only, no LLM
    python scripts/theory_to_mcq.py --subject Physics --limit 50
    python scripts/theory_to_mcq.py --workers 6              # everything

Writes, per subject, into ``outputs/mcq_from_theory/``:
    <Subject>_mcqs.json        the delivery payload (valid JSON array)
    <Subject>_raw.jsonl        resumable per-row log, successes and failures
    _triage_report.json        why every non-converted row was left out
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from edu_pipeline.shared.paths import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from edu_pipeline.generators.questions import theory_mcq_batch as batch  # noqa: E402

IN_DIR = REPO_ROOT / "outputs" / "subjectwise_json"
CLASS_DIR = REPO_ROOT / "outputs" / "classwise_json"
OUT_DIR = REPO_ROOT / "outputs" / "mcq_from_theory"


def collect(subjects, class_map, limit=0):
    """Gather (row, subject, class) triples plus a triage tally."""
    convertible, rejected = [], []
    tally = Counter()
    for subject in subjects:
        path = IN_DIR / f"{subject}_questions.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        theory = list(batch.iter_theory_rows(rows))
        tally[f"{subject}:total"] = len(rows)
        tally[f"{subject}:already_mcq"] = len(rows) - len(theory)
        taken = 0
        for row in theory:
            status, reason = batch.triage(row)
            if status == batch.REJECT:
                tally[f"{subject}:reject:{reason}"] += 1
                rejected.append({
                    "question_id": row.get("id"), "subject": subject,
                    "chapter": row.get("title"), "reason": reason,
                    "question_excerpt": (row.get("question") or "")[:160],
                })
                continue
            if status == batch.CONVERTIBLE_NO_ANSWER:
                tally[f"{subject}:convertible_answer_inferred:{reason}"] += 1
            if limit and taken >= limit:
                tally[f"{subject}:deferred_by_limit"] += 1
                continue
            convertible.append((row, subject, class_map.get(row.get("id"), "")))
            taken += 1
    return convertible, rejected, tally


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--subject", action="append", choices=batch.SUBJECTS,
                        help="restrict to one subject (repeatable)")
    parser.add_argument("--limit", type=int, default=0, help="max conversions per subject")
    parser.add_argument("--workers", type=int, default=4, help="concurrent Ollama calls")
    parser.add_argument("--model", default="", help="override OLLAMA_MODEL")
    parser.add_argument("--triage", action="store_true", help="report only, no LLM calls")
    args = parser.parse_args()

    subjects = args.subject or list(batch.SUBJECTS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    class_map = batch.load_class_map(CLASS_DIR)
    convertible, rejected, tally = collect(subjects, class_map, args.limit)

    (OUT_DIR / "_triage_report.json").write_text(
        json.dumps({"summary": dict(sorted(tally.items())),
                    "convertible": len(convertible),
                    "rejected": rejected}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    print(f"theory rows convertible: {len(convertible)}   rejected: {len(rejected)}")
    for key in sorted(tally):
        if ":reject:" in key or key.endswith(("total", "already_mcq")):
            print(f"  {key:58} {tally[key]}")
    if args.triage:
        print(f"\ntriage report -> {OUT_DIR / '_triage_report.json'}")
        return 0

    for subject in subjects:
        todo = [t for t in convertible if t[1] == subject]
        if not todo:
            continue
        raw_path = OUT_DIR / f"{subject}_raw.jsonl"
        print(f"\n[{subject}] converting {len(todo)} questions "
              f"({args.workers} workers, model={args.model or batch.OLLAMA_MODEL})")
        stats = batch.run_batch(todo, raw_path, workers=args.workers, model=args.model)
        print(f"[{subject}] {stats}")

        records, errors = [], []
        with raw_path.open(encoding="utf-8") as handle:
            for line in handle:
                rec = json.loads(line)
                (errors if rec.get("error") else records).append(rec)
        (OUT_DIR / f"{subject}_mcqs.json").write_text(
            json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        if errors:
            (OUT_DIR / f"{subject}_failures.json").write_text(
                json.dumps(errors, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[{subject}] wrote {len(records)} MCQs, {len(errors)} failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
