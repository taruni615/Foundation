"""Recompute arithmetic MCQs and correct answer keys that are provably wrong.

The bank's stored answer letter is wrong on an unknown number of questions --
"Find 4+3" is keyed (C) 6 rather than (A) 7. Most of those need the question
solved to detect, but a large family does not: when the question *is* an
arithmetic expression, Python can evaluate it and check which option it equals.
That is exact, free, and needs no model.

Scope, deliberately narrow:

* the question must reduce to a single arithmetic expression;
* the expression must evaluate without error;
* **exactly one** option must equal the result.

A question failing any of those is reported, never guessed at. Expressions are
evaluated through an AST whitelist (numbers and the five arithmetic operators
only) -- never ``eval`` on bank text.

Usage::

    python tools/export/verify_arithmetic.py                 # report only
    python tools/export/verify_arithmetic.py --apply         # write corrections
"""

from __future__ import annotations

import argparse
import ast
import html
import json
import operator
import re
from collections import Counter, OrderedDict
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_IN = "exports/questions/flat/all_questions_flat.json"
DEFAULT_OUT = "exports/questions/arithmetic_corrections.json"

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Unicode maths operators the OCR emits, mapped to Python syntax.
_NORMALISE = {
    "×": "*", "⋅": "*", "∙": "*", "·": "*",
    "÷": "/", "∕": "/",
    "−": "-", "–": "-", "—": "-",
    "⁄": "/",
}
# Words that introduce the expression; stripped before parsing.
_LEAD = re.compile(
    r"^\s*(?:find|calculate|compute|evaluate|solve|simplify|what\s+is|"
    r"the\s+value\s+of|value\s+of|determine)\b[\s:：]*",
    re.IGNORECASE,
)
_EXPR = re.compile(r"^[\s0-9+\-*/().]+$")
_TRAILING_QUESTION = re.compile(
    r"\.?\s*(?:what\s+is\s+the\s+result|what\s+do\s+you\s+get|"
    r"what\s+is\s+the\s+answer)\s*\??\s*$",
    re.IGNORECASE,
)


def plain(text: str) -> str:
    """Tag-stripped, entity-decoded text with maths operators normalised."""
    stripped = re.sub(r"<[^>]+>", "", text or "")
    out = html.unescape(stripped)
    for source, target in _NORMALISE.items():
        out = out.replace(source, target)
    return re.sub(r"\s+", " ", out).strip()


def safe_eval(expression: str) -> Optional[Fraction]:
    """Evaluate an arithmetic expression through an AST whitelist.

    Exact rational arithmetic, so 1/3 does not drift and comparisons against
    option values stay reliable. Returns None for anything not purely numeric.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None

    def walk(node: ast.AST) -> Fraction:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("non-numeric constant")
            return Fraction(str(node.value))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                raise ZeroDivisionError
            if isinstance(node.op, ast.Pow) and (right > 64 or right != int(right)):
                raise ValueError("unsupported exponent")
            return _OPS[type(node.op)](left, right)
        raise ValueError(f"disallowed node {type(node).__name__}")

    try:
        return walk(tree)
    except (ValueError, ZeroDivisionError, TypeError, OverflowError):
        return None


def question_expression(question: str) -> Optional[str]:
    """The arithmetic expression a question reduces to, or None."""
    text = plain(question)
    text = _TRAILING_QUESTION.sub("", text)
    candidates = [_LEAD.sub("", text).strip()]
    # "Find the product by suitable rearrangement: 25*60*4*150" -- the prose is
    # instructions, the expression is whatever follows the last colon.
    if ":" in text:
        candidates.append(text.rsplit(":", 1)[1].strip())
    for candidate in candidates:
        candidate = candidate.rstrip(" .?=")
        if not candidate or not _EXPR.fullmatch(candidate):
            continue
        # Needs an operator between two numbers to be worth computing.
        if not re.search(r"\d\s*[+\-*/]\s*[\d(]", candidate):
            continue
        return candidate
    return None


# "Find the HCF of 1624, 522 and 1276." / "the LCM of 12, 30 and 81"
_HCF_LCM = re.compile(
    r"\b(?P<kind>h\.?c\.?f\.?|g\.?c\.?d\.?|highest\s+common\s+factor"
    r"|l\.?c\.?m\.?|lowest\s+common\s+multiple|least\s+common\s+multiple)\b"
    r"[^0-9]{0,20}(?P<numbers>\d[\d\s,and]*\d)",
    re.IGNORECASE,
)


def number_theory_value(question: str) -> Optional[Tuple[str, Fraction]]:
    """Result of an HCF/LCM question, or None when it isn't one."""
    text = plain(question)
    match = _HCF_LCM.search(text)
    if not match:
        return None
    numbers = [int(n) for n in re.findall(r"\d+", match.group("numbers"))]
    if len(numbers) < 2 or any(n <= 0 for n in numbers):
        return None
    kind = match.group("kind").lower().replace(".", "")
    import math

    if kind.startswith(("h", "g")) or "factor" in kind:
        value = numbers[0]
        for n in numbers[1:]:
            value = math.gcd(value, n)
        return f"HCF{tuple(numbers)}", Fraction(value)
    value = numbers[0]
    for n in numbers[1:]:
        value = value * n // math.gcd(value, n)
    return f"LCM{tuple(numbers)}", Fraction(value)


