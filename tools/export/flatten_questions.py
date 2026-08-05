"""Flatten the hierarchical question export into one object per question.

Reads the nested export (classes -> subjects -> books -> chapters -> questions)
and emits a flat array in the assessment schema::

    class, subject, chapter, chapter_number, topic, subtopic, question_id,
    question_type, difficulty, question, options[], answer, explanation,
    cognitive_level, learning_objective

Three fields are not present in the nested file and are recovered here:

``answer``
    The correct option id ("A".."E").  For questions converted from Numerical
    by ``restructure_questions.py`` the key is already known.  For the rest it
    comes from the MySQL ``qa_content_row.answer`` column, which usually opens
    with the option letter ("(c) ...").  Roughly a third of bank rows carry a
    *misaligned* answer -- it holds the following question's text, a known
    extraction bug -- so a key is recorded only when it can be established;
    otherwise ``answer`` is "" rather than a guess.

``explanation``
    Taken from the same ``answer`` column when it holds real prose (a worked
    solution or reasoning) rather than a bare "(c)".  Left "" when the bank has
    nothing to say; generating one requires an LLM pass (see --explain-from).

``topic``
    Best available section heading, in order: a heading-like ``subtopic``, then
    the closest ``qa_theory_chapter.topic_name`` for that chapter by token
    overlap, then the chapter name.  The theory topic names are OCR output and
    some are damaged, so obvious junk ("CONCEPT MAP", "Example 6") is dropped.

Outputs a combined file plus classwise / subjectwise / chapterwise / topicwise
splits.

Usage::

    python tools/export/flatten_questions.py
    python tools/export/flatten_questions.py --no-db      # skip answer/explanation
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.append(str(Path(__file__).resolve().parents[2]))
sys.path.append(str(Path(__file__).resolve().parent))

from verify_arithmetic import computed_answer  # noqa: E402 - same tools/export dir

DEFAULT_IN = "exports/questions/all_questions_by_class_subject.json"
DEFAULT_OUT = "exports/questions/flat"
OPTION_IDS = ["A", "B", "C", "D", "E"]

# A leading option key in the answer column: "(c)", "c)", "Ans: C", "Answer - c".
_KEY_RE = re.compile(
    r"^\s*(?:ans(?:wer)?\s*[:\-.]?\s*)?[\(\[]?([a-eA-E])[\)\].]?(?:\s|$)", re.IGNORECASE
)
# Theory topic names that are structural noise rather than a real topic.
_JUNK_TOPIC = re.compile(
    # Structural headings that name no subject matter.
    r"^\s*(?:example|illustration|activity|exercise|passage|sol|soln|solution"
    r"|answer|note|summary|introduction|concept\s*map|try\s+yourself"
    r"|points?\s+to\s+remember|objective|assignment|test|worksheet"
    r"|fig|figs|figure|table|diagram|chart|graph|image|photo"
    r"|column|check\s*point|check|section|connecting\s*topic|more\s+than\s+one"
    r"|multiple\s+choice|choose\s+the|match\s+the|state\s+whether|fill\s+in"
    r"|very\s+short|short\s+answer|long\s+answer|true\s+or\s+false)\b",
    re.IGNORECASE,
)
# "4. Carbon and its Compounds" -> "Carbon and its Compounds"
_LEADING_NUMBER = re.compile(r"^\s*\d+\s*[.)\-:]\s*")
# A leading option / roman-numeral marker: "(c) Holozoic nutrition", "(iii) Heart".
_LEADING_MARKER = re.compile(
    r"^\s*[\(\[]\s*(?:[a-zA-Z]|i{1,3}v?|vi{0,3}|\d{1,2})\s*[\)\].]\s*"
)
# Topics that are really the question restated, not a section heading.
_IMPERATIVE_START = re.compile(
    r"^(?:find|solve|calculate|what|which|how|why|write|use|state|is|are|was|were"
    r"|do|does|did|can|will|would|should|construct|divide|multiply|subtract|add"
    r"|represent|name|give|choose|select|define|list|draw|prove|show|verify"
    r"|evaluate|simplify|express|convert|determine|identify|arrange|compare"
    r"|explain|describe|distinguish|complete|fill|match|if|when|where|who|whom"
    r"|the\s+following|following|in\s+the\s+following)\b",
    re.IGNORECASE,
)
_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "and", "or", "is", "are", "to", "for",
    "with", "by", "at", "from", "as", "it", "its", "be", "that", "this", "which",
    "what", "how", "why", "when", "where", "following", "was", "were", "will",
}


def plain(text: str) -> str:
    """Tag-stripped, entity-decoded text for matching (never for output)."""
    if not text:
        return ""
    stripped = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(stripped)).strip()


# ---------------------------------------------------------------------------
# Meaningless-row detection
# ---------------------------------------------------------------------------
# Extraction split many textbook items across rows, leaving behind rows that
# hold an *answer* rather than a question: a bare "(c)", a "True", a list like
# "(i) Positive (ii) Negative", or a lone math expression. They are unanswerable
# and pollute the bank, so they are dropped -- but written to a quarantine file
# rather than deleted outright.
_MASKED = re.compile(r"\b(?:MATH|TABLE)\b")
# "___", "_ _ _ _" and "...." are all fill-in-the-blank markers.
_BLANK = re.compile(r"(?:_\s*){3,}|\.{4,}")
# Any of these means the row actually asks for something.
_ASKS = re.compile(
    r"\b(?:add|subtract|multipl\w*|divid\w*|represent|find|calculat\w*|solv\w*"
    r"|state|defin\w*|name|explain|describ\w*|writ\w*|choos\w*|select|identif\w*"
    r"|give|list|draw|prov\w*|show|determin\w*|compar\w*|match|fill|complet\w*"
    r"|evaluat\w*|convert|express|arrang\w*|simplif\w*|construct|measur\w*"
    r"|estimat\w*|round|classif\w*|label|mark|plot|verif\w*|check|is|are|was"
    r"|were|do|does|did|can|will|has|have|which|what|why|how|who|when|where"
    r"|assertion|reason|following|reduce|obtain|prepare|form|make|use|apply"
    r"|derive|insert|order|count|read|observe)\b",
    re.IGNORECASE,
)
_ENUM_SPLIT = re.compile(r"[\(\[]\s*(?:[ivx]{1,4}|[a-z]|\d{1,2})\s*[\)\].]", re.IGNORECASE)
# A very short row survives only if an instruction verb *leads* it: "Define
# osmosis." is a question, while "Complete" and "Pure form" are answer scraps
# that happen to contain an instruction word.
_LEADS_WITH_VERB = re.compile(
    r"^\s*(?:define|find|solve|name|state|list|draw|write|calculate|explain"
    r"|describe|show|prove|give|convert|simplify|evaluate|complete|match"
    r"|identify|classify|label|measure|estimate|round|construct|represent|add"
    r"|subtract|multiply|divide|arrange|compare|express|determine|verify|check"
    r"|plot|mark|select|choose|fill|count|read|observe|apply|derive)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Theory leakage: question text that swallowed the rest of the section
# ---------------------------------------------------------------------------
# Extraction let some questions absorb everything that followed them -- the
# worked solution, then the next headings, then whole pages of theory. One row
# reaches 299,275 characters. The question is the text before the first such
# boundary; everything after it belongs to the book, not to the question.
_QUESTION_END = re.compile(
    r"\n\s*#{1,6}\s"                                  # a markdown heading
    r"|\bSOLUTION\s*:"                                 # the worked answer
    r"|\bDIRECTIONS\s*:"
    r"|\n\s*EXERCISE\b"
    r"|\bText\s*-\s*Book\s+Questions\b",
    re.IGNORECASE,
)
_LEADING_HASHES = re.compile(r"^\s*#{1,6}\s*")
# A line that is mostly LaTeX table plumbing ("&2255&\frac{15}{75}&\hline75&").
_LATEX_TABLE_LINE = re.compile(
    r"^[^A-Za-z]*(?:\\(?:hline|frac|begin|end|longdiv|quad|cline)\b|&)[^\n]*$",
    re.MULTILINE,
)
MIN_TRIMMED_QUESTION = 12


def trim_theory_leakage(question: str) -> str:
    """Cut a question back to the question, dropping absorbed book content."""
    text = question or ""
    # A question may legitimately open with its own "## " heading marker.
    body = _LEADING_HASHES.sub("", text, count=1)
    cut = _QUESTION_END.search(body)
    if cut:
        trimmed = body[: cut.start()].strip()
        # Only accept the cut if something question-shaped survives it.
        if len(plain(trimmed)) >= MIN_TRIMMED_QUESTION:
            body = trimmed
    body = _LATEX_TABLE_LINE.sub("", body).strip()
    if len(plain(body)) < MIN_TRIMMED_QUESTION:
        return text.strip()
    return body


def _content_words(text: str) -> List[str]:
    """Alphabetic words, ignoring the MATH/TABLE placeholders."""
    return re.findall(r"[A-Za-z]+", _MASKED.sub("", text))


def meaningless_reason(question: str) -> Optional[str]:
    """Why this row is not a question, or None when it is one.

    Conservative by design: anything carrying a question mark, a fill-in-the-blank
    marker, or a single instruction word is kept, even if it looks thin. Stems
    like "The image formed by a convex mirror" are real sentence-completion
    questions and must survive.
    """
    text = re.sub(r"<math[^>]*>.*?</math>", " MATH ", question or "", flags=re.S)
    text = re.sub(r"<table.*?</table>", " TABLE ", text, flags=re.S)
    text = plain(text)
    if not text:
        return "empty question text"
    if "?" in text or _BLANK.search(text):
        return None

    words = _content_words(text)
    if not words:
        return "expression only, no words"
    # Checked before the instruction-word exemption: a one-to-three word row is
    # a scrap unless a verb leads it and takes an object ("Define osmosis").
    # "Find 6-3." carries its whole task in the arithmetic, not in words.
    has_expression = bool(
        re.search(r"[=+×÷<>≤≥%]", text) or re.search(r"\d\s*[-+*/×÷=]\s*\d", text)
    )
    if len(words) <= 3 and not has_expression:
        if not (_LEADS_WITH_VERB.match(text) and len(words) >= 2):
            return "bare fragment"
        return None
    if _ASKS.search(text):
        return None
    segments = [s.strip() for s in _ENUM_SPLIT.split(text) if s.strip()]
    if len(segments) >= 2 and all(len(_content_words(s)) <= 4 for s in segments):
        return "enumerated label list"
    return None


def tokens(text: str) -> set:
    return {
        w for w in re.findall(r"[a-z0-9]+", plain(text).lower())
        if len(w) > 2 and w not in _STOPWORDS
    }


# ---------------------------------------------------------------------------
# DB lookups (answer key + explanation + theory topics)
# ---------------------------------------------------------------------------
def load_db_context() -> Tuple[Dict[int, str], Dict[Tuple[str, Optional[int]], List[str]]]:
    """Return ``({question_id: answer_text}, {(book, chapter_no): [topics]})``."""
    import pymysql

    from edu_pipeline.shared import db_config as cfg

    conn = pymysql.connect(
        host=cfg.DB_HOST, port=int(cfg.DB_PORT), user=cfg.DB_USER,
        password=cfg.DB_PASSWORD, database=cfg.DB_NAME, charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, answer FROM qa_content_row")
            answers = {int(r[0]): (r[1] or "") for r in cur.fetchall()}
            cur.execute(
                """SELECT ch.book_slug, ch.chapter_number, t.topic_name
                   FROM qa_theory_chapter t
                   JOIN qa_chapter ch ON t.chapter_id = ch.chapter_id
                   ORDER BY ch.book_slug, ch.chapter_number, t.section_order"""
            )
            topics: Dict[Tuple[str, Optional[int]], List[str]] = defaultdict(list)
            for book, chapter_no, name in cur.fetchall():
                name = clean_heading(name)
                if not name or _JUNK_TOPIC.match(name) or len(name) > 90:
                    continue
                if _IMPERATIVE_START.match(name):
                    continue
                # Headings that are mostly punctuation/symbols are OCR debris.
                if len(re.findall(r"[A-Za-z]", name)) < 4:
                    continue
                key = (book, int(chapter_no) if chapter_no is not None else None)
                if name not in topics[key]:
                    topics[key].append(name)
    finally:
        conn.close()
    return answers, topics


def answer_key(answer_text: str, option_count: int) -> str:
    """Option id encoded at the head of the bank's answer column, or ""."""
    match = _KEY_RE.match(plain(answer_text))
    if not match:
        return ""
    index = ord(match.group(1).lower()) - ord("a")
    return OPTION_IDS[index] if 0 <= index < option_count else ""


