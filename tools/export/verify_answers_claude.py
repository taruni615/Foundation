"""Independently solve every bank MCQ with Claude and flag wrong answer keys.

The rule-based cross-check in ``flatten_questions`` can only catch a
contradiction when the bank stored an explanation to contradict — 14 of 7,107
questions. Everything else needs the question actually solved. This does that:
Claude answers each MCQ from the stem and options alone, without being shown
the stored key, and its answer is compared afterwards. A disagreement is
reported, never silently applied.

Two execution modes:

``--mode batch`` (default)
    The Message Batches API: 50% cheaper and the right fit for a few thousand
    non-latency-sensitive questions. Results usually land within the hour.

``--mode sync``
    Concurrent live requests. Faster to first result, full price. Use for a
    ``--limit``ed trial run before committing to the whole bank.

Both modes cache per question id in ``--cache``, so a re-run costs nothing for
questions already solved and an interrupted run resumes where it stopped.

Usage::

    export ANTHROPIC_API_KEY=sk-ant-...        # or: ant auth login
    python tools/export/verify_answers_claude.py --mode sync --limit 25   # trial
    python tools/export/verify_answers_claude.py                          # full run
    python tools/export/verify_answers_claude.py --report                 # read cache
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import os
import re
import sys
import threading
import time
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.append(str(Path(__file__).resolve().parents[2]))
sys.path.append(str(Path(__file__).resolve().parent))

DEFAULT_IN = "exports/questions/flat/all_questions_flat.json"
DEFAULT_CACHE = "exports/questions/.claude_answer_cache.json"
DEFAULT_MODEL = "claude-opus-5"
OPTION_IDS = ["A", "B", "C", "D", "E"]

SYSTEM = (
    "You are a meticulous school examiner checking a question bank. "
    "You solve each multiple-choice question yourself and report which option "
    "is correct. You are never shown the bank's stored answer, so do not guess "
    "at what it might be — work the question."
)

PROMPT = """Class {cls} — {subject} — {chapter}

QUESTION:
{question}

OPTIONS:
{options}

Work out the correct option yourself.

- "answer" is the id of the single correct option.
- "confidence" is "high" only when you are certain; use "low" when the question
  is ambiguous, malformed, missing data, or has no correct option among those
  listed.
- "explanation" is 1-3 sentences saying why that option is right, including the
  calculation when the question is numerical.
- If no listed option is correct, set "answer" to the closest one, "confidence"
  to "low", and say so in "explanation".
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "enum": OPTION_IDS},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "explanation": {"type": "string"},
    },
    "required": ["answer", "confidence", "explanation"],
    "additionalProperties": False,
}


def readable(text: str) -> str:
    """Render MathML to plain maths so the prompt is legible and compact."""
    from restructure_questions import mathml_to_text  # same tools/export dir

    return mathml_to_text(text)


def build_prompt(row: Dict[str, Any]) -> str:
    options = "\n".join(
        f"({o['id']}) {readable(o.get('text', ''))}" for o in row.get("options", [])
    )
    return PROMPT.format(
        cls=row.get("class", "?"),
        subject=row.get("subject", "?"),
        chapter=row.get("chapter", "?"),
        question=readable(row.get("question", "")),
        options=options,
    )


def request_params(row: Dict[str, Any], model: str, effort: str,
                   max_tokens: int) -> Dict[str, Any]:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": SYSTEM,
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
        "messages": [{"role": "user", "content": build_prompt(row)}],
    }


def parse_reply(message: Any) -> Optional[Dict[str, Any]]:
    """Pull the JSON object out of a completed message."""
    if getattr(message, "stop_reason", None) == "refusal":
        return None
    text = next(
        (b.text for b in message.content if getattr(b, "type", None) == "text"), ""
    )
    if not text.strip():
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if data.get("answer") not in OPTION_IDS:
        return None
    return data


def select(rows: List[Dict[str, Any]], only_disputed: bool) -> List[Dict[str, Any]]:
    """MCQs that have options — the only rows whose key can be checked."""
    pool = [r for r in rows if r.get("options")]
    if only_disputed:
        pool = [r for r in pool if r.get("answer")]
    return pool


# ---------------------------------------------------------------------------
# Execution modes
# ---------------------------------------------------------------------------
def run_sync(client, todo, cache, cache_path, model, effort, max_tokens, workers):
    lock = threading.Lock()
    done = [0]
    started = time.time()

    def work(row):
        try:
            message = client.messages.create(**request_params(row, model, effort, max_tokens))
            parsed = parse_reply(message)
        except Exception as exc:                      # noqa: BLE001 - log and continue
            parsed, error = None, str(exc)[:200]
        else:
            error = None if parsed else "unparseable reply"
        with lock:
            cache[str(row["question_id"])] = parsed or {"error": error}
            done[0] += 1
            if done[0] % 25 == 0 or done[0] == len(todo):
                rate = done[0] / max(1e-6, time.time() - started)
                print(f"  {done[0]}/{len(todo)}  {rate*60:.0f}/min  "
                      f"eta {(len(todo)-done[0])/max(rate,1e-6)/60:.0f}m", flush=True)
                save_cache(cache_path, cache)

    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, todo))
    save_cache(cache_path, cache)


