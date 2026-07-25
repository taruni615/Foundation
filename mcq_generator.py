#!/usr/bin/env python3
"""Theory-question -> MCQ converter (Ollama-powered).

Many extracted questions are *theory* / open-ended (Short Answer, Long Answer,
Case Study, Conceptual, Fill in the Blanks, ...).  Those can only ever be used
as "written" questions -- collected for review, never auto-graded.  This module
uses the **same local Ollama** the extraction pipeline already relies on to turn
such a theory question (plus its model answer) into a proper, auto-gradable
multiple-choice question that looks like the MCQs already in the bank:

    {"stem": "...", "options": ["A","B","C","D"], "correct_index": 1,
     "explanation": "..."}

Design goals:
  * **Non-breaking / additive.** Nothing here is imported at server start; the
    app and pipeline keep working untouched even when Ollama is offline.
  * **Reuse, don't duplicate.** It borrows ``OllamaClient`` and the JSON
    extraction helper from ``topicwise_pipeline`` (imported lazily so importing
    this module never pulls in the heavy pipeline unless conversion is asked
    for).
  * **Safe to fail.** Conversion either returns a validated MCQ dict or raises a
    clear error; callers degrade to the existing "written" behaviour.

CLI -- batch-convert every theory question in the bank::

    python mcq_generator.py --limit 50 --out outputs/generated_mcqs.json
    python mcq_generator.py --subject Physics --class 10
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a KEY=VALUE .env file, without overriding values
    already set in the real environment.

    This mirrors ``app_server._load_dotenv`` but is kept local so this module is
    self-sufficient: it must run BEFORE the lazy imports of ``topicwise_pipeline``
    (which freezes ``DB_*`` / ``OLLAMA_*`` from the environment at import time)
    and ``bank_read`` (which reads ``DB_SOCKET`` at import time).  That way the
    DB + Ollama credentials defined in ``.env`` / the pipeline defaults are
    honoured no matter how mcq_generator is entered -- CLI, server route, or a
    direct ``import mcq_generator``.
    """
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


# Load credentials at import time, before any lazy pipeline/bank import below.
_load_dotenv(REPO_ROOT / ".env")

# Question types that are NOT already structured MCQs.  Everything outside the
# {MCQ, Assertion-Reason} families is fair game for conversion.  (Assertion-
# Reason rows already carry their own option scaffold, so we leave them alone.)
THEORY_TYPES = {
    "short answer", "long answer", "conceptual", "exercise question",
    "practice question", "fill in the blanks", "true/false", "case study",
    "illustration question", "diagram based", "activity based", "formula based",
    "hots", "match the following", "numerical",
}

# Crude detector for "this question already lists (a)/(b)/(c)/(d) options".
_INLINE_OPT_RE = re.compile(r"(?m)(?:^|\n)\s*\(?[a-dA-D1-4][\).]\s+\S")

OLLAMA_NUM_PREDICT = int(os.environ.get("MCQ_OLLAMA_NUM_PREDICT", "2048"))


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------
def is_theory_type(question_type: str) -> bool:
    return (question_type or "").strip().lower() in THEORY_TYPES


def looks_like_mcq(question: str) -> bool:
    """True when the stem already embeds at least two lettered/numbered options
    -- such rows are already MCQ-shaped and don't need generating."""
    if not question:
        return False
    return len(_INLINE_OPT_RE.findall(question)) >= 2


def needs_conversion(question_type: str, question: str) -> bool:
    """A row is worth converting when it's a theory type and not already an
    inline-options MCQ."""
    return is_theory_type(question_type) and not looks_like_mcq(question)


# ---------------------------------------------------------------------------
# Ollama plumbing (reuses the pipeline's client + JSON extractor)
# ---------------------------------------------------------------------------
_CLIENT = None  # lazily-built, reused across calls in a process


def _get_client():
    global _CLIENT
    if _CLIENT is None:
        from topicwise_pipeline import OllamaClient  # lazy: heavy import
        client = OllamaClient()
        client.ensure_model()  # raises a clear error if Ollama/model is missing
        _CLIENT = client
    return _CLIENT


