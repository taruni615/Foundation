#!/usr/bin/env python3
"""Constants shared across pipeline layers."""

from __future__ import annotations

# Keys under ``topics[]`` in a v3.1 ``*_final.json`` that hold question items.
# Previously duplicated verbatim in repository/service.py, storage/export_qa.py
# and ai/services/mcq_service.py.
QA_SECTION_KEYS = (
    "illustrations",
    "check_your_knowledge_items",
    "textbook_exercises",
    "exercises",
    "examples",
)
