#!/usr/bin/env python3
"""Batch converter: theory/descriptive rows in ``outputs/*_questions.json`` -> MCQs.

This is the JSON-file counterpart to :mod:`edu_pipeline.generators.questions.mcq_generator`
(which reads the MySQL bank).  It takes the exported subject files under
``outputs/subjectwise_json/`` and turns every *convertible* theory question into
one single-correct-answer MCQ in the delivery schema::

    {"question_id", "subject", "chapter", "topic", "question", "question_type",
     "options": {"A".."D"}, "correct_option", "correct_answer", "explanation",
     "difficulty", "blooms_level", "source_type", "tags"}

Three things about the source data drive the design:

1. ``question_type`` in the export is **unreliable** -- rows labelled
   "Assertion-Reason" are frequently fill-in-the-blanks, and rows labelled
   "Conceptual" sometimes carry ``solution == "(d)"`` and nothing else.  The
   trustworthy signal for "this is a theory row" is an empty ``options`` map,
   so that is what :func:`iter_theory_rows` selects on.

2. A large share of theory rows are **misaligned extraction output**: the
   ``question`` column holds an answer fragment ("Thermometer.", "oxygen",
   "(c) Flow of wind ... is called monsoon").  Converting those would mean
   inventing a question, so :func:`triage` rejects them with a reason instead.
   This is the same upstream defect noted for ``mcq_parser`` in CLAUDE.md.

3. Maths is embedded as raw **MathML** (and occasionally LaTeX), often hundreds
   of characters per expression.  Sending it through an 8B model invites silent
   corruption, so :func:`mask_math` swaps each expression for a placeholder and
   :func:`unmask` restores it byte-for-byte.  The model sees a readable
   rendering in a side glossary, never the markup itself.

Nothing here is imported at server start and nothing touches MySQL.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from edu_pipeline.generators.questions import tagger
from edu_pipeline.shared.json_utils import extract_json_object

SUBJECTS = ("Biology", "Chemistry", "Mathematics", "Physics", "Science")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("THEORY_MCQ_MODEL", os.environ.get("OLLAMA_MODEL", "qwen3:8b"))
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))
# Ollama defaults qwen3 to a 32k context. On a small GPU the KV cache for that
# evicts model layers to CPU and inference collapses to a crawl, so we ask for
# only what a single conversion needs.
OLLAMA_NUM_CTX = int(os.environ.get("THEORY_MCQ_NUM_CTX", "4096"))
OLLAMA_NUM_PREDICT = int(os.environ.get("THEORY_MCQ_NUM_PREDICT", "1100"))


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------
def load_class_map(classwise_dir: Path) -> Dict[str, str]:
    """Map every question id -> "Class N".

    The subject exports carry no class column; the class-wise exports of the
    same rows do, and between them they cover every id.
    """
    mapping: Dict[str, str] = {}
    for path in sorted(classwise_dir.glob("Class_*_all_questions.json")):
        label = path.name.split("_all")[0].replace("_", " ")
        for row in json.loads(path.read_text(encoding="utf-8")):
            rid = row.get("id")
            if rid:
                mapping[rid] = label
    return mapping


def iter_theory_rows(rows: Iterable[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
    """Yield rows with no populated options -- i.e. not already an MCQ."""
    for row in rows:
        if not any((row.get("options") or {}).values()):
            yield row


# ---------------------------------------------------------------------------
# Triage: which theory rows can honestly be converted?
# ---------------------------------------------------------------------------
_QUESTION_OPENERS = (
    r"what|why|how|when|where|which|who|whose|define|explain|state|name|describe|"
    r"write|find|calculate|list|give|draw|derive|prove|show|discuss|distinguish|"
    r"differentiate|compare|mention|identify|justify|classify|convert|evaluate|"
    r"solve|determine|express|fill|choose|match|complete|observe|label|arrange|"
    r"simplify|factorise|factorize|verify|construct|is|are|do|does|can|will|if"
)
_OPENER_RE = re.compile(rf"^\W*(?:{_QUESTION_OPENERS})\b", re.I)
_BARE_KEY_RE = re.compile(r"^\(?[a-dA-D][\)\.]")
_BLANK_RE = re.compile(r"_\s*_|\.{4,}|…")

# Rows whose stem is an orphaned working step rather than a question.
_WORKING_RE = re.compile(
    r"^\W*(?:let\b|so\b|thus\b|hence\b|therefore\b|since\b|given\b\s*[:,]|"
    r"c\.p\.|s\.p\.|cost of\b|the\s+\w+\s+is\b.*[.]$)",
    re.I,
)


def _plain(text: str) -> str:
    """Strip MathML/HTML markup so heuristics see words, not tags."""
    text = re.sub(r"<math\b.*?</math>", " M ", text or "", flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def looks_like_question(stem: str) -> bool:
    raw = (stem or "").strip()
    if not raw:
        return False
    if "?" in raw or _BLANK_RE.search(raw):
        return True
    flat = _plain(raw)
    if not flat:
        return False
    if _WORKING_RE.match(flat):
        return False
    return bool(_OPENER_RE.match(flat))


CONVERTIBLE = "convertible"
CONVERTIBLE_NO_ANSWER = "convertible_answer_inferred"
REJECT = "reject"


def triage(row: Dict[str, Any]) -> Tuple[str, str]:
    """Decide whether a theory row can be converted without inventing content.

    Returns ``(status, reason)`` where status is :data:`CONVERTIBLE`,
    :data:`CONVERTIBLE_NO_ANSWER` (the stem is a real question but the stored
    answer is unusable, so the model must supply it) or :data:`REJECT`.

    The stem is judged first and decides convertibility: a row whose *question*
    column actually holds answer text can never be converted honestly, whereas a
    genuine question with a broken answer column still can.
    """
    stem = (row.get("question") or "").strip()
    solution = (row.get("solution") or "").strip()
    flat_stem, flat_sol = _plain(stem), _plain(solution)

    if not flat_stem:
        return REJECT, "empty_question"
    if _BARE_KEY_RE.match(flat_stem) and len(flat_stem) < 80:
        return REJECT, "question_is_bare_answer_key"
    if not looks_like_question(stem):
        return REJECT, "question_is_orphaned_answer_text"

    # Stem is a real question from here on -- only the answer can be missing.
    if not flat_sol:
        return CONVERTIBLE_NO_ANSWER, "no_answer_provided"
    if len(flat_sol) <= 6 or (_BARE_KEY_RE.match(flat_sol) and len(flat_sol) < 12):
        return CONVERTIBLE_NO_ANSWER, "answer_is_bare_key_only"
    if flat_sol == flat_stem:
        # The two columns being identical usually means one block of answer text
        # was written to both. Only trust it as a question when the stem carries
        # an explicit question mark or blank.
        if "?" in stem or _BLANK_RE.search(stem):
            return CONVERTIBLE_NO_ANSWER, "answer_duplicates_question"
        return REJECT, "question_is_orphaned_answer_text"
    return CONVERTIBLE, ""


# ---------------------------------------------------------------------------
# Maths / table masking -- guarantees formulae survive the round trip verbatim
# ---------------------------------------------------------------------------
_MASKABLE_RE = re.compile(
    r"<math\b.*?</math>"          # MathML
    r"|<table\b.*?</table>"       # HTML tables (kept, per the table rule)
    r"|\$\$.+?\$\$|\$[^$\n]+\$"   # LaTeX display / inline
    r"|\\\(.+?\\\)|\\\[.+?\\\]",
    re.S,
)

_MML_OPS = {
    "&#x0003D;": "=", "&#x0002B;": "+", "&#x02212;": "-", "&#x000D7;": "x",
    "&#x000F7;": "/", "&#x00028;": "(", "&#x00029;": ")", "&#x0002C;": ",",
    "&#x02192;": "->", "&#x02218;": "deg", "&#x000A0;": " ",
}


def _render_mathml(fragment: str) -> str:
    """Best-effort plain-text rendering of a MathML fragment, for the glossary."""
    try:
        node = ET.fromstring(re.sub(r'\sxmlns="[^"]*"', "", fragment))
    except ET.ParseError:
        return re.sub(r"<[^>]+>", "", fragment)[:120]

    def walk(el: ET.Element) -> str:
        tag = el.tag.split("}")[-1]
        kids = list(el)
        if tag == "mfrac" and len(kids) == 2:
            return f"({walk(kids[0])})/({walk(kids[1])})"
        if tag == "msup" and len(kids) == 2:
            return f"{walk(kids[0])}^{walk(kids[1])}"
        if tag == "msub" and len(kids) == 2:
            return f"{walk(kids[0])}_{walk(kids[1])}"
        if tag == "msqrt":
            return f"sqrt({''.join(walk(k) for k in kids)})"
        text = (el.text or "")
        for code, sym in _MML_OPS.items():
            text = text.replace(code, sym)
        return text + "".join(walk(k) for k in kids) + (el.tail or "")

    return re.sub(r"\s+", " ", walk(node)).strip()[:200]


def _render_table(fragment: str) -> str:
    cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", fragment, re.S)
    flat = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
    return "table[" + " | ".join(f for f in flat if f)[:200] + "]"


def mask_math(text: str, store: Dict[str, str], glossary: Dict[str, str]) -> str:
    """Replace each maths/table span with a stable placeholder token.

    ``store`` accumulates placeholder -> original markup (for exact restore);
    ``glossary`` accumulates placeholder -> readable rendering (for the prompt).
    """
    def sub(match: re.Match) -> str:
        raw = match.group(0)
        for token, existing in store.items():
            if existing == raw:
                return token
        token = f"<<M{len(store) + 1}>>"
        store[token] = raw
        if raw.startswith("<table"):
            glossary[token] = _render_table(raw)
        elif raw.startswith("<math"):
            glossary[token] = _render_mathml(raw)
        else:
            glossary[token] = raw.strip("$\\()[] ")[:200]
        return token

    return _MASKABLE_RE.sub(sub, text or "")


_TOKEN_RE = re.compile(r"<<M\d+>>")


def unmask(text: str, store: Dict[str, str]) -> str:
    return _TOKEN_RE.sub(lambda m: store.get(m.group(0), m.group(0)), text or "")


def unknown_tokens(text: str, store: Dict[str, str]) -> List[str]:
    """Placeholders the model invented that have no source expression behind them."""
    return [t for t in _TOKEN_RE.findall(text or "") if t not in store]


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a senior examination author for the Indian "IIT Foundation" series (classes 6-10) covering Physics, Chemistry, Biology, Science and Mathematics.

You convert ONE theory/descriptive question plus its model answer into ONE high-quality single-correct-answer MCQ.

HARD RULES
1. Test the SAME concept as the source. Never substitute a different concept and never reduce the depth of the syllabus.
2. Rewrite the stem so it reads naturally as an MCQ - a crisp, self-contained question with one definite answer. Do not simply bolt options onto the original wording.
3. The correct option must follow from the MODEL ANSWER supplied. Never contradict it.
4. Give EXACTLY four options, A-D. Exactly one is correct.
5. The three distractors must sit in the same topic, be conceptually close, and represent real misconceptions or near-miss values. No joke options, no impossible values, no unrelated nouns.
6. Balance option length - a distractor must not be obviously shorter or longer than the correct option.
7. BANNED in options: "All of the above", "None of the above", "Both A and B", bare "Always", bare "Never", one-word throwaways.
8. Vary which letter carries the answer across questions.
9. Preserve numbers, units, vectors, symbols, oxidation states, charges, chemical formulae, scientific names and spellings exactly as given.
10. Placeholders of the form <<M1>>, <<M2>> stand for a formula, equation or table from the source. Reuse them verbatim when you need that expression. NEVER invent a new placeholder number and never write out its contents.
11. If a table placeholder belongs to the stem, keep it in the stem, before the options.
12. Explanation: 2-5 lines. Say why the correct option is correct and why the concept matters. Do not walk through every distractor.
13. If the source genuinely cannot become a fair single-answer MCQ (pure "draw a diagram", open-ended essay, subjective opinion, or the answer is missing), set "convertible": false and omit the other fields.

SPECIAL SOURCE FORMS
- Fill in the blank -> ask for the missing term, options are the candidate terms.
- True/False -> rewrite as a conceptual four-option question, not a True/False restatement.
- Match the following -> ask "Which of the following correctly matches ...", each option a complete matching combination.
- Assertion-Reason -> emit a standard Assertion-Reason MCQ whose four options are the usual A/R relationship statements.
- Multi-part or long theory -> pick the single key concept and build one unambiguous MCQ from it.
- Diagram/image dependent -> keep the reference and phrase the stem around it ("In the given figure, ...").

Reply with ONLY a JSON object, no prose and no markdown fence:
{"convertible": true, "question": "...", "options": {"A": "...", "B": "...", "C": "...", "D": "..."}, "correct_option": "A", "explanation": "...", "blooms_level": "Remember|Understand|Apply|Analyze|Evaluate|Create", "tags": ["...", "..."]}"""


