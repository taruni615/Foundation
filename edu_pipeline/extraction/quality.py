"""Post-extraction checks that catch a book being extracted wrongly.

Every check here exists because the fault it looks for shipped silently once:
the extraction reported success, the JSON was well-formed, and the damage was
only visible by reading the output. A book that loses six of its nine chapters,
or parses its whole answer key as more questions, still "succeeds".

The checks are about *shape*, not wording, so a new book that breaks in a new
way still trips them:

- a chapter that is a multiple of its siblings' size has swallowed its
  neighbours, whatever the contents page happened to look like;
- an exercise chapter with no answers has lost its answer key, whichever form
  the SOLUTIONS banner took;
- a question longer than any real question is a run-on, whatever it ran into.

Nothing here parses the book a second time -- these read the extraction's own
output, so the check cannot drift away from what the pipeline produced.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# A question longer than this is not a question. The longest legitimate one in
# the corpus is a Case Study passage at ~2,800 characters of text, so this
# leaves generous headroom before flagging.
RUNON_TEXT_CHARS = 6000
# A chapter this many times the median chapter's size has absorbed its
# neighbours; real chapters in these books vary by about 3x.
CHAPTER_SIZE_RATIO = 4.0
# An exercise chapter with this many questions and almost no answers has lost
# its answer key. Chapters that genuinely print no key exist, so this reports
# rather than fails when the book has no key anywhere.
MIN_QUESTIONS_FOR_ANSWER_CHECK = 40
LOW_ANSWER_RATE = 0.05

# Page furniture that must never reach a question. Each pattern is one the
# export strips; finding it again means something bypassed the sanitiser.
FURNITURE_PATTERNS = (
    ("exam tag", r"\[\s*(?:NTSE|JSTSE|KVPY|NSO|IJSO|NSEJS|NSTSE)\b"),
    ("check-your-knowledge banner", r"(?:Time\s+to\s+)?Check\s+Your\s+Knowledge"),
    ("table separator row", r":?-{3,}\s*\|"),
    ("DIRECTIONS preamble", r"\n\s*DIRECTIONS\s*[:(]"),
    ("LaTeX section heading", r"\\section\*"),
    ("un-embedded figure URL", r"!\[\]\(https?://cdn\.mathpix"),
    ("fullwidth punctuation", r"[\uFF01-\uFF5E]"),
)

_MATH_RE = re.compile(r"<math.*?</math>", re.DOTALL)
_IMG_RE = re.compile(r"<img[^>]*>|!\[[^\]]*\]\([^)]*\)|\[image:[^\]]+\]")


@dataclass
class Finding:
    """One problem found in an extracted book."""

    check: str
    severity: str  # "fail" or "warn"
    message: str
    evidence: List[str] = field(default_factory=list)


def text_length(value: Any) -> int:
    """Length of a field's prose, ignoring maths and figures.

    A question carrying six structure diagrams is long for a good reason; one
    carrying six thousand characters of the chapter's theory is not.
    """
    text = str(value or "")
    return len(_IMG_RE.sub("", _MATH_RE.sub("", text)))


def _questions_of(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [q for c in document.get("chapters") or [] for q in c.get("questions") or []]


def _answered(question: Dict[str, Any]) -> bool:
    return bool(str(question.get("answer") or "").strip())


def check_chapters_are_comparable(document: Dict[str, Any]) -> List[Finding]:
    """A chapter far larger than its siblings has swallowed them.

    This is what a missed contents-page entry looks like from the outside, and
    it does not depend on how that page was typeset -- Chemistry's chapter 3
    held 13,465 lines against a 3,000-line median.
    """
    chapters = document.get("chapters") or []
    if len(chapters) < 3:
        return []
    sizes = sorted(len(c.get("questions") or []) for c in chapters)
    median = sizes[len(sizes) // 2]
    if median < 10:
        return []
    findings = []
    for chapter in chapters:
        count = len(chapter.get("questions") or [])
        if count > median * CHAPTER_SIZE_RATIO:
            findings.append(Finding(
                check="chapter_size",
                severity="fail",
                message=(
                    f"Chapter {chapter.get('chapter_number')} "
                    f"({chapter.get('chapter_name')}) holds {count} questions "
                    f"against a median of {median} -- it has probably absorbed "
                    f"the chapters after it. Check the contents page parses."
                ),
            ))
    return findings


def check_chapters_are_distinct(document: Dict[str, Any]) -> List[Finding]:
    """The same question in two chapters means one of them is serving a stale split."""
    seen: Dict[str, int] = {}
    duplicates: List[str] = []
    for chapter in document.get("chapters") or []:
        number = chapter.get("chapter_number")
        for question in chapter.get("questions") or []:
            # Key on prose only. Two unrelated questions that both open with an
            # equation share hundreds of characters of identical MathML, which
            # reads as a duplicate when it is merely the same markup.
            prose = _IMG_RE.sub(" ", _MATH_RE.sub(" ", str(question.get("question") or "")))
            key = re.sub(r"\s+", " ", prose).strip()[:120]
            if len(key) < 60:
                continue
            first = seen.get(key)
            if first is not None and first != number:
                duplicates.append(f"ch{first} and ch{number}: {key[:70]}")
            else:
                seen.setdefault(key, number)
    if not duplicates:
        return []
    # A textbook does reprint a few questions across chapters -- IUPAC naming
    # appears in both the organic chapters. A stale split duplicates them by the
    # hundred, so the count is what separates the two.
    total = sum(len(c.get("questions") or []) for c in document.get("chapters") or [])
    widespread = len(duplicates) > max(20, total * 0.005)
    return [Finding(
        check="duplicate_questions",
        severity="fail" if widespread else "warn",
        message=(
            f"{len(duplicates)} question(s) appear in more than one chapter. A "
            f"stale topics_md/ or topics_json/ cache is the usual cause; "
            f"re-run with --force after bumping TOPIC_CACHE_VERSION."
        ),
        evidence=duplicates[:5],
    )]


def check_answer_keys_were_found(document: Dict[str, Any]) -> List[Finding]:
    """An exercise chapter with no answers has lost its SOLUTIONS banner.

    When that happens the key does not merely go missing -- it parses as more
    questions, so the chapter looks *fuller* than its siblings while being
    almost entirely unanswered.
    """
    chapters = document.get("chapters") or []
    rates = []
    for chapter in chapters:
        questions = chapter.get("questions") or []
        if len(questions) >= MIN_QUESTIONS_FOR_ANSWER_CHECK:
            rates.append(sum(1 for q in questions if _answered(q)) / len(questions))
    # A book that prints no answer key at all is a different situation from one
    # chapter losing its own, and only the second is a bug worth failing on.
    if not rates or max(rates) < 0.2:
        return []
    findings = []
    for chapter in chapters:
        questions = chapter.get("questions") or []
        if len(questions) < MIN_QUESTIONS_FOR_ANSWER_CHECK:
            continue
        answered = sum(1 for q in questions if _answered(q))
        if answered / len(questions) < LOW_ANSWER_RATE:
            findings.append(Finding(
                check="answer_key",
                severity="fail",
                message=(
                    f"Chapter {chapter.get('chapter_number')} "
                    f"({chapter.get('chapter_name')}) answers "
                    f"{answered}/{len(questions)} while other chapters in this "
                    f"book answer most of theirs -- its answer key was probably "
                    f"parsed as questions. Check the SOLUTIONS banner's form."
                ),
            ))
    return findings


def check_no_runaway_questions(document: Dict[str, Any]) -> List[Finding]:
    """A question carrying thousands of characters of prose ran on into the page."""
    offenders = []
    for chapter in document.get("chapters") or []:
        for question in chapter.get("questions") or []:
            size = text_length(question.get("question")) + text_length(question.get("answer"))
            if size > RUNON_TEXT_CHARS:
                offenders.append((size, chapter.get("chapter_number"),
                                  question.get("question_number"),
                                  str(question.get("question") or "")[:60]))
    if not offenders:
        return []
    offenders.sort(reverse=True)
    return [Finding(
        check="runaway_question",
        severity="fail",
        message=(
            f"{len(offenders)} question(s) carry more than {RUNON_TEXT_CHARS:,} "
            f"characters of text -- they have run on into the theory or the next "
            f"exercise. Largest is {offenders[0][0]:,}."
        ),
        evidence=[f"ch{c} q{n} ({size:,} chars): {text[:50]}"
                  for size, c, n, text in offenders[:5]],
    )]


def check_no_page_furniture(document: Dict[str, Any]) -> List[Finding]:
    """Banners, exam tags and table rules must not survive into a question."""
    findings = []
    for label, pattern in FURNITURE_PATTERNS:
        regex = re.compile(pattern)
        hits = []
        for chapter in document.get("chapters") or []:
            for question in chapter.get("questions") or []:
                for key in ("question", "answer", "explanation", "question_stem"):
                    value = str(question.get(key) or "")
                    if value and regex.search(value):
                        hits.append(f"ch{chapter.get('chapter_number')} "
                                    f"q{question.get('question_number')} [{key}]")
                        break
        if hits:
            findings.append(Finding(
                check="page_furniture",
                severity="fail",
                message=f"{len(hits)} question(s) still contain {label}.",
                evidence=hits[:5],
            ))
    return findings


def check_answers_are_answers(document: Dict[str, Any]) -> List[Finding]:
    """An answer holding another question's text is a misalignment, not an answer.

    This is the known shape of an alignment bug: the answer column picks up the
    *next* question instead of the key, which no amount of well-formed JSON
    reveals.
    """
    stems = set()
    for chapter in document.get("chapters") or []:
        for question in chapter.get("questions") or []:
            prose = _IMG_RE.sub(" ", _MATH_RE.sub(" ", str(question.get("question") or "")))
            key = re.sub(r"\s+", " ", prose).strip()
            if len(key) >= 60:
                stems.add(key[:120])

    offenders = []
    for chapter in document.get("chapters") or []:
        for question in chapter.get("questions") or []:
            prose = _IMG_RE.sub(" ", _MATH_RE.sub(" ", str(question.get("answer") or "")))
            key = re.sub(r"\s+", " ", prose).strip()[:120]
            if len(key) >= 60 and key in stems:
                offenders.append(f"ch{chapter.get('chapter_number')} "
                                 f"q{question.get('question_number')}: {key[:60]}")
    if not offenders:
        return []
    return [Finding(
        check="answer_is_a_question",
        severity="fail",
        message=(f"{len(offenders)} answer(s) hold the text of a question instead "
                 f"of an answer -- question/answer alignment has slipped."),
        evidence=offenders[:5],
    )]


def check_answer_keys_match_options(document: Dict[str, Any]) -> List[Finding]:
    """A key of "(e)" against four options means the answer belongs elsewhere."""
    offenders = []
    for chapter in document.get("chapters") or []:
        for question in chapter.get("questions") or []:
            options = question.get("options")
            answer = str(question.get("answer") or "").strip()
            if not isinstance(options, dict) or not options or not answer:
                continue
            match = re.fullmatch(r"\(?([a-z])\)?", answer, re.IGNORECASE)
            if match and match.group(1).lower() not in {k.lower() for k in options}:
                offenders.append(f"ch{chapter.get('chapter_number')} "
                                 f"q{question.get('question_number')}: key {answer!r} "
                                 f"but options {sorted(options)}")
    if not offenders:
        return []
    return [Finding(
        check="answer_outside_options",
        severity="fail",
        message=f"{len(offenders)} answer key(s) name an option the question does not have.",
        evidence=offenders[:5],
    )]


def check_figures_resolve(document: Dict[str, Any]) -> List[Finding]:
    """An [image:img_007] token with no matching figure renders as nothing.

    The sidecars are meant to be self-contained, so a token the document cannot
    resolve is a figure the reviewer will never see.
    """
    token_re = re.compile(r"\[image:([^\]]+)\]")
    offenders = []
    for chapter in document.get("chapters") or []:
        for question in chapter.get("questions") or []:
            available = {str(img.get("id")) for img in (question.get("images") or [])
                         if isinstance(img, dict)}
            for key in ("question", "answer", "explanation", "question_stem"):
                for token in token_re.findall(str(question.get(key) or "")):
                    if token not in available:
                        offenders.append(f"ch{chapter.get('chapter_number')} "
                                         f"q{question.get('question_number')} [{key}]: {token}")
    if not offenders:
        return []
    return [Finding(
        check="unresolved_figure",
        severity="fail",
        message=(f"{len(offenders)} figure reference(s) have no figure attached to "
                 f"the question, so they render as nothing."),
        evidence=offenders[:5],
    )]


def check_questions_were_found(document: Dict[str, Any]) -> List[Finding]:
    """An empty chapter is a split that landed in the wrong place."""
    empty = [str(c.get("chapter_number")) for c in document.get("chapters") or []
             if not (c.get("questions") or [])]
    if not empty:
        return []
    return [Finding(
        check="empty_chapter",
        severity="warn",
        message=f"Chapter(s) {', '.join(empty)} produced no questions at all.",
    )]


CHECKS = (
    check_chapters_are_comparable,
    check_chapters_are_distinct,
    check_answer_keys_were_found,
    check_no_runaway_questions,
    check_no_page_furniture,
    check_answers_are_answers,
    check_answer_keys_match_options,
    check_figures_resolve,
    check_questions_were_found,
)


def check_questions_document(document: Dict[str, Any]) -> List[Finding]:
    """Run every check against a loaded ``<book>_questions.json``."""
    findings: List[Finding] = []
    for check in CHECKS:
        findings.extend(check(document))
    return findings


def check_questions_file(path: str) -> List[Finding]:
    if not os.path.isfile(path):
        return [Finding(check="missing_file", severity="fail",
                        message=f"No questions sidecar at {path}")]
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return [Finding(check="unreadable_file", severity="fail",
                        message=f"Cannot read {path}: {exc}")]
    return check_questions_document(document)


def format_report(findings: List[Finding], book_name: str = "") -> str:
    """A short report, quiet when the book is clean."""
    title = f"Extraction quality: {book_name}" if book_name else "Extraction quality"
    if not findings:
        return f"  {title} -- OK"
    lines = [f"  {title} -- {len(findings)} issue(s)"]
    for finding in findings:
        marker = "FAIL" if finding.severity == "fail" else "warn"
        lines.append(f"    [{marker}] {finding.check}: {finding.message}")
        for item in finding.evidence:
            lines.append(f"           - {item}")
    return "\n".join(lines)


def report_questions_file(path: str, book_name: str = "") -> List[Finding]:
    """Check a sidecar and print the report. Never raises: a check is not the job."""
    try:
        findings = check_questions_file(path)
    except Exception as exc:  # pragma: no cover - a broken check must not fail a run
        print(f"  Extraction quality check skipped ({exc})")
        return []
    print(format_report(findings, book_name))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Check an extracted book's questions sidecar for extraction faults.")
    parser.add_argument("paths", nargs="+", help="One or more <book>_questions.json files")
    parser.add_argument("--warn-only", action="store_true",
                        help="Report findings but always exit 0")
    args = parser.parse_args(argv)

    failed = False
    for path in args.paths:
        book = os.path.basename(path).replace("_questions.json", "")
        findings = report_questions_file(path, book)
        if any(f.severity == "fail" for f in findings):
            failed = True
    return 1 if (failed and not args.warn_only) else 0
