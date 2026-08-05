"""Restructure the exported question bank into the assessment schema.

Two independent stages, both operating on the JSON produced by
``tools/export/export_questions_json.py`` and preserving its hierarchy
(classes -> subjects -> books -> chapters -> questions) exactly.

Stage "options" (deterministic, no LLM)
    MCQ rows store their choices *inline* in the question text::

        How many cm makes a km?
        (a) 100
        (b) 1000

    They are lifted into an ``options`` array of ``{"id": "A", "text": ...}``
    and removed from the stem.  Option text is sliced out of the **raw**
    string, so MathML / LaTeX / HTML / chemistry / Unicode / internal line
    breaks survive byte-for-byte -- only leading and trailing whitespace is
    trimmed.

    The splitter is deliberately conservative.  The bank contains three traps
    that look like option lists but are not:

    * orphan fragments -- a whole row that is just ``"(b) Soft drink"``,
      produced when extraction split one question across several rows;
    * multi-part exercises -- ``"Estimate each of the following ... (a) .. (d)"``
      where the parts are four *tasks*, not four *choices*;
    * matching columns -- ``"Column I (A) Book (B) Table ..."``.

    A row is split only when it clears every gate in ``_looks_like_options``;
    otherwise it is left untouched and counted as skipped.  Guessing here
    would silently corrupt the bank.

Stage "numerical" (needs Ollama)
    ``question_type == "Numerical"`` rows are solved and rewritten as MCQs
    with one correct answer and three mistake-derived distractors.

    Correctness is the whole point of this stage, so a single model reply is
    not trusted: the model is sampled ``--samples`` times independently and
    the answer is accepted only when the samples agree (after normalisation).
    On disagreement the row is left as ``Numerical`` and reported, because a
    confidently wrong key teaches the student the wrong answer -- the same
    reasoning ``generators/questions/mcq_parser`` applies to keys it cannot
    establish.

    Results are cached by question text in ``--cache`` so the (slow) run is
    resumable and re-runs are free.

Usage::

    python tools/export/restructure_questions.py --stage options
    python tools/export/restructure_questions.py --stage numerical --workers 4
    python tools/export/restructure_questions.py --stage all
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import hashlib
import html
import json
import os
import random
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.append(str(Path(__file__).resolve().parents[2]))

DEFAULT_IN = "exports/questions/all_questions_by_class_subject.json"
OPTION_IDS = ["A", "B", "C", "D", "E"]

# ---------------------------------------------------------------------------
# Stage 1: lift inline options out of the question text
# ---------------------------------------------------------------------------

# Option markers anchored to the start of a line -- "(a) ", "a) ", "a. ", "[A] ".
# Line anchoring is what keeps the pattern from firing inside a MathML blob or
# mid-sentence; it finds 3,135 of the 3,155 four-option rows a whitespace
# anchored pattern finds, without the false positives.
_MARKER_LINE = re.compile(r"(?:^|\n)[ \t]*[\(\[]?([a-eA-E])[\)\].][ \t]+", re.M)
# Fallback for rows that keep the whole list on one line.
_MARKER_ANY = re.compile(r"(?:(?<=\n)|(?<=^)|(?<=\s))[\(\[]?([a-eA-E])[\)\].]\s")

# Stems that introduce sub-tasks or a matching table rather than choices.
_NOT_A_CHOICE_LIST = re.compile(
    r"each of the following"
    r"|^\s*column\s*[-\s]*(i|ii|1|2|a|b)\b"
    r"|^\s*unscramble"
    r"|^\s*match\s+the"
    r"|^\s*state\s+whether"
    r"|^\s*fill\s+in\s+the\s+blank"
    r"|following\s+(questions|statements)\s*[:.]?\s*$",
    re.IGNORECASE,
)

MIN_RUN = 4
MAX_RUN = 5
# An option longer than this is almost always a sub-task or a run-on paragraph
# rather than a choice. Measured on plain text, so MathML does not inflate it.
MAX_OPTION_PLAIN_LEN = 400


def _plain_len(text: str) -> int:
    """Length of ``text`` with tags stripped and entities decoded."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip())