def build_user_prompt(row: Dict[str, Any], subject: str, klass: str,
                      glossary: Dict[str, str], stem: str, answer: str) -> str:
    head = [f"Subject: {subject}", f"Chapter: {row.get('title') or ''}"]
    if klass:
        head.append(f"Class: {klass}")
    if row.get("question_type"):
        head.append(f"Source type (unreliable, use your own judgement): {row['question_type']}")
    parts = ["\n".join(h for h in head if h.strip())]
    if glossary:
        lines = "\n".join(f"  {tok} = {txt}" for tok, txt in glossary.items())
        parts.append(
            "Placeholder meanings (for your understanding only - always write the "
            f"placeholder itself, never its expansion):\n{lines}"
        )
    parts.append(f"THEORY QUESTION:\n{stem}")
    parts.append(f"MODEL ANSWER:\n{answer}")
    parts.append("Convert this into one MCQ following every rule.")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Ollama transport
# ---------------------------------------------------------------------------
class OllamaError(RuntimeError):
    pass


def call_ollama(system: str, user: str, model: str = "", temperature: float = 0.4) -> str:
    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": user,
        "system": system,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": temperature,
            "num_predict": OLLAMA_NUM_PREDICT,
            "num_ctx": OLLAMA_NUM_CTX,
        },
    }
    request = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OllamaError(f"ollama unreachable: {exc}") from exc
    return body.get("response", "")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
