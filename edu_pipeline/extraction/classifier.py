"""Rule-based question type classification.

Classifies question prompts into standard educational question types:
MCQ, Assertion-Reason, Numerical, Conceptual, Short Answer, Long Answer,
Case Study, Match the Following, Fill in the Blanks, True/False, Diagram Based, etc.
"""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List

QUESTION_TYPES = (
    "MCQ",
    "Assertion-Reason",
    "Numerical",
    "Conceptual",
    "Short Answer",
    "Long Answer",
    "Case Study",
    "Match the Following",
    "Fill in the Blanks",
    "True/False",
    "Diagram Based",
    "Formula Based",
    "HOTS",
    "Application Based",
    "Activity Based",
    "Practice Question",
    "Exercise Question",
    "Illustration Question",
)

SECTION_DEFAULT_TYPE = {
    "illustration": "Illustration Question",
    "example": "Illustration Question",
    "check_your_knowledge": "Practice Question",
    "textbook_exercise": "Exercise Question",
    "exercise": "Exercise Question",
}

_ASSERTION_REASON_RE = re.compile(
    r"assertion\s*(?:\(\s*a\s*\)|[:\-])"
    r"|statement\s*[-\s]*(?:i|1)\s*[:\-].*statement\s*[-\s]*(?:ii|2)\s*[:\-]"
    r"|\bassertion\b.*\breason\s*(?:\(\s*r\s*\)|[:\-])",
    re.IGNORECASE | re.DOTALL,
)

_MCQ_RE = re.compile(
    r"\([abcd]\)|\([ABCD]\)|\boption\s+[abcd]\b|\boptions?\s*:\s*",
    re.IGNORECASE,
)
_NUMERIC_RE = re.compile(
    r"\b(find|calculate|compute|determine|evaluate|solve|how\s+(?:much|many|long|fast)|"
    r"what\s+is\s+the\s+(?:value|magnitude|speed|distance|force|resistance|current))\b",
    re.IGNORECASE,
)
_UNITS_RE = re.compile(
    r"\d+\s*(?:cm|mm|km|m\/s|m\s*s|kg|g|hz|w|v|a|°|ohm|Ω|mol|l\b|litre|second|min)\b",
    re.IGNORECASE,
)
_FORMULA_RE = re.compile(
    r"\b(formula|derive|derivation|using\s+the\s+(?:relation|equation|expression)|"
    r"prove\s+that|law\s+of)\b",
    re.IGNORECASE,
)
_DIAGRAM_RE = re.compile(
    r"\b(fig\.?|figure|diagram|image|graph|shown\s+in|refer\s+to\s+the\s+(?:fig|diagram)|"
    r"as\s+shown\s+below|in\s+the\s+given\s+figure)\b",
    re.IGNORECASE,
)
_CASE_STUDY_RE = re.compile(
    r"\b(case\s+study|read\s+the\s+passage|passage\s+based|based\s+on\s+the\s+(?:passage|paragraph)|"
    r"study\s+the\s+following\s+information)\b",
    re.IGNORECASE,
)
_ACTIVITY_RE = re.compile(
    r"\b(activity|experiment|practical|laboratory|lab\s+work|perform\s+the\s+experiment)\b",
    re.IGNORECASE,
)
_HOTS_RE = re.compile(
    r"\b(hots|higher\s+order\s+thinking|think\s+and\s+answer|justify\s+your\s+answer|"
    r"give\s+reasons?\s+for|what\s+would\s+happen\s+if)\b",
    re.IGNORECASE,
)
_APPLICATION_RE = re.compile(
    r"\b(application|daily\s+life|real\s+life|practical\s+application|"
    r"give\s+(?:an\s+)?example\s+of|used\s+in\s+(?:our\s+)?daily)\b",
    re.IGNORECASE,
)
_CONCEPTUAL_RE = re.compile(
    r"\b(why\s+does|why\s+is|distinguish\s+between|differentiate\s+between|"
    r"state\s+the\s+law|what\s+do\s+you\s+mean)\b",
    re.IGNORECASE,
)

_OPT_SPLIT_RE = re.compile(
    r"(?:^|(?<=\s))[\(\[]?\s*([a-dA-D1-4])\s*[\)\].]\s+",
)
_KEY_RE = re.compile(
    r"^\s*(?:ans(?:wer)?\s*[:\-.]?\s*)?[\(\[]?\s*([a-dA-D1-4])\s*[\)\].]?(?:\s|$)",
    re.IGNORECASE,
)
_STATEMENT_MARKER_RE = re.compile(r"\s(?=[IVX]{2,4}\.\s+[A-Z])")
_LETTERS = "abcd"
MIN_OPTIONS = 2
MAX_OPTIONS = 4


def _plain(text: str) -> str:
    """Strip HTML/MathML tags for pattern matching."""
    if not text:
        return ""
    t = re.sub(r"<[^>]+>", " ", text)
    t = html.unescape(t)
    t = re.sub(r"(?:_\s*){3,}", "____ ", t)
    return re.sub(r"\s+", " ", t).strip()


