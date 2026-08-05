#!/usr/bin/env python3
"""Backfill the PRD tagging columns on the question bank.

    python scripts/tag_questions.py --coverage
    python scripts/tag_questions.py --limit 200 --dry-run
    python scripts/tag_questions.py                       # tag everything untagged
    python scripts/tag_questions.py --book "10 PHYSICS FOUNDATION" --retag

Requires ``schema/add_question_tagging_columns.sql`` to have been applied.
Thin wrapper over ``edu_pipeline.storage.tagging``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edu_pipeline.shared.paths import PROJECT_ROOT, load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from edu_pipeline.storage import tagging  # noqa: E402


def _print_coverage(cov: dict) -> None:
    print(f"Total rows      : {cov['total']:,}")
    print(f"Tagged          : {cov['tagged']:,}  ({cov['pct_tagged']}%)")
    print(f"Untagged        : {cov['untagged']:,}")
    print(f"With subtopic   : {cov['with_subtopic']:,}")
    print("By difficulty   :", ", ".join(f"{k}={v:,}" for k, v in cov["by_difficulty"].items()))
    print("By Bloom level  :", ", ".join(f"{k}={v:,}" for k, v in cov["by_cognitive_level"].items()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", default="", help="restrict to one book_slug")
    ap.add_argument("--limit", type=int, default=None, help="cap rows updated")
    ap.add_argument("--retag", action="store_true", help="re-tag rows that already carry tags")
    ap.add_argument("--dry-run", action="store_true", help="compute tags without writing")
    ap.add_argument("--coverage", action="store_true", help="report tag coverage and exit")
    ap.add_argument("--json", default="", help="also write the run stats to this path")
    args = ap.parse_args(argv)

    if args.coverage:
        _print_coverage(tagging.coverage(args.book))
        return 0

    seen = {"n": 0}

    def progress(chapter_id, updated, total):
        seen["n"] += 1
        if seen["n"] % 10 == 0 or updated == 0:
            print(f"  ... {seen['n']} chapters, {total:,} rows tagged", flush=True)

    stats = tagging.backfill(
        book_slug=args.book,
        only_untagged=not args.retag,
        limit=args.limit,
        dry_run=args.dry_run,
        progress=progress,
    )

    print()
    print("Chapters processed:", stats["chapters"])
    print("Rows read         :", f"{stats['rows_read']:,}")
    print("Rows updated      :", f"{stats['rows_updated']:,}" + ("  (dry run)" if args.dry_run else ""))
    print("With subtopic     :", f"{stats['with_subtopic']:,}")
    print("By difficulty     :", ", ".join(f"{k}={v:,}" for k, v in sorted(stats["by_difficulty"].items())))
    print("By Bloom level    :", ", ".join(f"{k}={v:,}" for k, v in sorted(stats["by_cognitive_level"].items())))

    if args.json:
        Path(args.json).write_text(json.dumps(stats, indent=2), encoding="utf-8")
        print("\nWrote", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