# Minimum share of the question's content words that must reappear in the
# answer prose for it to be trusted as that question's explanation.
MIN_EXPLANATION_OVERLAP = 0.15
# Where the answer column stops being an answer and starts being the rest of
# the textbook: a markdown heading, or the start of the next exercise block.
_SECTION_DUMP = re.compile(
    r"##|\bDIRECTIONS\s*:|\bEXERCISE\b|\bText\s*-\s*Book\s+Questions\b"
    r"|\b(?:Very\s+)?Short\s+Answer\s+Questions\b|\bLong\s+Answer\s+Questions\b",
    re.IGNORECASE,
)
# An explanation should be a few sentences, per the agreed schema.
MAX_EXPLANATION_CHARS = 800
MAX_EXPLANATION_SENTENCES = 5


def tidy_explanation(text: str) -> str:
    """Cut a section dump back to the explanation and trim it to a few sentences."""
    cut = _SECTION_DUMP.search(text)
    if cut:
        text = text[: cut.start()].strip()
    if len(text) <= MAX_EXPLANATION_CHARS:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) <= MAX_EXPLANATION_SENTENCES:
            return text.strip()
        return " ".join(sentences[:MAX_EXPLANATION_SENTENCES]).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept: List[str] = []
    for sentence in sentences[:MAX_EXPLANATION_SENTENCES]:
        if sum(len(s) for s in kept) + len(sentence) > MAX_EXPLANATION_CHARS and kept:
            break
        kept.append(sentence)
    return " ".join(kept).strip()[:MAX_EXPLANATION_CHARS].strip()


