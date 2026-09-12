#!/usr/bin/env python3
"""Rebuild the review sidecars from an existing *_final.json.

Usage:
    python scripts/rebuild_sidecars.py "outputs/<book>/<book>_final.json"
    python scripts/rebuild_sidecars.py outputs/*/*_final.json

`<book>_questions.json` and `<book>_theory.json` are derived views of
`<book>_final.json`, so a change on the *export* side -- the question sanitiser,
option parsing, figure resolution -- does not need the book re-extracted from
OCR. This regenerates just those two files, and runs the quality checks on the
result.

A change to *extraction* (parsing, chapter boundaries, headings) is a different
matter: bump `TOPIC_CACHE_VERSION` and re-run the pipeline instead.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edu_pipeline.extraction.quality import report_questions_file
from edu_pipeline.extraction.topic_extractor import (
    save_questions_json_sidecar,
    save_theory_json_sidecar,
)


def rebuild(final_path: str) -> bool:
    """Rewrite both sidecars for one book. True when the checks all pass."""
    with open(final_path, "r", encoding="utf-8") as handle:
        document = json.load(handle)
    if not document or not document.get("topics"):
        print(f"  Skipping {final_path}: no topics in the document")
        return True

    book = Path(final_path).name.replace("_final.json", "")
    questions_path = final_path.replace("_final.json", "_questions.json")
    theory_path = final_path.replace("_final.json", "_theory.json")

    save_theory_json_sidecar(document, book, theory_path)
    save_questions_json_sidecar(document, book, questions_path)
    findings = report_questions_file(questions_path, book)
    return not any(f.severity == "fail" for f in findings)


def main(argv=None) -> int:
    paths = list(argv if argv is not None else sys.argv[1:])
    if "-h" in paths or "--help" in paths:
        print(__doc__)
        return 0
    if not paths:
        print(__doc__)
        return 2
    ok = True
    for path in paths:
        print(f"=== {path}")
        ok = rebuild(path) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
