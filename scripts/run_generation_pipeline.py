#!/usr/bin/env python3
"""CLI Entry Point — Pipeline 2: Generation & Conversion.

Full workflow:
    MySQL / Repository -> Theory-to-MCQ Conversion -> MCQ Similarity -> Short Notes

Examples:
    python scripts/run_generation_pipeline.py "10 PHYSICS FOUNDATION"
    python scripts/run_generation_pipeline.py "10 PHYSICS FOUNDATION" --modes convert,notes
    python scripts/run_generation_pipeline.py "10 PHYSICS FOUNDATION" --mcq-limit 50
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make repository root importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edu_pipeline.shared.paths import PROJECT_ROOT, load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from edu_pipeline.workflow import run_generation_pipeline


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_generation_pipeline",
        description="Pipeline 2: Run downstream generation & conversion (MCQs, notes) directly from DB/Repository.",
    )
    parser.add_argument("book_slug", help="Book slug or name in MySQL / Repository")
    parser.add_argument(
        "--modes",
        default="convert,similar,notes",
        help="Comma-separated modes: convert, similar, notes (default: convert,similar,notes)",
    )
    parser.add_argument("--mcq-limit", type=int, default=20, help="Max theory questions to convert to MCQs")
    parser.add_argument("--similar-limit", type=int, default=20, help="Max source MCQs to generate variants for")
    parser.add_argument("--out-dir", default=None, help="Custom output directory for notes/generated JSONs")

    args = parser.parse_args(argv)

    raw_modes = [m.strip().lower() for m in args.modes.split(",") if m.strip()]
    mode_map = {"convert": "convert_mcqs", "similar": "similar_mcqs", "notes": "notes"}
    selected_modes = [mode_map.get(m, m) for m in raw_modes]

    print(f"=== Starting Generation Pipeline: {args.book_slug} ===")
    print(f"Modes: {selected_modes}")

    res = run_generation_pipeline(
        args.book_slug,
        modes=selected_modes,
        mcq_limit=args.mcq_limit,
        similar_limit=args.similar_limit,
        out_dir=args.out_dir,
    )

    print(f"\n=== Generation Pipeline Completed ===")
    for mode, out in res.get("outputs", {}).items():
        print(f"[{mode}]:", json.dumps(out, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
