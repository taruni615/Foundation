#!/usr/bin/env python3
"""CLI entry point: topicwise_pipeline."""

import sys
from pathlib import Path

# Entry points live in scripts/; make the repository root importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edu_pipeline.extraction.topic_extractor import *
from edu_pipeline.extraction.topic_extractor import main

if __name__ == "__main__":
    main()
