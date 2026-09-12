#!/usr/bin/env python3
"""Question-bank parsing: exercises, their sub-sections, and the answer key.

Foundation books lay a chapter out as

    <theory, illustrations, case studies>
    Exercise 1 : Master Boards
        Multiple Choice Questions (MCQs)     1. ... 2. ... 10. ...
        Assertion-Reason                     1. ... 2. ...
        Fill in the Blanks                   1. ... 18. ...
    Exercise 2 : Master NCERT
        Text-Book Exercise                   1. ... 16. ...
        Exemplar Questions                   1. ...
    Exercise 3 : Foundation Builder
    Exercise 4 : Foundation Builder +
    SOLUTIONS (Brief Explanations of Selected Questions)
        Exercise 1 Master Boards
            Multiple Choice Questions (MCQs) 1. (b) ... 2. (a) ...
            Assertion-Reason                 1. (d) ...
        Exercise 2 Master NCERT
        ...

so a question and its answer are separated by the whole rest of the chapter and
share only their ``(exercise, sub-section, number)`` coordinates. Numbering
restarts in every sub-section, which is why matching on the bare number alone
mixes Exercise 1's MCQ 1 up with Exercise 3's MCQ 1.

This module parses both halves into the same ``Block`` shape and aligns them on
those coordinates. The OCR is noisy in ways that matter here:

* Exercise numbers are mangled -- "Exercise 31", "Exercise 310", "Exercise 3101"
  and "Exercise 210" all appear -- so blocks are keyed on the exercise *name*
  ("Foundation Builder"), never on the digits.
* Headings lose their ``##`` prefix at random, so headings are recognised from
  the text alone.
* Answer keys are typeset in columns and get flattened into single lines
  ("7. (b) 8. (c)") or emitted out of order (1, 3, 5, ..., 2, 4, 6).
* The solutions half covers *selected* questions only, so whole sub-sections go
  missing and the two halves cannot be zipped positionally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "Block",
    "QuestionItem",
    "canonical_subsection_kind",
    "find_bank_start",
    "normalize_exercise_label",
    "parse_answer_line",
    "parse_question_bank",
    "split_bank_and_solutions",
    "split_theory_and_bank",
]


# ---------------------------------------------------------------------------
# Heading vocabulary
# ---------------------------------------------------------------------------

# ``## SOLUTIONS``/``SOLUTIONS (Brief Explanations ...)`` opens the answer half.
# Deliberately plural: singular ``SOLUTION :`` belongs to an illustration.
# "SOLUTIONS", "## SOLUTIONS <br> (Brief Explanations of Selected Questions)" and
# the unparenthesised "## Solutions Brief Explanations of Selected Questions" all
# open the answer half. Missing one makes the whole key parse as more questions.
SOLUTIONS_SPLIT_RE = re.compile(
    r"^#*\s*SOLUTIONS\b\s*(?:<br\s*/?>)?\s*(?:[(\-–:]|Brief\b|$)",
    re.IGNORECASE,
)

# "Exercise 1", "Exercise 3 : Foundation Builder", "Excercise : Foundation Builder +",
# "Exercise 310 Foundation Builder" -- the digits are OCR noise, the name is not.
# Some books letter-space the word and put the number first ("1 EXERCISE"), so
# a leading number is accepted as well as a trailing one.
EXERCISE_LINE_RE = re.compile(
    r"^#*\s*(?:(\d+)\s+)?(?:Advanced\s*)?Ex[c]?ercise\b\s*(\d*)\s*[:.\-]?\s*(.*?)\s*$",
    re.IGNORECASE,
)

# Exercise names, most specific first: "Foundation Builder +" must win over
# "Foundation Builder", or exercises 3 and 4 collapse into one.
_EXERCISE_NAMES: Tuple[Tuple[str, str], ...] = (
    (r"foundation\s*builder\s*(?:\+|＋|plus)", "foundation_builder_plus"),
    (r"foundation\s*builder", "foundation_builder"),
    (r"master\s*ncert", "master_ncert"),
    (r"master\s*boards?", "master_boards"),
    (r"revision", "revision"),
    (r"examination[-\s]*style", "examination_style"),
    # OCR drops the space: "AdvancedExercise Based on Connecting Topics".
    (r"advanced\s*exercise|connecting\s*topics", "advanced"),
)

# Sub-section kinds, most specific first ("very short answer" before "short answer",
# "case based" before "multiple choice", "assertion" before "reason").
_SUBSECTION_KINDS: Tuple[Tuple[str, str], ...] = (
    (r"case\s*(?:study|based)", "case_based"),
    (r"passage\s*based|comprehension", "passage"),
    (r"assertion", "assertion_reason"),
    (r"fill\s*in\s*the\s*blank", "fill_blanks"),
    (r"true\s*[/&and]*\s*false", "true_false"),
    (r"multiple\s*match", "multiple_matching"),
    (r"match(?:ing|\s*the\s*(?:following|column))", "matching"),
    (r"very\s*short\s*answer", "very_short_answer"),
    (r"short\s*answer", "short_answer"),
    (r"long\s*answer", "long_answer"),
    (r"integer|numeric", "integer"),
    (r"hots", "hots"),
    (r"reasoning", "reasoning"),
    (r"statement\s*based", "statement_based"),
    (r"(?:figure|diagram)\s*[/&]?\s*(?:figure|diagram)?\s*based", "diagram_based"),
    # "More than One Option Correct" and "One or More than One Option Correct"
    # are multiple-answer MCQs; they must be tested before the plain MCQ and
    # single-option patterns, which their wording also contains.
    (r"more\s*than\s*one\s*(?:option|correct)|multiple\s*option", "multiple_option"),
    (r"single\s*[od]ption", "single_option"),
    (r"multiple\s*(?:choice|correct)|\bmcq", "mcq"),
    (r"text\s*-?\s*book", "textbook"),
    (r"exemplar", "exemplar"),
    (r"subjective", "subjective"),
    (r"miscellaneous", "miscellaneous"),
)

# A heading line carries no sentence punctuation and is short. Guards against
# treating a question that merely mentions "assertion" as a heading.
_MAX_HEADING_CHARS = 90

# Mathpix emits fullwidth digits and punctuation for some pages ("５．", "5．").
# Missing them merges a question into the one above it -- 554 lines in the corpus.
NUMBERED_RE = re.compile(r"^([0-9\uFF10-\uFF19]{1,3})\s*[.)\uFF0E\uFF09\uFF1A]\s*(.*)$")
# A row of nothing but table rules is layout, never content.
TABLE_RULE_RE = re.compile(r"^\|(?:\s*:?-{2,}:?\s*\|)+\s*$")

_FULLWIDTH_DIGITS = {chr(0xFF10 + n): str(n) for n in range(10)}
# Mathpix renders whole runs of a page in fullwidth forms, so the same heading is
# "SOLUTIONS (Brief Explanations…)" in one chapter and "SOLUTIONS （Brief…）" in
# the next. Every printable ASCII character has a fullwidth twin at +0xFEE0.
_FULLWIDTH_ASCII = {chr(0xFF01 + n): chr(0x21 + n) for n in range(94)}
_FULLWIDTH_ASCII["\u3000"] = " "


def normalize_number(text: str) -> str:
    """ASCII form of a question number, so "５" and "5" are the same key."""
    return "".join(_FULLWIDTH_DIGITS.get(ch, ch) for ch in str(text or ""))


def normalize_fullwidth(text: str) -> str:
    """ASCII form of a line, so a heading matches whichever form OCR produced."""
    return "".join(_FULLWIDTH_ASCII.get(ch, ch) for ch in str(text or ""))
# "Passage", "Passage - I", "Paragraph 2" — the shared text a run of questions
# refers back to. A block can hold several, each governing the questions after it.
PASSAGE_MARKER_RE = re.compile(
    r"^#*\s*(?:passage|paragraph)\s*(?:[-–—]?\s*[IVXivx0-9]{1,4})?\s*[:.]?\s*$",
    re.IGNORECASE,
)
DIRECTIONS_RE = re.compile(r"^#*\s*DIRECTIONS\b", re.IGNORECASE)
# "DIRECTIONS (Qs. 1-32) : ..." names the question range it governs, so it marks
# a bank even in chapters whose exercise heading OCR dropped entirely.
DIRECTIONS_RANGE_RE = re.compile(r"^#*\s*DIRECTIONS\s*\(\s*Qs?\b", re.IGNORECASE)

# "1. (a) 2. (b) 3. (a)" -- a column-major key flattened onto one line.
KEYED_ANSWER_RE = re.compile(r"(\d{1,3})\s*[.)]\s*\(([a-eA-E])\)")
# Longest run of prose allowed between two entries of a compressed key line.
_MAX_COMPRESSED_GAP = 40


def _clean_heading(line: str) -> str:
    """Strip markdown/OCR decoration so a heading can be matched on its words."""
    text = normalize_fullwidth(line).strip()
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"\\section\*?\{(.*?)\}", r"\1", text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = text.replace("\\&", "&")
    text = re.sub(r"[*_`]", "", text)
    text = re.sub(r"\s+", " ", text).strip().strip(":.- ")
    # Letter-spaced headings ("1 E X E R C I S E") survive OCR in some books.
    return re.sub(r"\b(?:[A-Za-z] ){2,}[A-Za-z]\b", lambda m: m.group(0).replace(" ", ""), text)


def _looks_like_heading(line: str) -> bool:
    text = _clean_heading(line)
    if not text or len(text) > _MAX_HEADING_CHARS:
        return False
    if NUMBERED_RE.match(text):
        return False
    # Sentence-final punctuation marks prose, not a heading. Tested before
    # _clean_heading's trailing strip removes it -- the option lines under a
    # DIRECTIONS block ("(d) If Assertion is incorrect but Reason is correct.")
    # otherwise read as an Assertion-Reason heading.
    stripped = re.sub(r"^#+\s*", "", line.strip())
    if stripped.rstrip().endswith(("?", ".", ";", ",")):
        return False
    # A heading is titled, not written. "After substituting numerical values in
    # Eq.(7), we obtain" ends on no punctuation and passed every other test,
    # opening a bogus sub-section that swallowed 15,509 characters of theory as
    # its questions. Requiring most substantial words to be capitalised keeps
    # "Fill in the Blanks" and "More than One Option Correct" while rejecting a
    # sentence fragment.
    words = [word for word in re.findall(r"[A-Za-z]+", text) if len(word) >= 4]
    if len(words) >= 3:
        titled = sum(1 for word in words if word[0].isupper())
        if titled / len(words) < 0.6:
            return False
    return True


# A brief-explanation key entry: "3. (d) Substitute y=1". Questions never look
# like this -- their options sit on their own lines, one per line.
ANSWER_KEY_LINE_RE = re.compile(r"^\s*(\d{1,3})[.)]\s*\(?([a-eA-E])\)")
# How many such lines, and how close together, before a run counts as the key.
_KEY_RUN_LENGTH = 5
_KEY_RUN_WINDOW = 60


def find_answer_key_start(lines: List[str]) -> Optional[int]:
    """Line where a bannerless answer key begins, or None.

    Only used when no SOLUTIONS banner was found. Measured against every
    chapter in the corpus that *does* have one, this never fires earlier than
    the real banner -- so at worst it recovers part of a key rather than
    cutting a chapter's questions in half.
    """
    hits = [i for i, line in enumerate(lines) if ANSWER_KEY_LINE_RE.match(line)]
    for position, start in enumerate(hits):
        window = [h for h in hits[position:] if h < start + _KEY_RUN_WINDOW]
        if len(window) < _KEY_RUN_LENGTH:
            continue
        numbers = [int(ANSWER_KEY_LINE_RE.match(lines[h]).group(1))
                   for h in window[:_KEY_RUN_LENGTH]]
        if all(b >= a for a, b in zip(numbers, numbers[1:])):
            # The key names its own section right above the run. Left on the
            # question side, the answers have no sub-section to align against
            # and attach to nothing.
            back = start - 1
            while back >= 0 and not lines[back].strip():
                back -= 1
            if back >= 0 and _looks_like_heading(lines[back]):
                return back
            return start
    return None


def canonical_subsection_kind(title: str) -> str:
    """Map a sub-section heading onto a stable kind, or "" when unrecognised."""
    text = _clean_heading(title).lower()
    if not text:
        return ""
    for pattern, kind in _SUBSECTION_KINDS:
        if re.search(pattern, text):
            return kind
    return ""


def normalize_exercise_label(title: str) -> Tuple[str, str]:
    """Return ``(key, display_title)`` for an exercise heading.

    The key comes from the exercise *name* when the book gives one, since the
    digits are unreliable; a bare "Exercise 2" falls back to its number.
    """
    display = _clean_heading(title)
    # Matched against the cleaned text, so letter-spaced headings
    # ("1 E X E R C I S E") and LaTeX-wrapped ones are recognised too.
    match = EXERCISE_LINE_RE.match(display)
    if not match:
        return "", display
    digits = match.group(1) or match.group(2)
    remainder = match.group(3).lower()
    for pattern, name in _EXERCISE_NAMES:
        if re.search(pattern, remainder):
            return name, display
    if digits:
        # "31"/"310"/"3101" are all exercise 3 with trailing OCR noise.
        return f"exercise_{digits[0]}", display
    return "exercise", display


def _is_exercise_heading(line: str) -> bool:
    if not _looks_like_heading(line):
        return False
    return bool(EXERCISE_LINE_RE.match(_clean_heading(line)))


# ---------------------------------------------------------------------------
# Parsed shapes
# ---------------------------------------------------------------------------


@dataclass
class QuestionItem:
    number: str
    text: str
    # Line index within the parsed half, so questions can be restored to the
    # order they appear in the book rather than grouped by section.
    line: int = 0
    # Shared passage this question refers back to, when it sits under one.
    passage: str = ""


@dataclass
class Block:
    """One ``(exercise, sub-section)`` group of consecutively numbered items."""

    exercise_key: str
    exercise_title: str
    subsection_kind: str
    subsection_title: str
    items: List[QuestionItem] = field(default_factory=list)

    @property
    def coord(self) -> Tuple[str, str]:
        return (self.exercise_key, self.subsection_kind)


def split_bank_and_solutions(markdown: str) -> Tuple[str, str]:
    """Split a chapter's question bank from its SOLUTIONS half.

    Returns ``(bank_markdown, solutions_markdown)``; the second is empty for
    books that print answers inline instead of in a trailing key.
    """
    lines = markdown.splitlines()
    for idx, line in enumerate(lines):
        if SOLUTIONS_SPLIT_RE.match(normalize_fullwidth(line).strip()):
            return "\n".join(lines[:idx]), "\n".join(lines[idx + 1 :])
    # Some chapters lose the banner entirely -- Maths chapter 2 has no
    # "SOLUTIONS" line anywhere, so its whole key parsed as 243 more unanswered
    # questions. The key still looks like a key, so find it by its shape.
    idx = find_answer_key_start(lines)
    if idx is not None:
        return "\n".join(lines[:idx]), "\n".join(lines[idx:])
    return markdown, ""


# Sub-section kinds that only ever open a question bank. "case_based",
# "passage", "matching" and "reasoning" are excluded: theory carries worked
# "CASE STUDY-1 :" blocks and comprehension passages of its own, so treating
# those as the boundary swallows the chapter's theory into the bank.
_BANK_ONLY_KINDS = frozenset({
    "mcq", "single_option", "multiple_option", "fill_blanks", "true_false",
    "assertion_reason", "very_short_answer", "short_answer", "long_answer",
    "integer", "hots", "textbook", "exemplar", "subjective",
})


def find_bank_start(markdown: str) -> Optional[int]:
    """Line index where a chapter's question bank begins, or None.

    Foundation chapters run theory first and then the exercises, so the first
    exercise heading -- or, when OCR dropped it, the first unambiguous
    question-type sub-section heading -- marks the boundary.
    """
    for index, line in enumerate(markdown.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if _is_exercise_heading(stripped):
            return index
        if DIRECTIONS_RANGE_RE.match(stripped):
            return index
        if _looks_like_heading(stripped) and canonical_subsection_kind(stripped) in _BANK_ONLY_KINDS:
            return index
    return None


def split_theory_and_bank(markdown: str) -> Tuple[str, str]:
    """Split a chapter into ``(theory_markdown, question_bank_markdown)``."""
    start = find_bank_start(markdown)
    if start is None:
        return markdown, ""
    lines = markdown.splitlines()
    return "\n".join(lines[:start]), "\n".join(lines[start:])


def parse_answer_line(text: str) -> List[Tuple[str, str]]:
    """Split a compressed answer-key line into ``(number, answer)`` pairs.

    ``"1. (a) 2. (b) 3. (a)"`` yields three entries, while
    ``"1. (b) In plane mirror, object distance = image distance"`` yields one --
    the prose after the option marks it as a real explanation, not a key row.
    """
    matches = list(KEYED_ANSWER_RE.finditer(text))
    if len(matches) < 2:
        return []
    # Every gap between consecutive keys must be short, or this is prose that
    # merely happens to mention another numbered option.
    for current, following in zip(matches, matches[1:]):
        if following.start() - current.end() > _MAX_COMPRESSED_GAP:
            return []
    pairs: List[Tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        answer = text[match.start() : end].strip()
        # Drop the leading "7." so the value is the answer, not the numbering.
        answer = NUMBERED_RE.sub(r"\2", answer, count=1).strip()
        pairs.append((match.group(1), answer))
    return pairs


def parse_blocks(markdown: str, *, compress_keys: bool = False) -> List[Block]:
    """Parse one half of a chapter into ordered ``(exercise, sub-section)`` blocks.

    ``compress_keys`` splits flattened answer-key lines; it is enabled for the
    SOLUTIONS half only, where "7. (b) 8. (c)" is two answers rather than one
    question that mentions an option.
    """
    blocks: List[Block] = []
    exercise_key = ""
    exercise_title = ""
    subsection_kind = ""
    subsection_title = ""
    current: Optional[Block] = None
    pending: Optional[QuestionItem] = None
    # The passage in force. Text between a "Passage" marker and the next
    # numbered item belongs to the questions that follow it, not to any one of
    # them, so it is carried onto each rather than folded into the first.
    passage_lines: List[str] = []
    collecting_passage = False
    current_passage = ""

    def close_item() -> None:
        nonlocal pending
        if pending is not None and current is not None:
            pending.text = pending.text.strip()
            current.items.append(pending)
        pending = None

    def close_block() -> None:
        nonlocal current
        close_item()
        if current is not None and current.items:
            blocks.append(current)
        current = None

    def open_block() -> Block:
        return Block(
            exercise_key=exercise_key,
            exercise_title=exercise_title,
            subsection_kind=subsection_kind,
            subsection_title=subsection_title,
        )

    for line_no, raw_line in enumerate(markdown.splitlines()):
        line = raw_line.strip()
        if not line:
            if pending is not None:
                pending.text += "\n"
            continue
        if TABLE_RULE_RE.match(line):
            continue

        if _is_exercise_heading(line):
            close_block()
            exercise_key, exercise_title = normalize_exercise_label(line)
            subsection_kind = subsection_title = ""
            current_passage = ""
            collecting_passage = False
            passage_lines = []
            continue

        if PASSAGE_MARKER_RE.match(line):
            close_item()
            collecting_passage = True
            passage_lines = []
            continue

        # Tested before the heading check: a DIRECTIONS line restates the format
        # of the block that follows ("DIRECTIONS : This section contains
        # multiple choice questions...") and would otherwise be read as an MCQ
        # heading, overwriting the real one.
        if DIRECTIONS_RE.match(line):
            close_item()
            directed = canonical_subsection_kind(line)
            # Directions name the format of what follows, and are sometimes the
            # only thing that does. They are adopted as the sub-section kind
            # when no heading is in force, or when they follow questions -- both
            # mean the real heading was lost to OCR, as Assertion-Reason blocks
            # routinely are. Directions that merely restate the heading just
            # above are ignored, so "Single Option Correct" is not overwritten
            # by its own "contains multiple choice questions" preamble.
            if directed and directed != subsection_kind:
                if not subsection_kind:
                    subsection_kind = directed
                elif current is not None and current.items:
                    close_block()
                    subsection_kind = directed
                    subsection_title = ""
            continue

        if _looks_like_heading(line):
            kind = canonical_subsection_kind(line)
            if kind:
                close_block()
                subsection_kind = kind
                subsection_title = _clean_heading(line)
                current_passage = ""
                collecting_passage = False
                passage_lines = []
                continue

        if compress_keys:
            keyed = parse_answer_line(line)
            if keyed:
                close_item()
                if current is None:
                    current = open_block()
                for number, answer in keyed:
                    current.items.append(QuestionItem(
                        number=normalize_number(number), text=answer, line=line_no))
                continue

        numbered = NUMBERED_RE.match(line)
        if numbered:
            number, rest = normalize_number(numbered.group(1)), numbered.group(2)
            if current is None:
                current = open_block()
            elif any(item.number == number for item in current.items):
                # The number restarted inside one heading: a second, unlabelled
                # block (a repeated "Passage Based Questions", say) has begun.
                close_block()
                current = open_block()
            if collecting_passage:
                current_passage = "\n".join(passage_lines).strip()
                collecting_passage = False
                passage_lines = []
            close_item()
            pending = QuestionItem(
                number=number, text=rest, line=line_no, passage=current_passage)
            continue

        if collecting_passage:
            passage_lines.append(raw_line)
            continue

        if pending is not None:
            pending.text += "\n" + raw_line

    close_block()
    return blocks


def _drop_leading_theory(blocks: List[Block]) -> List[Block]:
    """Discard unlabelled blocks preceding the first real exercise heading.

    Theory carries its own numbered lists (ray-diagram rules, properties of an
    image) that parse as questions. They always sit *before* the first exercise
    or sub-section heading, so anything unlabelled up to that point is dropped --
    unless the chapter has no headings at all, in which case every block is
    kept rather than losing the whole bank.
    """
    first_labelled = next(
        (i for i, b in enumerate(blocks) if b.exercise_key or b.subsection_kind),
        None,
    )
    return blocks if first_labelled is None else blocks[first_labelled:]


def _align_blocks(
    question_blocks: List[Block],
    solution_blocks: List[Block],
) -> List[Tuple[Block, Optional[Block]]]:
    """Pair each question block with its solution block.

    Matching is on ``(exercise_key, subsection_kind)`` and is consumed left to
    right, so repeated coordinates pair up in order. Because the SOLUTIONS half
    covers selected questions only, an unmatched question block is expected and
    simply yields no answers.
    """
    used: List[bool] = [False] * len(solution_blocks)
    cursor = 0

    def find(block: Block, *, exact: bool, from_cursor: bool) -> Optional[int]:
        start = cursor if from_cursor else 0
        for index in range(start, len(solution_blocks)):
            if used[index]:
                continue
            candidate = solution_blocks[index]
            if candidate.subsection_kind != block.subsection_kind:
                continue
            if exact and candidate.exercise_key != block.exercise_key:
                continue
            return index
        return None

    # Both halves list their blocks in the same order, so a forward search from
    # the last match is preferred: it keeps repeated coordinates (two "Passage
    # Based Questions" in one exercise) in sequence. The exercise key is only a
    # preference, since OCR routinely renders one exercise as "Exercise" on one
    # side and "Exercise 1" on the other; a sub-section match still counts when
    # the keys disagree.
    strategies = ((True, True), (False, True), (True, False), (False, False))

    def find_unlabelled(block: Block) -> Optional[int]:
        """Match a key that carries no headings at all, on its numbers alone.

        Some chapters print the key as a bare list under "## Solutions", with
        nothing naming the exercise or sub-section it answers, so there is no
        coordinate to match on. Requiring most of this block's numbers to be
        present keeps it evidence-based: matching on bare numbers *globally*
        is what paired Exercise 1's MCQ 1 with Exercise 3's in the first place.
        """
        numbers = {normalize_number(item.number) for item in block.items}
        if len(numbers) < 3:
            return None
        best_index, best_overlap = None, 0
        for index, candidate in enumerate(solution_blocks):
            if used[index] or candidate.subsection_kind or candidate.exercise_key:
                continue
            overlap = len(numbers & {normalize_number(i.number) for i in candidate.items})
            if overlap > best_overlap:
                best_index, best_overlap = index, overlap
        if best_index is not None and best_overlap >= max(3, len(numbers) * 0.6):
            return best_index
        return None

    pairs: List[Tuple[Block, Optional[Block]]] = []
    for block in question_blocks:
        index = None
        for exact, from_cursor in strategies:
            index = find(block, exact=exact, from_cursor=from_cursor)
            if index is not None:
                break
        if index is None:
            index = find_unlabelled(block)
        if index is None:
            pairs.append((block, None))
            continue
        used[index] = True
        cursor = index + 1
        pairs.append((block, solution_blocks[index]))
    return pairs


def parse_question_bank(markdown: str) -> List[Dict[str, Any]]:
    """Parse a chapter's question bank into exercises with answers attached.

    Returns one dict per ``(exercise, sub-section)`` block::

        {"exercise_key", "exercise_title", "subsection_kind", "subsection_title",
         "questions": [{"number", "prompt_markdown", "solution_markdown"}]}
    """
    bank_md, solutions_md = split_bank_and_solutions(markdown)
    # Drop the theory that precedes the bank: its numbered lists (ray-diagram
    # rules, image properties under a CASE STUDY heading) parse as questions.
    _theory_md, bank_md = split_theory_and_bank(bank_md)
    question_blocks = _drop_leading_theory(parse_blocks(bank_md))
    solution_blocks = parse_blocks(solutions_md, compress_keys=True) if solutions_md else []

    sections: List[Dict[str, Any]] = []
    for block, solutions in _align_blocks(question_blocks, solution_blocks):
        answers: Dict[str, str] = {}
        positional: List[str] = []
        if solutions is not None:
            for item in solutions.items:
                answers.setdefault(item.number, item.text)
            # Some sub-sections continue the exercise's running numbering in the
            # question half ("29., 30.") while their answers restart at 1. With
            # no number in common the two lists can only be paired in order.
            question_numbers = {item.number for item in block.items}
            if question_numbers.isdisjoint(answers):
                positional = [item.text for item in solutions.items]
        sections.append({
            "exercise_key": block.exercise_key,
            "exercise_title": block.exercise_title,
            "subsection_kind": block.subsection_kind,
            "subsection_title": block.subsection_title,
            "questions": [
                {
                    "number": item.number,
                    "prompt_markdown": item.text,
                    "solution_markdown": answers.get(
                        item.number,
                        positional[index] if index < len(positional) else "",
                    ),
                    "source_line": item.line,
                    "passage": item.passage,
                }
                for index, item in enumerate(block.items)
            ],
        })
    return sections


# ---------------------------------------------------------------------------
# Rule-based Question Classification & Option Parsing
# ---------------------------------------------------------------------------
import html

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