def option_value(text: str) -> Optional[Fraction]:
    """The single number an option denotes, or None when it isn't one."""
    body = plain(text).strip().rstrip(".")
    if not body:
        return None
    fraction = re.fullmatch(r"(-?\d+)\s*/\s*(\d+)", body)
    if fraction:
        denominator = int(fraction.group(2))
        return Fraction(int(fraction.group(1)), denominator) if denominator else None
    if not re.fullmatch(r"-?\d[\d,]*(?:\.\d+)?", body):
        return None
    return Fraction(body.replace(",", ""))


def check(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Verdict for one question, or None when it is out of scope."""
    options = row.get("options") or []
    if len(options) < 2:
        return None
    expression = question_expression(row.get("question", ""))
    result = safe_eval(expression) if expression is not None else None
    if result is None:
        number_theory = number_theory_value(row.get("question", ""))
        if number_theory is None:
            return None
        expression, result = number_theory

    matches = [o["id"] for o in options if option_value(o.get("text", "")) == result]
    values = [option_value(o.get("text", "")) for o in options]
    if any(v is None for v in values):
        return {"status": "non-numeric options", "expression": expression}
    if len(matches) != 1:
        return {
            "status": "no unique matching option" if not matches
            else "several options match",
            "expression": expression,
            "computed": str(result),
        }

    correct = matches[0]
    stored = row.get("answer") or ""
    if not stored:
        status = "supplies missing key"
    elif stored == correct:
        status = "confirms stored key"
    else:
        status = "CORRECTS stored key"
    return {
        "status": status,
        "expression": expression,
        "computed": str(result),
        "correct": correct,
        "stored": stored,
    }


def computed_answer(question: str, options: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Verdict from computing the question, for use by the export pipeline.

    Returns ``{"answer": "<id>"}`` when the arithmetic picks exactly one option,
    ``{"unverifiable": "<reason>"}`` when the question computes but no option
    equals the result (the question itself is broken -- its stored key and its
    stored explanation are both untrustworthy), or None when out of scope.
    """
    verdict = check({"question": question, "options": options, "answer": ""})
    if verdict is None:
        return None
    if verdict["status"] in ("CORRECTS stored key", "supplies missing key",
                             "confirms stored key"):
        return {"answer": verdict["correct"], "computed": verdict["computed"]}
    if verdict["status"] in ("no unique matching option", "several options match"):
        return {"unverifiable": verdict["status"],
                "computed": verdict.get("computed", "")}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", default=DEFAULT_IN)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--apply", action="store_true",
                        help="write corrected answers back into the input file")
    args = parser.parse_args()

    source = Path(args.src)
    with source.open(encoding="utf-8") as handle:
        data = json.load(handle)
    rows = data["questions"] if isinstance(data, dict) else data

    stats: Counter = Counter()
    findings: List[Dict[str, Any]] = []
    corrections: Dict[Any, Tuple[str, str]] = {}

    for row in rows:
        verdict = check(row)
        if verdict is None:
            continue
        stats[verdict["status"]] += 1
        if verdict["status"] in ("CORRECTS stored key", "supplies missing key"):
            corrections[row["question_id"]] = (verdict.get("stored", ""), verdict["correct"])
            findings.append(OrderedDict([
                ("question_id", row["question_id"]),
                ("status", verdict["status"]),
                ("question", plain(row["question"])[:120]),
                ("expression", verdict["expression"]),
                ("computed", verdict["computed"]),
                ("stored_answer", verdict.get("stored", "")),
                ("correct_answer", verdict["correct"]),
                ("options", {o["id"]: plain(o["text"])[:30] for o in row["options"]}),
                ("class", row.get("class")), ("subject", row.get("subject")),
            ]))

    print(f"Arithmetic questions examined: {sum(stats.values())}")
    for status, n in stats.most_common():
        print(f"  {n:5d}  {status}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        json.dump(OrderedDict([
            ("examined", sum(stats.values())),
            ("summary", OrderedDict(stats.most_common())),
            ("findings", findings),
        ]), handle, ensure_ascii=False, indent=2)
    print(f"Wrote {out} ({len(findings)} answers to change)")

    for finding in findings[:12]:
        print(f"  id={finding['question_id']}  {finding['expression']} = "
              f"{finding['computed']}  stored={finding['stored_answer'] or '-'} "
              f"-> {finding['correct_answer']}   {finding['options']}")

    if args.apply and corrections:
        changed = 0
        for row in rows:
            pair = corrections.get(row.get("question_id"))
            if not pair:
                continue
            was, now = pair
            row["answer"] = now
            if was and was != now:
                row["answer_corrected_from"] = was
            row["answer_source"] = "computed"
            changed += 1
        with source.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        print(f"Applied {changed} corrections to {source}")
    elif corrections:
        print("Re-run with --apply to write these corrections.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