def _norm_compact(text: str) -> str:
    """Alphanumeric-only form, for comparing an option against prose."""
    return re.sub(r"[^0-9a-z]+", "", plain(text).lower())


_EXPLANATION_SPLIT = re.compile(r"\bExplanation\s*:|\bReason\s*:|\bSolution\s*:", re.I)
MIN_OPTION_MATCH_LEN = 2


def answer_from_explanation(answer_text: str, options: List[Dict[str, Any]]) -> str:
    """The option id the answer's own explanation argues for, or "".

    The bank stores ``(c) <option text> Explanation: <prose>``. The key letter
    and the text it quotes always agree (verified across 823 rows), but the
    *explanation* sometimes argues for a different option -- e.g. id 9050 is
    keyed (c) "280x10" while its explanation states the product "is 280",
    which is option (a). Returns an id only when exactly one option is named,
    so an ambiguous explanation never overrides the key.
    """
    parts = _EXPLANATION_SPLIT.split(plain(answer_text), maxsplit=1)
    if len(parts) < 2:
        return ""
    prose = _norm_compact(parts[1])
    if len(prose) < 3:
        return ""
    matches = [
        (o.get("id"), _norm_compact(o.get("text", "")))
        for o in options
        if len(_norm_compact(o.get("text", ""))) >= MIN_OPTION_MATCH_LEN
        and _norm_compact(o.get("text", "")) in prose
    ]
    # "280" is a substring of "280x10"; keep only the longest distinct match.
    maximal = [m for m in matches if not any(m[1] != n and m[1] in n for _, n in matches)]
    return maximal[0][0] if len(maximal) == 1 else ""


