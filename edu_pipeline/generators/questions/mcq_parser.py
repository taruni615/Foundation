#!/usr/bin/env python3
"""Parse bank rows into auto-gradable MCQs.

Bank rows store the option list *inline* in the question text
("... (a) foo (b) bar (c) baz (d) qux") and the key in the answer text
("(c) baz." or just "(c)").  Nothing in the schema records a structured option
array or a correct index, so the exam engine has historically fallen back to
ungradable ``type: "written"`` questions.

This module recovers the structure with rules only -- no LLM, no DB -- so the
Practice Engine can serve auto-graded questions on demand.  It is deliberately
conservative: when the key cannot be established with confidence the row is
rejected (``None``) rather than guessed at, because a wrongly-keyed question
teaches the student the wrong answer.

Distinct from :mod:`mcq_generator`, which *writes new* MCQs with Ollama; this
only reads structure that is already present in the text.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .classifier import _plain

# Option markers: "(a)", "a)", "a.", "(A)" -- at least two must be present in
# ascending order for the text to count as an inline option list.
_OPT_SPLIT_RE = re.compile(
    r"(?:^|\s)[\(\[]?\s*([a-dA-D1-4])\s*[\)\].]\s+",
)

# A leading key marker in the answer: "(c)", "c)", "c.", "Ans: c", "Answer - C"
_KEY_RE = re.compile(
    r"^\s*(?:ans(?:wer)?\s*[:\-.]?\s*)?[\(\[]?\s*([a-dA-D1-4])\s*[\)\].]?(?:\s|$)",
    re.IGNORECASE,
)

_LETTERS = "abcd"

MIN_OPTIONS = 2
MAX_OPTIONS = 4


def _letter_to_index(token: str) -> Optional[int]:
    t = (token or "").strip().lower()
    if t in _LETTERS:
        return _LETTERS.index(t)
    if t.isdigit() and 1 <= int(t) <= 4:
        return int(t) - 1
    return None


def parse_options(question: str) -> Tuple[str, List[str]]:
    """Split an inline option list off a question stem.

    Returns ``(stem, options)``.  ``options`` is empty when the text carries no
    recognisable option list, in which case ``stem`` is the whole question.
    """
    text = _plain(question or "").strip()
    if not text:
        return "", []

    matches = list(_OPT_SPLIT_RE.finditer(text))
    if len(matches) < MIN_OPTIONS:
        return text, []

    # Keep only a run that ascends a, b, c, d (or 1..4) from the first marker.
    run: List[Any] = []
    expected = 0
    for m in matches:
        idx = _letter_to_index(m.group(1))
        if idx is None:
            continue
        if idx == expected:
            run.append((m, idx))
            expected += 1
        elif idx == 0 and expected > 1:
            # A fresh (a) after a completed run -- a second list; stop here.
            break
    if len(run) < MIN_OPTIONS:
        return text, []

    stem = text[: run[0][0].start()].strip()
    options: List[str] = []
    for i, (m, _idx) in enumerate(run):
        start = m.end()
        end = run[i + 1][0].start() if i + 1 < len(run) else len(text)
        options.append(text[start:end].strip(" .;,"))

    options = [o for o in options if o]
    if len(options) < MIN_OPTIONS or not stem:
        return text, []
    return stem, options[:MAX_OPTIONS]


def parse_correct_index(answer: str, options: List[str]) -> Optional[int]:
    """Locate the keyed option, or ``None`` when it cannot be established.

    Two strategies, in order of reliability:
      1. A leading option letter in the answer ("(c) ...", "Ans: c").
      2. The answer text matching exactly one option's text.
    """
    ans = _plain(answer or "").strip()
    if not ans or not options:
        return None

    m = _KEY_RE.match(ans)
    if m:
        idx = _letter_to_index(m.group(1))
        if idx is not None and idx < len(options):
            return idx

    # Fall back to text equality -- only accept an unambiguous single match.
    norm = re.sub(r"\W+", " ", ans.lower()).strip()
    if norm:
        hits = [
            i
            for i, o in enumerate(options)
            if re.sub(r"\W+", " ", o.lower()).strip() == norm
        ]
        if len(hits) == 1:
            return hits[0]
    return None


def to_mcq(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert a ``qa_content_row`` dict into a gradable MCQ, or ``None``.

    ``None`` means the row is not safely auto-gradable -- no inline options, or
    no recoverable key.  Callers should fall back to a written question.
    """
    stem, options = parse_options(row.get("question", ""))
    if not options:
        return None
    correct = parse_correct_index(row.get("answer", ""), options)
    if correct is None:
        return None

    return {
        "source_id": row.get("id"),
        "stem": stem,
        "options": options,
        "correct_index": correct,
        "answer_text": _plain(row.get("answer", "")).strip(),
        "question_type": row.get("question_type", ""),
        "difficulty": row.get("difficulty") or "Moderate",
        "cognitive_level": row.get("cognitive_level") or "",
        "subtopic": row.get("subtopic") or "",
        "learning_objective": row.get("learning_objective") or "",
        "chapter_id": row.get("chapter_id"),
        "chapter_name": row.get("chapter_name", ""),
        "book_slug": row.get("book_slug", ""),
    }


def to_mcqs(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert what can be converted; silently drop what cannot."""
    out = []
    for r in rows:
        m = to_mcq(r)
        if m:
            out.append(m)
    return out
