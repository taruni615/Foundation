#!/usr/bin/env python3
"""Similar-MCQ generator ("more like this") -- Ollama-powered.

Where ``mcq_generator.py`` turns *theory* questions into brand-new MCQs, this
script does the complementary job: it takes the MCQs that ALREADY exist in the
bank (``qa_content_row`` rows whose ``question_type`` is ``MCQ``) and asks the
local Ollama model to generate fresh, *similar* MCQs -- same chapter, same
concept area, same difficulty, same single-correct 4-option format -- WITHOUT
parroting the original.

Every generated item inherits all the attributes of its source row so the new
questions are drop-in compatible with the existing bank:

    subject, class, board, book_slug, chapter_id, chapter_name,
    question_type ("MCQ"), difficulty, source_id

It also renders each new MCQ back into the bank's native storage shape
(``bank_question`` with embedded ``(a)..(d)`` options + ``bank_answer`` starting
with the correct letter) so the output could later be inserted into
``qa_content_row`` unchanged -- but this script itself is **read-only**: it only
reads the bank and writes a JSON file. Nothing in the DB or the app is modified.

Design: reuses ``mcq_generator``'s Ollama client, JSON extraction, and MCQ
validation, and ``mcq_generator``'s import-time ``.env`` loading (so DB +
Ollama credentials from ``.env`` / ``topicwise_pipeline`` are honoured).

CLI examples::

    # list chapters so you can pick one
    python mcq_similar.py --subject Physics --class 10 --list-chapters

    # 2 similar MCQs for each existing MCQ in chapter 178, cap 25 sources
    python mcq_similar.py --subject Physics --class 10 --chapter 178 \\
        --per-item 2 --limit 25 --out outputs/similar_mcqs.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from typing import Any, Dict, List, Optional

# Reuse all the plumbing from the sibling module.  Importing it also loads .env
# at import time (before any lazy topicwise_pipeline / bank_read import below).
import mcq_generator as mg

# ---------------------------------------------------------------------------
# Parsing existing MCQ rows (stem + (a)..(d) options + correct letter)
# ---------------------------------------------------------------------------
# An option line: "(a) text", "a) text", "a. text", "1) text", optionally
# indented.  We anchor at line starts so option text inside the stem is ignored.
_OPT_LINE_RE = re.compile(r"(?m)^\s*\(?([a-dA-D1-4])[\).]\s*(.+?)\s*$")
# Leading correct-answer marker in the answer field, e.g. "(b) ...", "b)", "B.".
_ANS_LETTER_RE = re.compile(r"^\s*\(?([a-dA-D1-4])[\).]?")

_LETTER_TO_IDX = {"a": 0, "b": 1, "c": 2, "d": 3,
                  "1": 0, "2": 1, "3": 2, "4": 3}


def parse_existing_mcq(question: str, answer: str) -> Optional[Dict[str, Any]]:
    """Parse a stored MCQ row into ``{stem, options[4], correct_index}``.

    Returns ``None`` when the row doesn't actually carry four parseable options
    (so it can be skipped rather than fed to the model malformed).
    """
    q = (question or "").strip()
    if not q:
        return None

    matches = list(_OPT_LINE_RE.finditer(q))
    if len(matches) < 4:
        return None
    # Keep the last 4 well-formed option lines (some stems contain (i)/(ii)
    # sub-parts earlier; the real options are the trailing block).
    matches = matches[-4:]
    options = [m.group(2).strip() for m in matches]
    if any(not o for o in options):
        return None
    letters = [m.group(1).lower() for m in matches]

    stem = q[: matches[0].start()].strip()
    if not stem:
        return None

    # Correct index: prefer the leading letter in the answer field.
    ci: Optional[int] = None
    a = (answer or "").strip()
    m = _ANS_LETTER_RE.match(a)
    if m:
        want = m.group(1).lower()
        # Map the answer letter onto the position of that letter in this row's
        # option markers (handles rows whose markers are out of order).
        if want in letters:
            ci = letters.index(want)
        elif want in _LETTER_TO_IDX and _LETTER_TO_IDX[want] < len(options):
            ci = _LETTER_TO_IDX[want]
    # Fallback: match the answer text against an option.
    if ci is None and a:
        a_norm = re.sub(r"^\s*\(?[a-dA-D1-4][\).]\s*", "", a).strip().lower()
        for i, o in enumerate(options):
            if a_norm and (a_norm.startswith(o.lower()) or o.lower().startswith(a_norm[:40])):
                ci = i
                break
    if ci is None:
        return None
    return {"stem": stem, "options": options, "correct_index": ci}


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------
_SIMILAR_SYSTEM_PROMPT = (
    "You are an expert exam author for Indian school 'IIT Foundation' science and "
    "maths (classes 6-10). Given ONE sample multiple-choice question, you write "
    "NEW multiple-choice questions that are SIMILAR to it.\n\n"
    "Rules:\n"
    "1. Each new MCQ must test the SAME chapter/topic and the SAME concept family "
    "as the sample, at the SAME difficulty level.\n"
    "2. Do NOT reword, paraphrase, or merely reshuffle the sample's options. Create "
    "genuinely new questions (different scenario, numbers, or angle) on the topic.\n"
    "3. Provide EXACTLY four options per question. Exactly one is unambiguously "
    "correct; the other three are plausible distractors (common misconceptions, "
    "near-miss values, related-but-wrong terms).\n"
    "4. Keep options short, parallel in form, and mutually exclusive. Do NOT use "
    "'All of the above' / 'None of the above'.\n"
    "5. Preserve any units/formula conventions the sample uses. Vary which position "
    "holds the correct option across the set.\n\n"
    "Respond with ONLY a JSON object, no prose, in exactly this shape:\n"
    '{"mcqs": [{"stem": "<q>", "options": ["<o1>","<o2>","<o3>","<o4>"], '
    '"correct_index": <0-3>, "explanation": "<one-sentence why>"}]}'
)


def _build_similar_prompt(parsed: Dict[str, Any], subject: str, chapter: str,
                          difficulty: str, n: int) -> str:
    opt_lines = "\n".join(
        f"({chr(97 + i)}) {o}" for i, o in enumerate(parsed["options"])
    )
    correct = parsed["options"][parsed["correct_index"]]
    parts = []
    if subject:
        parts.append(f"Subject: {subject}")
    if chapter:
        parts.append(f"Chapter: {chapter}")
    if difficulty:
        parts.append(f"Difficulty: {difficulty}")
    head = ("\n".join(parts) + "\n\n") if parts else ""
    return (
        f"{head}Sample MCQ:\n{parsed['stem']}\n{opt_lines}\n"
        f"Correct answer: {correct}\n\n"
        f"Write {n} NEW MCQ(s) similar to this sample, following all the rules."
    )


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def similar_mcqs(parsed: Dict[str, Any], subject: str = "", chapter: str = "",
                 difficulty: str = "", n: int = 2) -> Dict[str, Any]:
    """Generate ``n`` MCQs similar to a parsed sample.

    Returns ``{"ok": True, "mcqs": [...]}`` (each validated) or
    ``{"ok": False, "reason": ...}``.  Raises only if Ollama is unreachable.
    """
    from topicwise_pipeline import _extract_json_from_llm_text  # lazy

    client = mg._get_client()
    payload = {
        "model": client.model,
        "messages": [
            {"role": "system", "content": _SIMILAR_SYSTEM_PROMPT},
            {"role": "user", "content": _build_similar_prompt(
                parsed, subject, chapter, difficulty, n)},
        ],
        "stream": False,
        "format": "json",
        # Higher temperature than conversion -> more variety between siblings.
        "options": {"temperature": 0.8, "num_predict": mg.OLLAMA_NUM_PREDICT},
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
            parsed_out = _extract_json_from_llm_text(content)
            raw_list = parsed_out.get("mcqs") if isinstance(parsed_out, dict) else None
            if not isinstance(raw_list, list):
                # Model may have returned a single MCQ object.
                raw_list = [parsed_out] if isinstance(parsed_out, dict) else []
            mcqs: List[Dict[str, Any]] = []
            src_stem = parsed["stem"].strip().lower()
            for raw in raw_list:
                mcq = mg._validate_mcq(raw)
                if mcq is None:
                    continue
                # Drop near-duplicates of the source stem.
                if mcq["stem"].strip().lower() == src_stem:
                    continue
                mcqs.append(mcq)
            if not mcqs:
                return {"ok": False, "reason": "no valid similar MCQs produced"}
            return {"ok": True, "mcqs": mcqs}
        except (json.JSONDecodeError, ValueError, requests.RequestException, KeyError) as exc:
            last_err = exc
            if attempt + 1 < OLLAMA_RETRIES:
                time.sleep(2)
    return {"ok": False, "reason": f"generation failed: {last_err}"}


# ---------------------------------------------------------------------------
# Rendering back into the bank's native storage shape
# ---------------------------------------------------------------------------
def _render_bank_fields(mcq: Dict[str, Any]) -> Dict[str, str]:
    """Render a clean MCQ dict into ``qa_content_row``-style question/answer
    text (embedded ``(a)..(d)`` options; answer prefixed with the letter)."""
    letters = "abcd"
    opt_block = "\n".join(
        f"({letters[i]}) {o}" for i, o in enumerate(mcq["options"])
    )
    question = f"{mcq['stem']}\n{opt_block}"
    letter = letters[mcq["correct_index"]]
    expl = (mcq.get("explanation") or "").strip()
    answer = f"({letter}) {expl}".strip()
    return {"bank_question": question, "bank_answer": answer}


def _attach_attributes(mcq: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    """Copy every source attribute onto a generated MCQ + render bank fields."""
    out = dict(mcq)
    out["question_type"] = "MCQ"
    out["source_id"] = src.get("id")
    out["subject"] = src.get("subject", "")
    out["class"] = src.get("class", "")
    out["board"] = src.get("board", "")
    out["book_slug"] = src.get("book_slug", "")
    out["chapter_id"] = src.get("chapter_id")
    out["chapter_name"] = src.get("chapter_name", "")
    out["difficulty"] = src.get("difficulty", "")
    out.update(_render_bank_fields(out))
    return out


# ---------------------------------------------------------------------------
# Reading existing MCQ rows from the bank (honours the same filters as bank_read)
# ---------------------------------------------------------------------------
def _fetch_source_mcqs(filters: Dict[str, Any], cap: int) -> List[Dict[str, Any]]:
    """Fetch up to ``cap`` existing MCQ rows (with full attributes) matching the
    subject/class/board/chapter filters, reusing bank_read's filter semantics."""
    import bank_read

    f = bank_read.normalize_filters(filters)
    with bank_read._connect() as conn:
        with conn.cursor() as cur:
            slug_attrs = bank_read._slug_attr_map(cur)
            where, params = bank_read._build_where(slug_attrs, f)
            cur.execute(
                "SELECT id, book_slug, chapter_id, chapter_name, question, answer, "
                "question_type FROM qa_content_row WHERE " + where +
                " ORDER BY id ASC LIMIT %s",
                params + [cap],
            )
            rows = cur.fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        attrs = bank_read.derive_attributes(r["book_slug"])
        out.append({
            "id": r["id"],
            "book_slug": r["book_slug"],
            "chapter_id": r.get("chapter_id"),
            "chapter_name": r.get("chapter_name") or "",
            "question": r.get("question") or "",
            "answer": r.get("answer") or "",
            "question_type": r.get("question_type") or "",
            "subject": attrs["subject"],
            "class": attrs["class"],
            "board": attrs["board"],
            "difficulty": bank_read.estimate_difficulty(
                r.get("question"), r.get("question_type")),
        })
    return out


