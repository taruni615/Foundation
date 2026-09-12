"""Common extraction helpers for book slug parsing and attribute inference."""

from __future__ import annotations

import re
from typing import Dict

SUBJECTS = ["Physics", "Chemistry", "Biology", "Mathematics", "Science"]
_CLASS_RE = re.compile(r"class\s*(\d{1,2})", re.IGNORECASE)
_CLASS_TH_RE = re.compile(r"(\d{1,2})\s*th", re.IGNORECASE)
_CLASS_LEAD_RE = re.compile(r"^\s*(\d{1,2})\b")


def derive_attributes(book_slug: str) -> Dict[str, str]:
    """Infers subject, class, and board from a book slug or filename."""
    low = (book_slug or "").lower()
    subject = ""
    for s in SUBJECTS:
        if s.lower() in low:
            subject = s
            break
    if not subject and "math" in low:
        subject = "Mathematics"
    cls = ""
    m = _CLASS_RE.search(low) or _CLASS_TH_RE.search(low) or _CLASS_LEAD_RE.match(low)
    if m:
        cls = m.group(1)
    board = "Foundation" if "foundation" in low else ""
    return {"subject": subject, "class": cls, "board": board}
