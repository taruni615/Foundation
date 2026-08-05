#!/usr/bin/env python3
"""Question tagging: difficulty, subtopic, cognitive level, learning objective.

The PRD requires every bank question to carry ``class, subject, chapter, topic,
subtopic, difficulty, cognitive level and learning objective``.  Class/subject
are derived from ``book_slug`` and chapter/topic already exist as columns, so
this module supplies the four remaining attributes.

Like :mod:`classifier`, this is a **pure rule engine** -- no LLM, no DB, no I/O.
That keeps tagging fast enough to backfill the whole bank in one pass and makes
it trivially testable.  ``edu_pipeline.storage.database`` delegates its
``estimate_difficulty`` here so difficulty has a single definition.

Cognitive levels follow Bloom's revised taxonomy, ordered low to high::

    Remember < Understand < Apply < Analyse < Evaluate < Create

When a question matches verbs at several levels the **highest** one wins: a
question that says "compare and explain" is doing analysis, not comprehension.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .classifier import _plain

# Ordered low -> high; index doubles as the comparison rank.
COGNITIVE_LEVELS = (
    "Remember",
    "Understand",
    "Apply",
    "Analyse",
    "Evaluate",
    "Create",
)

DIFFICULTIES = ("Easy", "Moderate", "Difficult")

# ---------------------------------------------------------------------------
# Cognitive level
# ---------------------------------------------------------------------------
# Verb / phrase cues per level.  Matched on word boundaries against the plain
# text so "state" does not fire inside "statement".
_COGNITIVE_CUES: Dict[str, tuple] = {
    "Remember": (
        r"define", r"definition", r"list", r"name\b", r"state\b", r"recall",
        r"label", r"identify", r"what is", r"what are", r"who\b", r"when\b",
        r"write the (?:formula|symbol|value)", r"full form",
        # Straight recall MCQ stems -- "Which of the following is a metal?"
        r"which of the following", r"which one of", r"which among",
        r"which (?:substance|element|compound|gas|metal|acid|part|organ)",
    ),
    "Understand": (
        r"explain", r"describe", r"summari[sz]e", r"discuss", r"interpret",
        r"give (?:a )?reason", r"why\b", r"how does", r"illustrate",
        r"in your own words", r"what happens", r"meaning of",
        # Causal phrasing -- the stem asks *why*, not *which*.
        r"due to", r"because", r"caused by", r"responsible for",
        r"happens when", r"results in",
    ),
    "Apply": (
        r"calculate", r"comput", r"solve", r"determine", r"find the",
        r"how much", r"how many", r"apply", r"use the (?:formula|equation)",
        r"obtain", r"convert",
    ),
    "Analyse": (
        r"compare", r"contrast", r"differentiate", r"distinguish", r"analy[sz]e",
        r"classify", r"relate", r"what would happen if", r"deduce", r"infer",
        r"assertion", r"categori[sz]e",
    ),
    "Evaluate": (
        r"justify", r"assess", r"judge", r"argue", r"which is better",
        r"do you agree", r"comment on", r"validate", r"give your opinion",
        r"recommend", r"critically",
    ),
    "Create": (
        r"design", r"construct", r"formulate", r"devise", r"propose",
        r"draw a plan", r"create", r"develop a", r"suggest a (?:method|way)",
        r"plan an experiment",
    ),
}

_COGNITIVE_RE = {
    level: re.compile("|".join(rf"\b(?:{cue})" for cue in cues), re.IGNORECASE)
    for level, cues in _COGNITIVE_CUES.items()
}

# Question types that imply a level regardless of verb wording.
_TYPE_COGNITIVE = {
    "numerical": "Apply",
    "formula based": "Apply",
    "hots": "Analyse",
    "assertion-reason": "Analyse",
    "match the following": "Analyse",
    "case study": "Analyse",
    "application based": "Apply",
    "activity based": "Create",
    "diagram based": "Understand",
    "fill in the blanks": "Remember",
    "true/false": "Remember",
    "conceptual": "Understand",
    # A bare MCQ stem with no recognisable verb is recall, not comprehension.
    # This is only a floor -- any Understand+ cue in the text still wins.
    "mcq": "Remember",
}


def cognitive_level(question: str, question_type: str = "") -> str:
    """Bloom level for a question.  Highest matching level wins."""
    text = _plain(question or "")
    best = ""
    best_rank = -1
    for level, rx in _COGNITIVE_RE.items():
        if rx.search(text):
            rank = COGNITIVE_LEVELS.index(level)
            if rank > best_rank:
                best, best_rank = level, rank

    # A type-implied level acts as a floor: a "Numerical" row is at least
    # Apply even when its wording carries no recognisable verb.
    implied = _TYPE_COGNITIVE.get((question_type or "").strip().lower(), "")
    if implied:
        implied_rank = COGNITIVE_LEVELS.index(implied)
        if implied_rank > best_rank:
            best, best_rank = implied, implied_rank

    return best or "Understand"


# ---------------------------------------------------------------------------
# Difficulty
# ---------------------------------------------------------------------------
_MATH_MARKERS = ("<math", "$", "\\(", "\\frac", "\\sqrt", "\\int")

_HARDER_TYPES = ("numerical", "problem", "hots", "assertion", "matrix", "case study")
_EASIER_TYPES = ("definition", "fill", "true", "one word", "short")


def estimate_difficulty(stem: str, question_type: str = "") -> str:
    """Heuristic per-question difficulty (Easy | Moderate | Difficult).

    Estimated from content signals -- length, presence of formulas, question
    type and cognitive demand.  Approximate, but it gives the Practice Engine a
    per-question attribute to calibrate adaptive difficulty against.
    """
    s = stem or ""
    qt = (question_type or "").lower()
    score = 0

    n = len(_plain(s))
    if n > 260:
        score += 2
    elif n > 130:
        score += 1

    if any(m in s for m in _MATH_MARKERS):
        score += 1
    if any(t in qt for t in _HARDER_TYPES):
        score += 1
    if any(t in qt for t in _EASIER_TYPES):
        score -= 1

    # Higher-order thinking is harder than recall, independent of length.
    rank = COGNITIVE_LEVELS.index(cognitive_level(s, question_type))
    if rank >= COGNITIVE_LEVELS.index("Analyse"):
        score += 1
    elif rank <= COGNITIVE_LEVELS.index("Remember"):
        score -= 1

    if score >= 3:
        return "Difficult"
    if score >= 1:
        return "Moderate"
    return "Easy"


# ---------------------------------------------------------------------------
# Subtopic
# ---------------------------------------------------------------------------
# Words too generic to identify a subtopic by.
_STOPWORDS = frozenset("""
a an the of and or in on at to for from with without by is are was were be been
being this that these those it its as into than then so such not no any all
some each every which what when where how why introduction chapter topic
section part unit exercise questions question answer example examples following
give given find write show state explain
""".split())


def _significant(text: str) -> List[str]:
    words = re.findall(r"[a-z]+", (text or "").lower())
    return [w for w in words if len(w) > 3 and w not in _STOPWORDS]


def subtopic(question: str, headings: Sequence[str] = ()) -> str:
    """Best-matching theory heading for a question, or "" when none matches.

    ``headings`` are the ``topic_name`` values of the chapter's theory sections.
    The heading sharing the most significant words with the question wins; ties
    break toward the more specific (longer) heading.  Requiring at least two
    shared words keeps unrelated headings from being attached to every row.
    """
    q_words = set(_significant(_plain(question or "")))
    if not q_words:
        return ""

    best = ""
    best_score = 0
    for h in headings:
        h_clean = (h or "").strip()
        if not h_clean:
            continue
        h_words = set(_significant(h_clean))
        if not h_words:
            continue
        overlap = len(q_words & h_words)
        if overlap > best_score or (
            overlap == best_score and overlap > 0 and len(h_clean) > len(best)
        ):
            best, best_score = h_clean, overlap

    # One shared word is usually coincidence ("energy" appears everywhere);
    # accept it only when the heading is a single significant word itself.
    if best_score >= 2:
        return best
    if best_score == 1 and len(_significant(best)) == 1:
        return best
    return ""


# ---------------------------------------------------------------------------
# Learning objective
# ---------------------------------------------------------------------------
_OBJECTIVE_TEMPLATES = {
    "Remember": "Recall and state the key facts of {concept}.",
    "Understand": "Explain the underlying principles of {concept}.",
    "Apply": "Apply {concept} to solve problems.",
    "Analyse": "Analyse and compare the elements of {concept}.",
    "Evaluate": "Evaluate and justify conclusions about {concept}.",
    "Create": "Design or construct a solution involving {concept}.",
}

_MAX_OBJECTIVE = 512


def learning_objective(level: str, concept: str) -> str:
    """A one-line objective phrased for the given cognitive level."""
    concept = (concept or "").strip() or "this topic"
    template = _OBJECTIVE_TEMPLATES.get(level, _OBJECTIVE_TEMPLATES["Understand"])
    return template.format(concept=concept)[:_MAX_OBJECTIVE]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def tag_question(
    question: str,
    question_type: str = "",
    chapter_name: str = "",
    headings: Sequence[str] = (),
) -> Dict[str, str]:
    """Return the four tagging attributes for one question.

    ``headings`` should be the chapter's theory-section names; pass ``()`` when
    they are unavailable and ``subtopic`` simply comes back empty.
    """
    level = cognitive_level(question, question_type)
    sub = subtopic(question, headings)
    concept = sub or (chapter_name or "").strip()
    return {
        "difficulty": estimate_difficulty(question, question_type),
        "subtopic": sub[:255],
        "cognitive_level": level,
        "learning_objective": learning_objective(level, concept),
    }


def tag_items(
    items: Iterable[Dict[str, Any]],
    headings_by_chapter: Optional[Dict[Any, Sequence[str]]] = None,
) -> List[Dict[str, Any]]:
    """Tag a sequence of ``{question, question_type, chapter_id, chapter_name}``
    dicts.  Each result echoes the row ``id`` when present so callers can build
    an UPDATE batch without re-matching on text.
    """
    headings_by_chapter = headings_by_chapter or {}
    out: List[Dict[str, Any]] = []
    for it in items:
        tags: Dict[str, Any] = dict(
            tag_question(
                it.get("question", ""),
                it.get("question_type", ""),
                it.get("chapter_name", ""),
                headings_by_chapter.get(it.get("chapter_id"), ()),
            )
        )
        if it.get("id") is not None:
            tags["id"] = it["id"]
        out.append(tags)
    return out