def health() -> Dict[str, Any]:
    """Report whether Ollama (and the configured model) is reachable.  Never
    raises -- mirrors ``bank_read.health`` so the UI can show a soft state."""
    try:
        from topicwise_pipeline import OLLAMA_BASE_URL, OLLAMA_MODEL, OllamaClient
        client = OllamaClient()
        client.ensure_model()
        return {"ollama_ok": True, "model": client.model, "base_url": OLLAMA_BASE_URL}
    except Exception as exc:  # pragma: no cover - environment dependent
        try:
            from topicwise_pipeline import OLLAMA_BASE_URL, OLLAMA_MODEL
            return {"ollama_ok": False, "error": str(exc),
                    "model": OLLAMA_MODEL, "base_url": OLLAMA_BASE_URL}
        except Exception:
            return {"ollama_ok": False, "error": str(exc)}


_SYSTEM_PROMPT = (
    "You are an expert exam author for Indian school 'IIT Foundation' science and "
    "maths (classes 6-10). You turn an open-ended/theory question and its model "
    "answer into ONE high-quality, single-correct-answer multiple-choice question "
    "(MCQ) suitable for a timed test.\n\n"
    "Rules:\n"
    "1. The MCQ must test the SAME core concept as the source question.\n"
    "2. Provide EXACTLY four options. Exactly one is unambiguously correct; it must "
    "follow from the given model answer.\n"
    "3. The other three are plausible but clearly wrong distractors (common "
    "misconceptions, near-miss values, or related-but-incorrect terms).\n"
    "4. Keep options short, parallel in form, and mutually exclusive. Do NOT use "
    "'All of the above' / 'None of the above'.\n"
    "5. Rephrase a vague or multi-part prompt into a crisp, self-contained question "
    "with a definite answer. Preserve any numbers/units/formulae faithfully.\n"
    "6. Vary which position holds the correct option.\n"
    "7. If the source genuinely cannot become a fair single-answer MCQ (e.g. 'draw "
    "a diagram', 'write an essay', purely subjective), set convertible=false.\n\n"
    "Respond with ONLY a JSON object, no prose, in exactly this shape:\n"
    '{"convertible": true, "stem": "<question>", '
    '"options": ["<opt1>", "<opt2>", "<opt3>", "<opt4>"], '
    '"correct_index": <0-3>, "explanation": "<one-sentence why>"}'
)