BANNED_OPTION_RE = re.compile(
    r"^\s*(all of the above|none of the above|both\s+[a-d]\s+and\s+[a-d]|"
    r"any of these|none of these|all of these|always|never|true|false|yes|no)\s*\.?\s*$",
    re.I,
)
_LABEL_RE = re.compile(r"^\(?([A-Da-d])[\).]\s+")


def _clean_option(value: Any) -> str:
    text = str(value or "").strip()
    return _LABEL_RE.sub("", text).strip()


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w<>]+", " ", text.lower())).strip()


def validate(raw: Any, store: Dict[str, str]) -> Tuple[Optional[Dict[str, Any]], str]:
    """Check one model reply against the quality checklist.

    Returns ``(clean_payload, "")`` or ``(None, reason)``.
    """
    if not isinstance(raw, dict):
        return None, "not_a_json_object"
    if raw.get("convertible") is False:
        return None, "model_declined"

    stem = str(raw.get("question") or "").strip()
    if not stem:
        return None, "empty_stem"

    options_in = raw.get("options")
    if isinstance(options_in, list):
        options_in = dict(zip("ABCD", options_in, strict=False))
    if not isinstance(options_in, dict):
        return None, "options_not_a_mapping"

    options: Dict[str, str] = {}
    for letter in "ABCD":
        text = _clean_option(options_in.get(letter))
        if not text:
            return None, "missing_option"
        if BANNED_OPTION_RE.match(text):
            return None, "banned_option"
        options[letter] = text

    if len({_normalise(v) for v in options.values()}) != 4:
        return None, "duplicate_options"

    lengths = [len(v) for v in options.values()]
    if max(lengths) > 4 * max(min(lengths), 1) and min(lengths) < 30:
        return None, "unbalanced_option_lengths"

    correct = str(raw.get("correct_option") or "").strip().upper()[:1]
    if correct not in options:
        return None, "bad_correct_option"

    explanation = str(raw.get("explanation") or "").strip()
    if len(explanation) < 20:
        return None, "explanation_too_short"

    # Every placeholder emitted must trace back to a real source expression.
    surfaces = [stem, explanation, *options.values()]
    if any(unknown_tokens(s, store) for s in surfaces):
        return None, "invented_placeholder"

    bloom = str(raw.get("blooms_level") or "").strip().title()
    if bloom not in tagger.COGNITIVE_LEVELS:
        bloom = ""

    tags = [str(t).strip() for t in (raw.get("tags") or []) if str(t).strip()]

    return {
        "question": stem,
        "options": options,
        "correct_option": correct,
        "correct_answer": options[correct],
        "explanation": explanation,
        "blooms_level": bloom,
        "tags": tags[:8],
    }, ""