def run_batch(client, todo, cache, cache_path, model, effort, max_tokens, poll):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    requests = [
        Request(
            custom_id=f"q{row['question_id']}",
            params=MessageCreateParamsNonStreaming(
                **request_params(row, model, effort, max_tokens)
            ),
        )
        for row in todo
    ]
    batch = client.messages.batches.create(requests=requests)
    print(f"  batch {batch.id} submitted with {len(requests)} questions")
    print("  (safe to Ctrl-C — re-run with --resume-batch <id> to collect)")
    collect_batch(client, batch.id, cache, cache_path, poll)


def collect_batch(client, batch_id, cache, cache_path, poll):
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            break
        counts = batch.request_counts
        print(f"  {batch.processing_status}: {counts.succeeded} done, "
              f"{counts.processing} processing, {counts.errored} errored", flush=True)
        time.sleep(poll)

    for result in client.messages.batches.results(batch_id):
        qid = result.custom_id.lstrip("q")
        if result.result.type == "succeeded":
            cache[qid] = parse_reply(result.result.message) or {"error": "unparseable"}
        else:
            cache[qid] = {"error": result.result.type}
    save_cache(cache_path, cache)
    print(f"  collected {len(cache)} results")


def save_cache(path: Path, cache: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def report(rows: List[Dict[str, Any]], cache: Dict[str, Any], out: Path) -> None:
    stats = Counter()
    disagreements = []
    for row in rows:
        entry = cache.get(str(row.get("question_id")))
        if not entry or entry.get("error"):
            stats["not solved"] += 1
            continue
        claude, stored = entry["answer"], row.get("answer")
        stats[f"confidence {entry.get('confidence', '?')}"] += 1
        if not stored:
            stats["no stored key — Claude supplies one"] += 1
            disagreements.append((row, entry, "missing"))
        elif claude == stored:
            stats["agrees with stored key"] += 1
        else:
            stats["DISAGREES with stored key"] += 1
            disagreements.append((row, entry, "conflict"))

    print("\nVerification summary")
    for key, n in stats.most_common():
        print(f"  {n:6d}  {key}")

    payload = OrderedDict([
        ("checked", sum(stats.values())),
        ("summary", OrderedDict(stats.most_common())),
        ("findings", [
            OrderedDict([
                ("question_id", r["question_id"]),
                ("kind", kind),
                ("stored_answer", r.get("answer") or ""),
                ("claude_answer", e["answer"]),
                ("confidence", e.get("confidence")),
                ("claude_explanation", e.get("explanation")),
                ("class", r.get("class")), ("subject", r.get("subject")),
                ("chapter", r.get("chapter")),
            ])
            for r, e, kind in disagreements
        ]),
    ])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(f"\nWrote {out} ({len(disagreements)} findings)")

    conflicts = [d for d in disagreements if d[2] == "conflict"]
    for row, entry, _ in conflicts[:10]:
        print(f"\n  id={row['question_id']}  stored={row.get('answer')} "
              f"claude={entry['answer']} ({entry.get('confidence')})")
        print(f"    {readable(row['question'])[:90]}")
        print(f"    {entry.get('explanation', '')[:150]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", default=DEFAULT_IN)
    parser.add_argument("--cache", default=DEFAULT_CACHE)
    parser.add_argument("--out", default="exports/questions/answer_verification.json")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="high",
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--mode", choices=["batch", "sync"], default="batch")
    parser.add_argument("--workers", type=int, default=8, help="sync mode only")
    parser.add_argument("--poll", type=int, default=60, help="batch poll seconds")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume-batch", default=None,
                        help="collect results from an existing batch id")
    parser.add_argument("--report", action="store_true",
                        help="only summarise the cache; make no API calls")
    parser.add_argument("--keyed-only", action="store_true",
                        help="check only questions that already have a stored key")
    args = parser.parse_args()

    with open(args.src, encoding="utf-8") as handle:
        data = json.load(handle)
    rows = data["questions"] if isinstance(data, dict) else data
    pool = select(rows, args.keyed_only)
    print(f"{len(rows)} questions loaded; {len(pool)} have options and can be checked")

    cache_path = Path(args.cache)
    cache: Dict[str, Any] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"  {len(cache)} already in {cache_path}")

    if args.report:
        report(pool, cache, Path(args.out))
        return 0

    import anthropic

    client = anthropic.Anthropic()

    if args.resume_batch:
        collect_batch(client, args.resume_batch, cache, cache_path, args.poll)
        report(pool, cache, Path(args.out))
        return 0

    todo = [r for r in pool if str(r["question_id"]) not in cache]
    if args.limit is not None:
        todo = todo[: args.limit]
    print(f"  {len(todo)} to solve with {args.model} (effort={args.effort}, "
          f"mode={args.mode})")
    if not todo:
        report(pool, cache, Path(args.out))
        return 0

    if args.mode == "sync":
        run_sync(client, todo, cache, cache_path, args.model, args.effort,
                 args.max_tokens, args.workers)
    else:
        run_batch(client, todo, cache, cache_path, args.model, args.effort,
                  args.max_tokens, args.poll)

    report(pool, cache, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
