#!/usr/bin/env python3
"""JSON helpers shared by the AI domain services.

Consolidates the identical ``_parse_json`` implementations that previously lived
in ``ai/services/notes_service.py`` and ``ai/services/mcq_service.py``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Parse an LLM response into a dict, tolerating surrounding prose.

    Tries a strict ``json.loads`` first, then falls back to the outermost
    ``{...}`` span in the text. Returns ``None`` when nothing parses.
    """
    text_clean = text.strip()
    try:
        return json.loads(text_clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text_clean, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return None
