#!/usr/bin/env python3
"""CLI entry point: refresh_qa_question_types."""

import sys
from pathlib import Path

# Entry points live in scripts/; make the repository root importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edu_pipeline.storage.refresh_types import *
from edu_pipeline.storage.refresh_types import main

if __name__ == "__main__":
    main()