# ---------------------------------------------------------------------------
# Per-row conversion
# ---------------------------------------------------------------------------
def convert_row(row: Dict[str, Any], subject: str, klass: str, model: str = "",
                attempts: int = 2) -> Dict[str, Any]:
    """Convert one theory row. Returns the delivery record, or an error record."""
    status, reason = triage(row)
    base = {"question_id": row.get("id"), "subject": subject, "chapter": row.get("title") or ""}
    if status == REJECT:
        return {**base, "error": reason}

    store: Dict[str, str] = {}
    glossary: Dict[str, str] = {}
    stem = mask_math(row.get("question") or "", store, glossary)
    if status == CONVERTIBLE_NO_ANSWER:
        answer = ("(none supplied - the source answer column is unusable. Determine "
                  "the correct answer yourself from the subject matter, and only "
                  "produce an MCQ if you are confident of it.)")
    else:
        answer = mask_math(row.get("solution") or "", store, glossary)
    user = build_user_prompt(row, subject, klass, glossary, stem, answer)

    last = "no_attempt"
    for attempt in range(attempts):
        try:
            reply = call_ollama(SYSTEM_PROMPT, user, model, temperature=0.3 + 0.3 * attempt)
        except OllamaError as exc:
            return {**base, "error": f"llm_error: {exc}"}
        clean, last = validate(extract_json_object(reply), store)
        if clean:
            return _finalise(clean, row, subject, klass, store, status)
    return {**base, "error": f"validation_failed: {last}"}


