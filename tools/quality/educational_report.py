#!/usr/bin/env python3
"""Educational quality report.

Scores extracted books and the question bank against the metrics defined in
``edu_pipeline.ai.services.educational_metrics``. Read-only and offline (the
bank section is skipped when MySQL is unavailable).

Usage (from the repository root)::

    python tools/quality/educational_report.py                  # every book
    python tools/quality/educational_report.py --book "10 PHYSICS FOUNDATION"
    python tools/quality/educational_report.py --json report.json
    python tools/quality/educational_report.py --no-bank
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from edu_pipeline.ai.services.educational_metrics import (  # noqa: E402
    notes_metrics,
    question_metrics,
    summarise,
)
from edu_pipeline.repository import RepositoryService  # noqa: E402


def _rule(title: str) -> None:
    print(f"\n{title}\n{'=' * len(title)}")


def _row(label: str, value: object) -> None:
    print(f"  {label:<32} {value}")


def report_book(slug: str) -> dict:
    repo = RepositoryService.load(slug)
    metrics = notes_metrics(repo.raw_json)
    questions = RepositoryService.get_questions(repo)
    metrics.update(question_metrics(questions))

    _rule(f"{slug}  ({metrics['topics']} topics, {metrics.get('questions', 0)} questions)")
    _row("theory coverage", f"{metrics['theory_coverage_pct']}%")
    _row("notes coverage", f"{metrics['notes_coverage_pct']}%")
    _row("enrichment coverage", f"{metrics['enrichment_coverage_pct']}%")
    if metrics["formula_count"]:
        _row("formula coverage", f"{metrics['formula_coverage_pct']}% of {metrics['formula_count']}")
    _row("prerequisite completeness", f"{metrics['prerequisite_completeness_pct']}%")
    _row("revision density", f"{metrics['revision_density_pct']}%")
    _row("mean contamination", metrics["mean_contamination"])
    _row("mean study time", f"{metrics['mean_study_minutes']} min")
    _row("subject(s) detected", ", ".join(metrics["subject_distribution"]) or "-")
    if metrics.get("questions"):
        _row("unique stems", f"{metrics['unique_stem_pct']}%")
        _row("question types", metrics["type_diversity"])
        _row("chapter balance", metrics["chapter_balance"])
        _row("substantial answers", f"{metrics['explanation_adequate_pct']}%")
        _row("stems embedding options", f"{metrics['stem_embeds_options_pct']}%")

    findings = summarise(metrics)
    if findings:
        print("\n  findings:")
        for f in findings:
            print(f"    - {f}")
    return metrics


def report_bank() -> dict:
    try:
        import edu_pipeline.storage.database as database

        with database._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT question, answer, question_type, chapter_name FROM qa_content_row"
                )
                rows = list(cur.fetchall())
    except Exception as exc:
        print(f"\n(question bank skipped: {exc})")
        return {}

    metrics = question_metrics(rows)
    _rule(f"Question bank ({metrics['questions']} rows in MySQL)")
    _row("unique stems", f"{metrics['unique_stem_pct']}%")
    _row("duplicate stems", f"{metrics['duplicate_pct']}%")
    _row("question types", metrics["type_diversity"])
    _row("chapters covered", metrics["chapter_coverage"])
    _row("chapter balance", metrics["chapter_balance"])
    _row("substantial answers", f"{metrics['explanation_adequate_pct']}%")
    _row("missing answers", f"{metrics['explanation_missing_pct']}%")
    _row("stems embedding options", f"{metrics['stem_embeds_options_pct']}%")
    print("\n  type distribution:")
    for qtype, count in list(metrics["type_distribution"].items())[:10]:
        print(f"    {qtype:<26} {count:>6} ({count / metrics['questions'] * 100:>4.1f}%)")

    findings = summarise(metrics)
    if findings:
        print("\n  findings:")
        for f in findings:
            print(f"    - {f}")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Educational quality report")
    parser.add_argument("--book", default=None, help="Report on a single book slug")
    parser.add_argument("--json", default=None, help="Also write the metrics to this JSON file")
    parser.add_argument("--no-bank", action="store_true", help="Skip the MySQL question bank")
    args = parser.parse_args()

    books = [args.book] if args.book else RepositoryService.list_books()
    if not books:
        print("No extracted books found.")
        return

    payload = {"books": {}, "bank": {}}
    for slug in books:
        try:
            payload["books"][slug] = report_book(slug)
        except Exception as exc:
            print(f"\n{slug}: could not report ({exc})")

    if not args.no_bank:
        payload["bank"] = report_bank()

    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    main()
