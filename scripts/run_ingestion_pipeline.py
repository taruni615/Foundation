#!/usr/bin/env python3
"""CLI Entry Point — Pipeline 1: Ingestion & Storage.

Full workflow:
    PDF -> Mathpix OCR -> Topic Extractor -> *_final.json -> MySQL Load -> Metadata Tagging

Examples:
    python scripts/run_ingestion_pipeline.py "edu_pipeline/materials/input/10 PHYSICS FOUNDATION.pdf"
    python scripts/run_ingestion_pipeline.py "10 PHYSICS FOUNDATION" --skip-db
    python scripts/run_ingestion_pipeline.py "edu_pipeline/materials/input/10 PHYSICS FOUNDATION.pdf" --replace-book --with-images
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make repository root importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edu_pipeline.shared.paths import PROJECT_ROOT, load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from edu_pipeline.workflow import run_ingestion_pipeline


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_ingestion_pipeline",
        description="Pipeline 1: Ingest textbook PDF, normalize content, load into MySQL, and tag metadata.",
    )
    parser.add_argument("pdf_or_slug", help="Path to PDF file or existing book slug")
    parser.add_argument(
        "--extract-mode",
        choices=["all", "theory_only", "questions_only"],
        default="all",
        help="Mode: 'all' (default), 'theory_only' (theory + images), or 'questions_only' (questions + solutions)",
    )
    parser.add_argument("--theory-only", action="store_true", help="Shortcut for --extract-mode theory_only")
    parser.add_argument("--questions-only", action="store_true", help="Shortcut for --extract-mode questions_only")
    parser.add_argument("--skip-db", action="store_true", help="Skip loading data into MySQL database")
    parser.add_argument("--skip-tagging", action="store_true", help="Skip backfilling question metadata tags")
    parser.add_argument("--no-images", action="store_true", help="Disable extracting images from PDF")
    parser.add_argument("--replace-book", action="store_true", help="Overwrite existing book data in MySQL")

    args = parser.parse_args(argv)

    extract_mode = args.extract_mode
    if args.theory_only:
        extract_mode = "theory_only"
    elif args.questions_only:
        extract_mode = "questions_only"

    print(f"=== Starting Ingestion Pipeline: {args.pdf_or_slug} (Mode: {extract_mode}) ===")
    res = run_ingestion_pipeline(
        args.pdf_or_slug,
        extract_mode=extract_mode,
        store_db=not args.skip_db,
        tag_questions=not args.skip_tagging,
        with_images=not args.no_images,
        replace_book=args.replace_book,
    )

    print(f"\n=== Ingestion Pipeline Completed ===")
    print(f"Book Slug    : {res.get('book_slug')}")
    print(f"Extract Mode : {res.get('extract_mode')}")
    print(f"DB Stored    : {res.get('db_stored')}")
    print(f"Tagged       : {res.get('tagged')}")

    if res.get("insert_stats"):
        print("Insert Stats:", res["insert_stats"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
