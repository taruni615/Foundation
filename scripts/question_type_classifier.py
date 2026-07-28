#!/usr/bin/env python3
"""CLI entry point: question_type_classifier."""

import sys
from pathlib import Path

# Entry points live in scripts/; make the repository root importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edu_pipeline.generators.questions.classifier import *
from edu_pipeline.generators.questions.classifier import main

if __name__ == "__main__":
    main()