def _first_sentence_start(text: str) -> str:
    plain = _plain(text)
    if not plain:
        return ""
    return re.split(r"[.?!]\s+", plain, maxsplit=1)[0].strip().lower()


def classify_question(
    question: str,
    *,
    section_type: str = "",
    subsection: str = "",
) -> str:
    """Classify a single question using rules (most specific first)."""
    q = question or ""
    plain = _plain(q)
    combined = f"{subsection} {plain}".lower()
    start = _first_sentence_start(q)

    if _ASSERTION_REASON_RE.search(combined):
        return "Assertion-Reason"
    if _MCQ_RE.search(plain):
        return "MCQ"
    if re.search(r"\btrue\s*/\s*false\b|\btrue\s+or\s+false\b", combined):
        return "True/False"
    if re.search(r"\bmatch\s+(?:the\s+)?following\b", combined):
        return "Match the Following"
    if re.search(
        r"\bfill\s+in\s+the\s+blanks?\b|\bcomplete\s+the\s+(?:sentence|statement)\b"
        r"|_{3,}|\.{5,}|\u2026\s*\u2026",
        combined,
    ):
        return "Fill in the Blanks"
    if _CASE_STUDY_RE.search(combined):
        return "Case Study"
    if _DIAGRAM_RE.search(combined):
        return "Diagram Based"
    if _ACTIVITY_RE.search(combined):
        return "Activity Based"
    if _FORMULA_RE.search(combined):
        return "Formula Based"
    if _NUMERIC_RE.search(plain) or _UNITS_RE.search(plain):
        return "Numerical"
    if re.search(r"\d+\s*[\+\-\×\÷\=\^]", plain):
        return "Numerical"
    if re.match(r"^(define|what\s+is|what\s+are|name\s+(?:the|any|two|three|four|five))", start):
        return "Short Answer"
    if re.match(r"^(explain|describe|discuss|why)\b", start):
        return "Long Answer"
    if _HOTS_RE.search(combined):
        return "HOTS"
    if _APPLICATION_RE.search(combined):
        return "Application Based"
    if _CONCEPTUAL_RE.search(combined):
        return "Conceptual"

    section = (section_type or "").strip().lower()
    if section in SECTION_DEFAULT_TYPE:
        return SECTION_DEFAULT_TYPE[section]

    return "Exercise Question"


def _letter_to_index(token: str) -> Optional[int]:
    t = (token or "").strip().lower()
    if t in _LETTERS:
        return _LETTERS.index(t)
    if t.isdigit() and 1 <= int(t) <= 4:
        return int(t) - 1
    return None


_MARKER_STYLES = (
    lambda token: token.islower(),
    lambda token: token.isupper(),
    lambda token: token.isdigit(),
)


def _ascending_run(matches: List[Any], is_style: Any) -> List[Any]:
    run: List[Any] = []
    expected = 0
    for match in matches:
        token = match.group(1)
        if not is_style(token):
            continue
        idx = _letter_to_index(token)
        if idx is None:
            continue
        if idx == expected:
            run.append((match, idx))
            expected += 1
        elif idx == 0 and expected > 1:
            if any(_letter_to_index(later.group(1)) == expected
                   for later in matches[matches.index(match) + 1:]
                   if is_style(later.group(1))):
                continue
            break
    return run


def parse_options(question: str) -> Tuple[str, List[str]]:
    """Split an inline option list off a question stem."""
    text = _plain(question or "").strip()
    if not text:
        return "", []

    matches = list(_OPT_SPLIT_RE.finditer(text))
    if len(matches) < MIN_OPTIONS:
        return text, []

    runs = [_ascending_run(matches, style) for style in _MARKER_STYLES]
    run = max(runs, key=len) if runs else []
    if len(run) < MIN_OPTIONS:
        return text, []

    stem = text[: run[0][0].start()].strip()
    last_start = run[-1][0].start()
    tail = [m.start() for m in matches
            if m.start() > last_start and _letter_to_index(m.group(1)) == 0]
    statement = _STATEMENT_MARKER_RE.search(text, last_start)
    if statement:
        tail.append(statement.start())
    limit = min(tail) if tail else len(text)
    options: List[str] = []
    for i, (m, _idx) in enumerate(run):
        start = m.end()
        end = run[i + 1][0].start() if i + 1 < len(run) else limit
        options.append(text[start:end].strip(" .;,"))

    options = [o for o in options if o]
    if len(options) < MIN_OPTIONS or not stem:
        return text, []
    return stem, options[:MAX_OPTIONS]


def parse_correct_index(answer: str, options: List[str]) -> Optional[int]:
    """Locate the keyed option, or None when it cannot be established."""
    ans = _plain(answer or "").strip()
    if not ans or not options:
        return None

    m = _KEY_RE.match(ans)
    if m:
        idx = _letter_to_index(m.group(1))
        if idx is not None and idx < len(options):
            return idx

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