def _build_user_prompt(question: str, answer: str, subject: str, chapter: str,
                       question_type: str) -> str:
    parts = []
    if subject:
        parts.append(f"Subject: {subject}")
    if chapter:
        parts.append(f"Chapter: {chapter}")
    if question_type:
        parts.append(f"Original type: {question_type}")
    head = ("\n".join(parts) + "\n\n") if parts else ""
    ans = (answer or "").strip() or "(no model answer provided — infer the correct answer yourself)"
    return (
        f"{head}Source question:\n{(question or '').strip()}\n\n"
        f"Model answer:\n{ans}\n\n"
        "Convert this into one MCQ following all the rules."
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _clean_opt(o: Any) -> str:
    s = str(o or "").strip()
    # Strip a leading "A) " / "(b) " / "1. " label if the model added one.
    s = re.sub(r"^\(?[A-Da-d1-4][\).]\s+", "", s).strip()
    return s


def _validate_mcq(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Coerce + validate a model response into a clean MCQ dict, or None if it
    is unusable / flagged non-convertible."""
    if not isinstance(raw, dict):
        return None
    if raw.get("convertible") is False:
        return None
    stem = str(raw.get("stem") or "").strip()
    opts_in = raw.get("options") or []
    if not stem or not isinstance(opts_in, list):
        return None
    options = [_clean_opt(o) for o in opts_in]
    options = [o for o in options if o]
    # Need exactly 4 distinct options (case-insensitive de-dupe).
    seen, uniq = set(), []
    for o in options:
        k = o.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    if len(uniq) != 4:
        return None
    try:
        ci = int(raw.get("correct_index"))
    except (TypeError, ValueError):
        return None
    # correct_index refers to the ORIGINAL option order; remap onto de-duped list.
    if not (0 <= ci < len(options)):
        return None
    correct_text = options[ci]
    try:
        ci = uniq.index(correct_text)
    except ValueError:
        return None
    return {
        "stem": stem,
        "options": uniq,
        "correct_index": ci,
        "explanation": str(raw.get("explanation") or "").strip(),
    }


# ---------------------------------------------------------------------------
# Public conversion API
# ---------------------------------------------------------------------------
def theory_to_mcq(question: str, answer: str = "", subject: str = "",
                  chapter: str = "", question_type: str = "") -> Dict[str, Any]:
    """Convert a single theory question into an MCQ via Ollama.

    Returns ``{"ok": True, "mcq": {...}}`` on success, or
    ``{"ok": False, "reason": "<why>"}`` when the model declined / produced an
    invalid result.  Raises only when Ollama itself is unreachable.
    """
    if not (question or "").strip():
        return {"ok": False, "reason": "empty question"}

    from topicwise_pipeline import _extract_json_from_llm_text  # lazy

    client = _get_client()
    payload = {
        "model": client.model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(
                question, answer, subject, chapter, question_type)},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.4, "num_predict": OLLAMA_NUM_PREDICT},
    }

    import requests
    from topicwise_pipeline import OLLAMA_RETRIES, OLLAMA_TIMEOUT

    last_err: Optional[Exception] = None
    for attempt in range(OLLAMA_RETRIES):
        try:
            resp = requests.post(f"{client.base_url}/api/chat", json=payload,
                                 timeout=OLLAMA_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            message = data.get("message", {})
            content = (message.get("content") or "").strip() or (message.get("thinking") or "").strip()
            if not content:
                raise ValueError(f"empty model response (done_reason={data.get('done_reason')})")
            parsed = _extract_json_from_llm_text(content)
            mcq = _validate_mcq(parsed)
            if mcq is None:
                return {"ok": False, "reason": "not convertible to a fair MCQ"}
            return {"ok": True, "mcq": mcq}
        except (json.JSONDecodeError, ValueError, requests.RequestException, KeyError) as exc:
            last_err = exc
            if attempt + 1 < OLLAMA_RETRIES:
                time.sleep(2)
    return {"ok": False, "reason": f"generation failed: {last_err}"}


def convert_items(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Batch-convert a list of ``{question, answer, subject, chapter,
    question_type, id?}`` dicts.  Returns ``{"mcqs": [...], "errors": [...]}``;
    each MCQ echoes the source ``id`` (when given) so callers can match them up.
    """
    mcqs: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for it in items:
        res = theory_to_mcq(
            it.get("question", "") or it.get("stem", ""),
            it.get("answer", ""),
            it.get("subject", ""),
            it.get("chapter", "") or it.get("chapter_name", ""),
            it.get("question_type", ""),
        )
        if res.get("ok"):
            out = dict(res["mcq"])
            if it.get("id") is not None:
                out["source_id"] = it["id"]
            if it.get("subject"):
                out["subject"] = it["subject"]
            chap = it.get("chapter") or it.get("chapter_name")
            if chap:
                out["chapter"] = chap
            if it.get("question_type"):
                out["source_type"] = it["question_type"]
            mcqs.append(out)
        else:
            errors.append({"id": it.get("id"), "reason": res.get("reason", "unknown")})
    return {"mcqs": mcqs, "errors": errors}


def convert_bank_item(item_id: int) -> Dict[str, Any]:
    """Fetch one bank row by id and convert it.  Returns the same shape as
    ``theory_to_mcq`` (plus ``source_id``)."""
    import bank_read
    detail = bank_read.get_item(item_id)
    if not detail:
        return {"ok": False, "reason": f"item #{item_id} not found"}
    item = detail["item"]
    res = theory_to_mcq(item.get("stem", ""), item.get("answer", ""),
                        item.get("subject", ""), item.get("chapter_name", ""),
                        item.get("question_type", ""))
    if res.get("ok"):
        res["mcq"]["source_id"] = item_id
        res["mcq"]["subject"] = item.get("subject", "")
        res["mcq"]["chapter"] = item.get("chapter_name", "")
    return res


# ---------------------------------------------------------------------------
# CLI: batch-convert theory questions straight from the question bank
# ---------------------------------------------------------------------------
def _iter_theory_bank_items(filters: Dict[str, Any], cap: int) -> List[Dict[str, Any]]:
    """Page through the bank, keeping only theory rows that need conversion."""
    import bank_read
    out: List[Dict[str, Any]] = []
    page, page_size = 1, 100
    while len(out) < cap:
        res = bank_read.search_items({**filters, "page": page, "pageSize": page_size})
        items = res.get("items", [])
        if not items:
            break
        for it in items:
            if needs_conversion(it.get("question_type", ""), it.get("stem", "")):
                out.append(it)
                if len(out) >= cap:
                    break
        if page * page_size >= int(res.get("total", 0)):
            break
        page += 1
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Convert theory questions in the bank into MCQs via Ollama.")
    ap.add_argument("--subject", action="append", default=[], help="filter by subject (repeatable)")
    ap.add_argument("--class", dest="klass", action="append", default=[], help="filter by class (repeatable)")
    ap.add_argument("--chapter", action="append", default=[], help="filter by chapter_id (repeatable)")
    ap.add_argument("--type", action="append", default=[], help="filter by question_type (repeatable)")
    ap.add_argument("--list-chapters", action="store_true", help="list chapter ids for the chosen subject/class, then exit")
    ap.add_argument("--limit", type=int, default=20, help="max questions to convert")
    ap.add_argument("--out", default="outputs/generated_mcqs.json", help="output JSON path")
    args = ap.parse_args(argv)

    # .env is already loaded at import time; re-apply here in case the file was
    # created/edited after this module was first imported (idempotent: setdefault
    # never overrides values already present in the environment).
    _load_dotenv(REPO_ROOT / ".env")

    filters: Dict[str, Any] = {}
    if args.subject:
        filters["subject"] = args.subject
    if args.klass:
        filters["class"] = args.klass
    if args.chapter:
        filters["chapter"] = args.chapter
    if args.type:
        filters["type"] = args.type

    # Helper: print the chapter ids available for the chosen subject/class so the
    # user can pick the right --chapter value (chapters are keyed by id, not name).
    # Doesn't need Ollama -- pure bank read.
    if args.list_chapters:
        import bank_read
        facets = bank_read.compute_facets(filters)
        chapters = facets.get("chapter", [])
        if not chapters:
            print("No chapters found for that filter.")
        for ch in chapters:
            print(f"  --chapter {ch['value']}   {ch.get('label','')}  ({ch['count']} questions)")
        return 0

    h = health()
    if not h.get("ollama_ok"):
        print(f"Ollama not reachable: {h.get('error')}", file=sys.stderr)
        return 2
    print(f"Using Ollama model: {h.get('model')}")

    try:
        candidates = _iter_theory_bank_items(filters, args.limit)
    except Exception as exc:
        print(f"Could not read the question bank: {exc}", file=sys.stderr)
        return 2
    print(f"Found {len(candidates)} theory question(s) to convert.")

    items = [{
        "id": it["id"], "question": it.get("stem", ""),
        "subject": it.get("subject", ""), "chapter_name": it.get("chapter_name", ""),
        "question_type": it.get("question_type", ""),
    } for it in candidates]

    # Pull model answers (the bank summary omits them).
    import bank_read
    for src in items:
        try:
            d = bank_read.get_item(src["id"])
            src["answer"] = ((d or {}).get("item") or {}).get("answer", "")
        except Exception:
            src["answer"] = ""

    result = {"mcqs": [], "errors": []}
    for i, src in enumerate(items, 1):
        print(f"[{i}/{len(items)}] #{src['id']} ({src['question_type']}) … ", end="", flush=True)
        one = convert_items([src])
        result["mcqs"].extend(one["mcqs"])
        result["errors"].extend(one["errors"])
        print("ok" if one["mcqs"] else f"skip ({one['errors'][0]['reason'] if one['errors'] else '?'})")

    out_path = args.out
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(result['mcqs'])} MCQ(s) ({len(result['errors'])} skipped) -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