def _finalise(clean: Dict[str, Any], row: Dict[str, Any], subject: str, klass: str,
              store: Dict[str, str], status: str = CONVERTIBLE) -> Dict[str, Any]:
    """Restore markup, attach metadata, and emit the delivery schema."""
    stem = unmask(clean["question"], store)
    options = {k: unmask(v, store) for k, v in clean["options"].items()}
    source_type = (row.get("question_type") or "Theory").strip()

    tags = list(dict.fromkeys(
        [t for t in clean["tags"]]
        + [subject, row.get("title") or "", klass]
    ))
    subtopic = tagger.subtopic(_plain(stem)) or (row.get("title") or "")

    return {
        "question_id": row.get("id"),
        "subject": subject,
        "chapter": row.get("title") or "",
        "topic": subtopic,
        "question": stem,
        "question_type": "MCQ",
        "options": options,
        "correct_option": clean["correct_option"],
        "correct_answer": unmask(clean["correct_answer"], store),
        "explanation": unmask(clean["explanation"], store),
        "difficulty": tagger.estimate_difficulty(stem, source_type),
        "blooms_level": clean["blooms_level"] or tagger.cognitive_level(_plain(stem), source_type),
        "source_type": "Converted from Theory",
        "tags": [t for t in tags if t],
        "metadata": {
            "original_question_id": row.get("id"),
            "original_question_type": source_type,
            "original_source_type": row.get("source_type") or "",
            "original_question": row.get("question") or "",
            "original_answer": row.get("solution") or "",
            "class": klass,
            "model": OLLAMA_MODEL,
            # "source" == the correct answer came from the book's own solution;
            # "inferred" == the solution column was unusable and the model
            # supplied the answer, so these need review before going live.
            "answer_source": "inferred" if status == CONVERTIBLE_NO_ANSWER else "source",
        },
    }


# ---------------------------------------------------------------------------
# Resumable batch runner
# ---------------------------------------------------------------------------
def run_batch(rows: List[Tuple[Dict[str, Any], str, str]], out_path: Path,
              workers: int = 4, model: str = "",
              on_result: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, int]:
    """Convert ``(row, subject, class)`` triples, appending JSONL to ``out_path``.

    Already-present ids are skipped, so an interrupted run resumes cleanly.
    """
    done: set = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    done.add(json.loads(line).get("question_id"))
                except json.JSONDecodeError:
                    continue

    pending = [t for t in rows if t[0].get("id") not in done]
    stats = {"converted": 0, "skipped": 0, "resumed": len(done)}
    lock = threading.Lock()
    handle = out_path.open("a", encoding="utf-8")

    def work(triple: Tuple[Dict[str, Any], str, str]) -> Dict[str, Any]:
        row, subject, klass = triple
        return convert_row(row, subject, klass, model)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for record in pool.map(work, pending):
                with lock:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    handle.flush()
                    if record.get("error"):
                        stats["skipped"] += 1
                    else:
                        stats["converted"] += 1
                    if on_result:
                        on_result(record)
    finally:
        handle.close()
    return stats