# ---------------------------------------------------------------------------
# Public batch API
# ---------------------------------------------------------------------------
def generate_from_sources(sources: List[Dict[str, Any]], per_item: int = 2
                          ) -> Dict[str, Any]:
    """For each source MCQ row, parse it and generate ``per_item`` similar MCQs.

    Returns ``{"mcqs": [...], "errors": [...]}``; each generated MCQ carries all
    source attributes + rendered bank fields.
    """
    mcqs: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for src in sources:
        parsed = parse_existing_mcq(src.get("question", ""), src.get("answer", ""))
        if parsed is None:
            errors.append({"id": src.get("id"), "reason": "could not parse source MCQ"})
            continue
        res = similar_mcqs(
            parsed,
            subject=src.get("subject", ""),
            chapter=src.get("chapter_name", ""),
            difficulty=src.get("difficulty", ""),
            n=per_item,
        )
        if res.get("ok"):
            for mcq in res["mcqs"]:
                mcqs.append(_attach_attributes(mcq, src))
        else:
            errors.append({"id": src.get("id"), "reason": res.get("reason", "unknown")})
    return {"mcqs": mcqs, "errors": errors}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate new MCQs similar to existing bank MCQs via Ollama.")
    ap.add_argument("--subject", action="append", default=[], help="filter by subject (repeatable)")
    ap.add_argument("--class", dest="klass", action="append", default=[], help="filter by class (repeatable)")
    ap.add_argument("--chapter", action="append", default=[], help="filter by chapter_id (repeatable)")
    ap.add_argument("--source-type", action="append", default=[],
                    help="source question_type(s) to draw from (default: MCQ)")
    ap.add_argument("--list-chapters", action="store_true",
                    help="list chapter ids for the chosen subject/class, then exit")
    ap.add_argument("--per-item", type=int, default=2, help="similar MCQs to make per source (default 2)")
    ap.add_argument("--limit", type=int, default=20, help="max source MCQs to draw from")
    ap.add_argument("--out", default="outputs/similar_mcqs.json", help="output JSON path")
    args = ap.parse_args(argv)

    # .env already loaded when `mcq_generator` was imported; re-apply in case the
    # file was created/edited after import (idempotent setdefault).
    mg._load_dotenv(mg.REPO_ROOT / ".env")

    filters: Dict[str, Any] = {}
    if args.subject:
        filters["subject"] = args.subject
    if args.klass:
        filters["class"] = args.klass
    if args.chapter:
        filters["chapter"] = args.chapter
    # Default to drawing from real MCQ rows; let --source-type override.
    filters["type"] = args.source_type or ["MCQ"]

    if args.list_chapters:
        import bank_read
        facets = bank_read.compute_facets(filters)
        chapters = facets.get("chapter", [])
        if not chapters:
            print("No chapters found for that filter.")
        for ch in chapters:
            print(f"  --chapter {ch['value']}   {ch.get('label','')}  ({ch['count']} questions)")
        return 0

    h = mg.health()
    if not h.get("ollama_ok"):
        print(f"Ollama not reachable: {h.get('error')}", file=sys.stderr)
        return 2
    print(f"Using Ollama model: {h.get('model')}")

    try:
        sources = _fetch_source_mcqs(filters, args.limit)
    except Exception as exc:
        print(f"Could not read the question bank: {exc}", file=sys.stderr)
        return 2

    if not sources:
        print("No matching source MCQs found for that filter.")
        return 0

    print(f"Generating ~{args.per_item} similar MCQ(s) for each of {len(sources)} source MCQ(s)...")
    t0 = time.time()
    result = generate_from_sources(sources, per_item=args.per_item)
    dt = time.time() - t0

    import os
    out_path = args.out
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2, default=str)

    print(f"Done in {dt:.1f}s -> {out_path}")
    print(f"  generated: {len(result['mcqs'])} MCQ(s)")
    print(f"  errors/skipped: {len(result['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
