#!/usr/bin/env python3
"""Check an extracted book for the faults that pass silently.

    python scripts/check_extraction_quality.py "outputs/<book>/<book>_questions.json"
    python scripts/check_extraction_quality.py outputs/*/*_questions.json

Exits non-zero when any book fails, so a batch can be gated on it. The same
checks run automatically at the end of every extraction.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edu_pipeline.extraction.quality import main

if __name__ == "__main__":
    raise SystemExit(main())