def _ascending_run(pattern: re.Pattern, text: str) -> List[re.Match]:
    """Matches that spell a, b, c, ... from the first marker, in order."""
    run: List[re.Match] = []
    expected = 0
    for m in pattern.finditer(text):
        if m.group(1).lower() == chr(ord("a") + expected):
            run.append(m)
            expected += 1
    return run


# The final option runs to end-of-text, so it absorbs anything the extractor
# appended after the choice list -- a worked solution, an answer key, or the
# next roman-numbered sub-part. Cut the last option at the first such marker.
_TRAILING_SECTION = re.compile(
    r"\n\s*(?:SOLUTION|SOLN|ANSWER|ANS|HINT|EXPLANATION)\s*[:.\-]"
    r"|\n\s*\((?:i|ii|iii|iv|v)\)\s",
    re.IGNORECASE,
)


def _trim_trailing_section(option: str) -> str:
    """Drop a worked solution / answer key glued onto the last option."""
    cut = _TRAILING_SECTION.search(option)
    return option[: cut.start()].strip() if cut else option


def _slice_options(text: str, run: List[re.Match]) -> Tuple[str, List[str]]:
    """Cut the stem and the raw option texts using marker offsets."""
    stem = text[: run[0].start()].strip()
    options: List[str] = []
    for i, m in enumerate(run):
        start = m.end()
        end = run[i + 1].start() if i + 1 < len(run) else len(text)
        # Only outer whitespace is trimmed: internal newlines, MathML and
        # markup are preserved exactly as stored.
        chunk = text[start:end].strip()
        if i == len(run) - 1:
            chunk = _trim_trailing_section(chunk)
        options.append(chunk)
    return stem, options


def _looks_like_options(stem: str, options: List[str]) -> bool:
    """Gate a candidate split; False means leave the row alone."""
    if not stem:
        return False  # orphan fragment -- the row is one stray choice
    if not (MIN_RUN <= len(options) <= MAX_RUN):
        return False
    if any(not o for o in options):
        return False
    if _NOT_A_CHOICE_LIST.search(stem):
        return False
    if any(_plain_len(o) > MAX_OPTION_PLAIN_LEN for o in options):
        return False
    # Options that repeat verbatim are an extraction artefact, not a real list.
    # Compared case-sensitively on purpose: "TT" and "Tt" are different
    # genotypes, and lowercasing would wrongly reject genetics questions.
    if len({o.strip() for o in options}) != len(options):
        return False
    return True


def split_inline_options(question: str) -> Optional[Tuple[str, List[str]]]:
    """Return ``(stem, options)`` or ``None`` when the row must not be split."""
    text = question or ""
    if not text.strip():
        return None
    for pattern in (_MARKER_LINE, _MARKER_ANY):
        run = _ascending_run(pattern, text)
        if not (MIN_RUN <= len(run) <= MAX_RUN):
            continue
        stem, options = _slice_options(text, run)
        if _looks_like_options(stem, options):
            return stem, options
    return None


def apply_options_stage(tree: Dict[str, Any], types: List[str]) -> Dict[str, int]:
    stats = {"converted": 0, "skipped": 0, "already": 0}
    for question in iter_questions(tree):
        if question.get("question_type") not in types:
            continue
        if question.get("options"):
            stats["already"] += 1
            continue
        split = split_inline_options(question.get("question", ""))
        if not split:
            stats["skipped"] += 1
            continue
        stem, options = split
        question["question"] = stem
        question["options"] = [
            {"id": OPTION_IDS[i], "text": text} for i, text in enumerate(options)
        ]
        stats["converted"] += 1
    return stats


# ---------------------------------------------------------------------------
# Stage 2: Numerical -> MCQ via Ollama
# ---------------------------------------------------------------------------
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def trim_question(text: str) -> str:
    """Strip absorbed theory/solution text, reusing the exporter's one rule."""
    from flatten_questions import trim_theory_leakage  # same tools/export dir

    return trim_theory_leakage(text)