def explanation_from_answer(answer_text: str, question_text: str = "",
                            option_text: str = "") -> str:
    """Prose part of the answer column, with a leading option key removed.

    Returns "" when the prose looks like it belongs to a *different* question.
    About a third of bank rows have a misaligned ``answer`` (it holds the next
    question's content), so a row whose answer shares almost no vocabulary with
    its question is dropped: a mismatched explanation is worse than none.
    """
    text = plain(answer_text)
    if not text:
        return ""
    stripped = _KEY_RE.sub("", text, count=1).strip()
    # A bare key ("(c)") or a one-word answer is not an explanation.
    if len(stripped) < 40 or len(stripped.split()) < 8:
        return ""
    question_tokens = tokens(f"{question_text} {option_text}")
    if len(question_tokens) < 3:
        # Too little to judge (e.g. "Find 6-3.") -- do not risk a wrong match.
        return ""
    overlap = len(question_tokens & tokens(stripped)) / len(question_tokens)
    if overlap < MIN_EXPLANATION_OVERLAP:
        return ""
    tidied = tidy_explanation(stripped)
    # Trimming can leave a scrap; hold the same bar as before the trim.
    if len(tidied) < 40 or len(tidied.split()) < 8:
        return ""
    return tidied


# ---------------------------------------------------------------------------
# topic / subtopic
# ---------------------------------------------------------------------------
def is_heading_like(value: str) -> bool:
    """True when a subtopic reads as a section heading, not a question."""
    text = clean_heading(value)
    if not text or len(text) > 70:
        return False
    if text.endswith("?") or _JUNK_TOPIC.match(text):
        return False
    if len(re.findall(r"[A-Za-z]", text)) < 4:
        return False
    # The tagger sometimes stored the question's own first line as the subtopic.
    if _IMPERATIVE_START.match(text):
        return False
    # A heading is a noun phrase; sentence punctuation means it is prose.
    if text.count(".") > 1 or "," in text or ";" in text:
        return False
    return True


def clean_heading(value: str) -> str:
    """Strip leading numbering and option/roman markers off a heading."""
    text = (value or "").strip()
    text = _LEADING_MARKER.sub("", text)
    text = _LEADING_NUMBER.sub("", text)
    # A dangling opening bracket left by a truncated OCR heading ("(Concept Map").
    for opener, closer in (("(", ")"), ("[", "]")):
        if text.startswith(opener) and closer not in text:
            text = text[1:]
    return text.strip(" .:-")


def pick_topic(question_text: str, subtopic: str, candidates: List[str], chapter: str) -> str:
    """Best section heading for a question (see module docstring for order)."""
    if is_heading_like(subtopic):
        return clean_heading(subtopic)
    if candidates:
        qt = tokens(question_text)
        best, best_score = "", 0.0
        for name in candidates:
            nt = tokens(name)
            if not nt:
                continue
            score = len(qt & nt) / len(nt)
            if score > best_score:
                best, best_score = name, score
        if best_score >= 0.5:
            return best.strip()
    return (chapter or "").strip()


def infer_subtopic(subtopic: str, topic: str, learning_objective: str) -> str:
    """Existing subtopic when usable, else the phrase the tagger built the LO from."""
    if (subtopic or "").strip():
        return subtopic.strip()
    match = re.search(
        r"(?:key facts of|principles of|elements of|apply)\s+(.+?)\s*(?:to solve problems)?\.?$",
        learning_objective or "", re.IGNORECASE,
    )
    if match:
        candidate = match.group(1).strip(" .")
        if candidate and candidate.lower() != (topic or "").lower() and len(candidate) <= 70:
            return candidate
    return topic or ""