_SYSTEM = (
    "You are a meticulous school mathematics and science examiner. "
    "You solve the problem exactly, then build a four-option multiple choice "
    "question. You reply with JSON only."
)

_PROMPT = """Solve this Class {cls} {subject} problem, then turn it into a 4-option MCQ.

PROBLEM:
{q}

Return JSON exactly in this shape:
{{"answer": "<the correct final answer, short>",
  "distractors": ["<wrong 1>", "<wrong 2>", "<wrong 3>"],
  "mistake_notes": ["<student error giving wrong 1>", "<...2>", "<...3>"],
  "solvable": true}}

Rules:
- "answer" must be the correct final answer only (a number with its unit, or a
  short phrase). Show no working.
- Each distractor must come from a PLAUSIBLE student mistake: arithmetic slip,
  sign error, unit-conversion error, misplaced decimal, algebraic slip, or a
  skipped step. Never invent random numbers.
- Distractors must be close to the answer in magnitude, and written in the same
  format and units as the answer.
- All four values must be distinct.
- If the problem has no single final answer, is a multi-part exercise, is
  missing data, or you are not confident, set "solvable": false.
"""


def mathml_to_text(text: str) -> str:
    """Readable rendering of MathML for the prompt only (never for output)."""
    def render(match: re.Match) -> str:
        inner = match.group(0)
        inner = re.sub(
            r"<mfrac>\s*<mrow>(.*?)</mrow>\s*<mrow>(.*?)</mrow>\s*</mfrac>",
            r"(\1)/(\2)", inner, flags=re.S,
        )
        inner = re.sub(
            r"<msup>\s*<mrow>(.*?)</mrow>\s*<mrow>(.*?)</mrow>\s*</msup>",
            r"\1^(\2)", inner, flags=re.S,
        )
        inner = re.sub(r"<msqrt>(.*?)</msqrt>", r"sqrt(\1)", inner, flags=re.S)
        return html.unescape(re.sub(r"<[^>]+>", "", inner))

    out = re.sub(r"<math[^>]*>.*?</math>", render, text or "", flags=re.S)
    out = html.unescape(re.sub(r"<[^>]+>", " ", out))
    return re.sub(r"[ \t]+", " ", out).strip()


def _normalise_answer(value: Any) -> str:
    """Loose key for comparing two samples' answers."""
    s = html.unescape(str(value or "")).strip().lower()
    s = s.replace(",", "").replace("$", "").replace("\\", "")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[.\s]+$", "", s)
    # 8, 8.0 and 08 must compare equal.
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(.*)", s)
    if m:
        num = float(m.group(1))
        num_s = str(int(num)) if num == int(num) else str(num)
        return f"{num_s} {m.group(2).strip()}".strip()
    return s


def _ollama_chat(model: str, prompt: str, temperature: float, timeout: int) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": "json",
        "think": False,
        "keep_alive": "30m",
        "options": {"temperature": temperature, "num_ctx": 8192},
    }
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))["message"]["content"]


def _one_sample(model: str, prompt: str, temperature: float, timeout: int) -> Optional[Dict]:
    try:
        raw = _ollama_chat(model, prompt, temperature, timeout)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict) or not data.get("solvable"):
        return None
    answer = str(data.get("answer") or "").strip()
    distractors = [str(d).strip() for d in (data.get("distractors") or []) if str(d).strip()]
    if not answer or len(distractors) < 3:
        return None
    return {
        "answer": answer,
        "distractors": distractors[:3],
        "mistake_notes": [str(n) for n in (data.get("mistake_notes") or [])][:3],
    }