# ---------------------------------------------------------------------------
# Flatten
# ---------------------------------------------------------------------------
def flatten(tree: Dict[str, Any], answers: Dict[int, str],
            theory: Dict[Tuple[str, Optional[int]], List[str]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for cls in tree.get("classes", []):
        for subject in cls.get("subjects", []):
            for book in subject.get("books", []):
                for chapter in book.get("chapters", []):
                    key = (book.get("book_slug", ""), chapter.get("chapter_number"))
                    candidates = theory.get(key, [])
                    for question in chapter.get("questions", []):
                        rows.append(
                            build_row(question, cls, subject, book, chapter,
                                      candidates, answers)
                        )
    return rows


def build_row(question, cls, subject, book, chapter, candidates, answers) -> Dict[str, Any]:
    qid = question.get("id")
    options = question.get("options") or []
    answer_text = answers.get(qid, "")

    corrected_from = ""
    unverifiable = ""
    if question.get("correct_option_id"):
        answer = question["correct_option_id"]          # converted Numerical
    elif options:
        answer = answer_key(answer_text, len(options))
        # The bank's key letter is sometimes wrong while its own explanation
        # names the right option; trust the reasoning over the label.
        argued = answer_from_explanation(answer_text, options)
        if argued and answer and argued != answer:
            corrected_from, answer = answer, argued
        # Computation outranks both. The bank keys "Find 4+3" as (C) 6, and for
        # "HCF of 1624, 522, 1276" its explanation argues 18 when the answer is
        # 58 -- so an arithmetic result overrides the key *and* the explanation.
        verdict = computed_answer(question.get("question", ""), options)
        if verdict and verdict.get("answer"):
            if answer and verdict["answer"] != answer:
                corrected_from = answer
            answer = verdict["answer"]
        elif verdict and verdict.get("unverifiable"):
            # It computes, but no option equals the result: the question is
            # broken. Publishing any key here teaches a wrong answer.
            unverifiable, corrected_from, answer = verdict["unverifiable"], "", ""
    else:
        answer = ""

    topic = pick_topic(
        question.get("question", ""), question.get("subtopic", ""),
        candidates, chapter.get("chapter_name", ""),
    )
    return OrderedDict([
        ("class", cls.get("class", "")),
        ("subject", subject.get("subject", "")),
        ("chapter", chapter.get("chapter_name", "")),
        ("chapter_number", chapter.get("chapter_number")),
        ("topic", topic),
        ("subtopic", infer_subtopic(question.get("subtopic", ""), topic,
                                    question.get("learning_objective", ""))),
        ("question_id", qid),
        ("question_type", question.get("question_type", "")),
        ("difficulty", question.get("difficulty", "")),
        ("question", trim_theory_leakage(question.get("question", ""))),
        ("options", options),
        ("answer", answer),
        ("explanation", explanation_from_answer(
            answer_text, question.get("question", ""),
            " ".join(o.get("text", "") for o in options))),
        ("cognitive_level", question.get("cognitive_level", "")),
        ("learning_objective", question.get("learning_objective", "")),
        ("book", book.get("book_slug", "")),
    ] + ([("answer_corrected_from", corrected_from)] if corrected_from else [])
      + ([("answer_unverifiable", unverifiable)] if unverifiable else []))


def slug(value: Any) -> str:
    s = re.sub(r"[^\w\s-]+", "", str(value or "")).strip().lower()
    return re.sub(r"[-\s_]+", "-", s).strip("-") or "unspecified"


def write_json(path: Path, payload: Any) -> None:
    """Write ``payload`` as indented JSON.

    Streamed with ``json.dump`` rather than ``dumps() + write_text()``: the
    combined file is ~25 MB and materialising that as one string peaks at
    several hundred MB, which OOMs on a machine this size. The bytes written
    are identical -- ``total_questions`` still leads every file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def tally(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts that let a consumer check a file without walking every question."""
    by_type: Dict[str, int] = defaultdict(int)
    by_difficulty: Dict[str, int] = defaultdict(int)
    for row in rows:
        by_type[row.get("question_type") or "Unspecified"] += 1
        by_difficulty[row.get("difficulty") or "Unspecified"] += 1
    return OrderedDict([
        ("with_options", sum(1 for r in rows if r.get("options"))),
        ("with_answer", sum(1 for r in rows if r.get("answer"))),
        ("with_explanation", sum(1 for r in rows if r.get("explanation"))),
        ("by_question_type", OrderedDict(sorted(by_type.items(), key=lambda kv: -kv[1]))),
        ("by_difficulty", OrderedDict(sorted(by_difficulty.items(), key=lambda kv: -kv[1]))),
    ])


def wrap(rows: List[Dict[str, Any]], scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Envelope every emitted file with its question count up front."""
    payload = OrderedDict([("total_questions", len(rows))])
    if scope:
        payload["scope"] = OrderedDict(scope)
    payload["counts"] = tally(rows)
    payload["questions"] = rows
    return payload


# name -> (filename key, scope describing what the file covers)
_GROUPS = {
    "by-class": (
        lambda r: f"class-{slug(r['class'])}",
        lambda r: {"class": r["class"]},
    ),
    "by-subject": (
        lambda r: slug(r["subject"]),
        lambda r: {"subject": r["subject"]},
    ),
    "by-class-subject": (
        lambda r: f"class-{slug(r['class'])}_{slug(r['subject'])}",
        lambda r: {"class": r["class"], "subject": r["subject"]},
    ),
    "by-chapter": (
        lambda r: (f"class-{slug(r['class'])}_{slug(r['subject'])}"
                   f"_ch{r['chapter_number'] or 0:02d}_{slug(r['chapter'])[:40]}"),
        lambda r: {"class": r["class"], "subject": r["subject"],
                   "chapter_number": r["chapter_number"], "chapter": r["chapter"]},
    ),
    "by-topic": (
        lambda r: f"class-{slug(r['class'])}_{slug(r['subject'])}_{slug(r['topic'])[:50]}",
        lambda r: {"class": r["class"], "subject": r["subject"], "topic": r["topic"]},
    ),
}


def write_splits(rows: List[Dict[str, Any]], out_dir: Path) -> Dict[str, int]:
    """Write the split files and a per-folder manifest carrying every count."""
    counts = {}
    for folder, (keyer, scoper) in _GROUPS.items():
        # Clear the folder first: bucket names shift between runs (a renamed
        # topic, a re-tagged chapter), and a leftover file from an earlier run
        # would still look like current output.
        target = out_dir / folder
        if target.exists():
            for stale in target.glob("*.json"):
                stale.unlink()
        buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            buckets[keyer(row)].append(row)
        manifest = []
        for name in sorted(buckets):
            items = buckets[name]
            scope = scoper(items[0])
            write_json(out_dir / folder / f"{name}.json", wrap(items, scope))
            manifest.append(OrderedDict(
                [("file", f"{name}.json"), ("total_questions", len(items))]
                + list(scope.items())
            ))
        write_json(out_dir / folder / "_index.json", OrderedDict([
            ("total_files", len(manifest)),
            ("total_questions", sum(m["total_questions"] for m in manifest)),
            ("files", manifest),
        ]))
        counts[folder] = len(buckets)
    return counts


REQUIRED = [
    "class", "subject", "chapter", "chapter_number", "topic", "subtopic",
    "question_id", "question_type", "difficulty", "question", "options",
    "answer", "explanation", "cognitive_level", "learning_objective",
]


def validate(rows: List[Dict[str, Any]]) -> List[str]:
    problems = []
    seen = set()
    for row in rows:
        missing = [f for f in REQUIRED if f not in row]
        if missing:
            problems.append(f"id {row.get('question_id')}: missing {missing}")
        if row["question_id"] in seen:
            problems.append(f"duplicate question_id {row['question_id']}")
        seen.add(row["question_id"])
        options = row.get("options") or []
        if options:
            if not 4 <= len(options) <= 5:
                problems.append(f"id {row['question_id']}: {len(options)} options")
            if [o.get("id") for o in options] != OPTION_IDS[: len(options)]:
                problems.append(f"id {row['question_id']}: bad option ids")
            if row["answer"] and row["answer"] not in OPTION_IDS[: len(options)]:
                problems.append(f"id {row['question_id']}: answer outside options")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", default=DEFAULT_IN)
    parser.add_argument("--out-dir", default=DEFAULT_OUT)
    parser.add_argument("--no-db", action="store_true",
                        help="skip MySQL; answer/explanation/topic fall back to ''")
    parser.add_argument("--no-splits", action="store_true")
    parser.add_argument("--keep-meaningless", action="store_true",
                        help="keep answer-fragment rows that carry no question")
    parser.add_argument("--keep-duplicates", action="store_true",
                        help="keep questions repeated verbatim within a chapter")
    args = parser.parse_args()

    # Streamed load for the same reason as write_json: never hold the raw text
    # and the parsed tree at the same time.
    with open(args.src, encoding="utf-8") as handle:
        tree = json.load(handle)
    print(f"Loaded {args.src} ({tree.get('question_count')} questions)")

    answers: Dict[int, str] = {}
    theory: Dict[Tuple[str, Optional[int]], List[str]] = {}
    if not args.no_db:
        try:
            answers, theory = load_db_context()
            print(f"  MySQL: {len(answers)} answer rows, "
                  f"{sum(len(v) for v in theory.values())} usable theory topics")
        except Exception as exc:                      # noqa: BLE001 - optional source
            print(f"  MySQL unavailable ({exc}); continuing without answer/explanation")

    rows = flatten(tree, answers, theory)
    # The nested tree is no longer needed; the flat rows reference their own
    # option dicts. Dropping it frees ~150 MB before the writes start.
    del tree, answers, theory
    out_dir = Path(args.out_dir)

    if not args.keep_duplicates:
        # The bank was loaded twice: 7,004 questions appear as an exact pair
        # inside the same chapter. Keep the lowest question_id of each group so
        # the survivor is stable across runs.
        best: Dict[Any, Dict[str, Any]] = {}
        order: List[Any] = []
        removed = 0
        for row in rows:
            key = (row.get("class"), row.get("subject"), row.get("chapter_number"),
                   re.sub(r"\s+", " ", row.get("question", "")).strip())
            if key not in best:
                best[key] = row
                order.append(key)
            else:
                removed += 1
                incumbent = best[key]
                if (row.get("question_id") or 0) < (incumbent.get("question_id") or 0):
                    best[key] = row
        if removed:
            rows = [best[k] for k in order]
            print(f"Removed {removed} duplicate rows "
                  f"(same question, same chapter); {len(rows)} remain")

    if not args.keep_meaningless:
        kept, dropped = [], []
        for row in rows:
            reason = meaningless_reason(row.get("question", ""))
            if reason:
                dropped.append(OrderedDict([("reason", reason)] + list(row.items())))
            else:
                kept.append(row)
        rows = kept
        counts: Dict[str, int] = defaultdict(int)
        for row in dropped:
            counts[row["reason"]] += 1
        print(f"Dropped {len(dropped)} rows that are not questions "
              f"(answer fragments left by extraction):")
        for reason, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"    {n:5d}  {reason}")
        write_json(out_dir / "_removed_meaningless.json", OrderedDict([
            ("total_removed", len(dropped)),
            ("counts", OrderedDict(sorted(counts.items(), key=lambda kv: -kv[1]))),
            ("questions", dropped),
        ]))
        print(f"    quarantined to {out_dir / '_removed_meaningless.json'}")
    write_json(out_dir / "all_questions_flat.json", wrap(rows))
    print(f"Wrote {out_dir / 'all_questions_flat.json'} ({len(rows)} questions)")

    if not args.no_splits:
        counts = write_splits(rows, out_dir)
        for folder, n in counts.items():
            print(f"  {folder}: {n} files")

    with_options = sum(1 for r in rows if r["options"])
    print(f"\nCoverage: options {with_options}, answers "
          f"{sum(1 for r in rows if r['answer'])}, explanations "
          f"{sum(1 for r in rows if r['explanation'])}, topics "
          f"{sum(1 for r in rows if r['topic'])}, subtopics "
          f"{sum(1 for r in rows if r['subtopic'])}")

    problems = validate(rows)
    print(f"Validation: {'clean' if not problems else str(len(problems)) + ' problems'}")
    for p in problems[:15]:
        print("   !", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