def solve_numerical(
    question: str, cls: str, subject: str, model: str, samples: int, timeout: int
) -> Dict[str, Any]:
    """Sample the model ``samples`` times; accept only on agreement."""
    # Solve the *question*, not the pages of theory some rows absorbed during
    # extraction: feeding the whole blob to the model produced confident
    # answers to whatever problem appeared last in the dump.
    readable = mathml_to_text(trim_question(question))
    if not readable:
        return {"ok": False, "reason": "empty after rendering"}
    if len(readable) > 4000:
        return {"ok": False, "reason": "too long to solve reliably"}

    prompt = _PROMPT.format(cls=cls or "?", subject=subject or "?", q=readable)
    results: List[Dict] = []
    for i in range(max(1, samples)):
        got = _one_sample(model, prompt, 0.1 if i == 0 else 0.6, timeout)
        if got:
            results.append(got)

    if not results:
        return {"ok": False, "reason": "model declined or failed"}
    if samples > 1:
        if len(results) < 2:
            return {"ok": False, "reason": "only one usable sample"}
        keys = {_normalise_answer(r["answer"]) for r in results}
        if len(keys) != 1:
            return {
                "ok": False,
                "reason": "samples disagreed",
                "seen": sorted(r["answer"] for r in results),
            }

    best = results[0]
    pool = [best["answer"]] + best["distractors"]
    if len({_normalise_answer(p) for p in pool}) != 4:
        return {"ok": False, "reason": "distractor collided with the answer"}
    return {
        "ok": True,
        "answer": best["answer"],
        "distractors": best["distractors"],
        "mistake_notes": best.get("mistake_notes", []),
        "agreement": len(results),
    }


def _cache_key(question: str) -> str:
    return hashlib.sha1(question.encode("utf-8")).hexdigest()


def apply_numerical_stage(
    tree: Dict[str, Any],
    cache_path: Path,
    model: str,
    samples: int,
    workers: int,
    timeout: int,
    limit: Optional[int],
) -> Dict[str, int]:
    cache: Dict[str, Any] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"  loaded {len(cache)} cached solutions from {cache_path}")

    # Collect unique question texts -- the bank repeats many rows verbatim.
    pending: Dict[str, Tuple[str, str, str]] = {}
    total_rows = 0
    for cls, subject, question in iter_questions_with_context(tree):
        if question.get("question_type") != "Numerical":
            continue
        total_rows += 1
        key = _cache_key(question["question"])
        if key not in cache:
            pending.setdefault(key, (question["question"], cls, subject))

    todo = list(pending.items())
    if limit is not None:
        todo = todo[:limit]
    print(f"  {total_rows} numerical rows, {len(pending)} uncached unique texts"
          f"{f' (limited to {len(todo)})' if limit is not None else ''}")

    lock = threading.Lock()
    done = [0]
    started = time.time()

    def work(item):
        key, (text, cls, subject) = item
        result = solve_numerical(text, cls, subject, model, samples, timeout)
        with lock:
            cache[key] = result
            done[0] += 1
            n = done[0]
            if n % 10 == 0 or n == len(todo):
                rate = n / max(1e-6, time.time() - started)
                left = (len(todo) - n) / rate if rate else 0
                ok = sum(1 for v in cache.values() if v.get("ok"))
                print(f"  {n}/{len(todo)} solved  ok={ok}  "
                      f"{rate*60:.1f}/min  eta {left/60:.0f}m", flush=True)
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8"
                )

    if todo:
        with futures.ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(work, todo))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    # Apply cached solutions to every matching row.
    stats = {"converted": 0, "left_as_numerical": 0}
    for question in iter_questions(tree):
        if question.get("question_type") != "Numerical":
            continue
        entry = cache.get(_cache_key(question["question"]))
        if not entry or not entry.get("ok"):
            stats["left_as_numerical"] += 1
            continue
        pool_texts = [entry["answer"]] + list(entry["distractors"])
        # Seeded by question id so the shuffle is reproducible but the correct
        # answer does not sit at A every time.
        rng = random.Random(f"{question.get('id')}")
        rng.shuffle(pool_texts)
        correct = pool_texts.index(entry["answer"])
        question["question_type"] = "MCQ"
        question["options"] = [
            {"id": OPTION_IDS[i], "text": t} for i, t in enumerate(pool_texts)
        ]
        question["correct_option_id"] = OPTION_IDS[correct]
        question["converted_from"] = "Numerical"
        stats["converted"] += 1
    return stats


# ---------------------------------------------------------------------------
# Tree walking / IO
# ---------------------------------------------------------------------------
def iter_questions(tree: Dict[str, Any]):
    for cls in tree.get("classes", []):
        for subject in cls.get("subjects", []):
            for book in subject.get("books", []):
                for chapter in book.get("chapters", []):
                    yield from chapter.get("questions", [])


def iter_questions_with_context(tree: Dict[str, Any]):
    for cls in tree.get("classes", []):
        for subject in cls.get("subjects", []):
            for book in subject.get("books", []):
                for chapter in book.get("chapters", []):
                    for question in chapter.get("questions", []):
                        yield cls.get("class", ""), subject.get("subject", ""), question


def validate(tree: Dict[str, Any]) -> List[str]:
    """Part 6 checks. Returns a list of problems (empty means clean)."""
    problems: List[str] = []
    seen_ids = set()
    for question in iter_questions(tree):
        qid = question.get("id")
        if qid in seen_ids:
            problems.append(f"duplicate id {qid}")
        seen_ids.add(qid)
        options = question.get("options")
        if options is None:
            continue
        if not 4 <= len(options) <= 5:
            problems.append(f"id {qid}: {len(options)} options")
        if [o.get("id") for o in options] != OPTION_IDS[: len(options)]:
            problems.append(f"id {qid}: option ids {[o.get('id') for o in options]}")
        if any(not str(o.get("text", "")).strip() for o in options):
            problems.append(f"id {qid}: empty option text")
        if _MARKER_LINE.search("\n" + question.get("question", "")):
            run = _ascending_run(_MARKER_LINE, question.get("question", ""))
            if len(run) >= MIN_RUN:
                problems.append(f"id {qid}: option markers left in stem")
        if question.get("converted_from") == "Numerical":
            if question.get("correct_option_id") not in OPTION_IDS[: len(options)]:
                problems.append(f"id {qid}: bad correct_option_id")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", default=DEFAULT_IN)
    parser.add_argument("--out", dest="dst", default=None,
                        help="default: overwrite the input (a .bak is kept)")
    parser.add_argument("--stage", choices=["options", "numerical", "all"], default="all")
    parser.add_argument("--types", default="MCQ",
                        help="comma-separated question_types for the options stage")
    parser.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "qwen3:8b"))
    parser.add_argument("--samples", type=int, default=2,
                        help="independent solves that must agree (default 2)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--limit", type=int, default=None,
                        help="only solve this many uncached numericals this run")
    parser.add_argument("--cache", default="exports/questions/.numerical_cache.json")
    args = parser.parse_args()

    src = Path(args.src)
    tree = json.loads(src.read_text(encoding="utf-8"))
    print(f"Loaded {src} ({tree.get('question_count')} questions)")

    if args.stage in ("options", "all"):
        types = [t.strip() for t in args.types.split(",") if t.strip()]
        print(f"Stage 1: splitting inline options for {types} ...")
        stats = apply_options_stage(tree, types)
        print(f"  options extracted: {stats['converted']}, "
              f"left alone: {stats['skipped']}, already had options: {stats['already']}")

    if args.stage in ("numerical", "all"):
        print(f"Stage 2: Numerical -> MCQ via {args.model} "
              f"({args.samples} agreeing samples, {args.workers} workers) ...")
        stats = apply_numerical_stage(
            tree, Path(args.cache), args.model, args.samples,
            args.workers, args.timeout, args.limit,
        )
        print(f"  converted: {stats['converted']}, "
              f"left as Numerical: {stats['left_as_numerical']}")

    problems = validate(tree)
    print(f"Validation: {'clean' if not problems else str(len(problems)) + ' problems'}")
    for p in problems[:20]:
        print("   !", p)

    dst = Path(args.dst) if args.dst else src
    if dst == src:
        backup = src.with_suffix(src.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(src, backup)
            print(f"Backup written to {backup}")
    dst.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
