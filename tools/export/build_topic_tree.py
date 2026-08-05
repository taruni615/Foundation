"""Explode the flat question export into a Class/Subject/Chapter/Topic tree.

Reads ``exports/questions/flat/all_questions_flat.json`` and writes::

    output/
      Class_6/
        Mathematics/
          Chapter_01_Knowing_Our_Numbers/
            Place_Value.json
            Estimation.json
          Chapter_02_Whole_Numbers/
            Distributive_Property.json

Every topic file carries its own header plus only the questions belonging to
that topic::

    {"class", "subject", "chapter", "chapter_number", "topic",
     "question_count", "questions": [...]}

Questions keep their identity fields (id, text, options, answer, explanation,
difficulty, cognitive level, learning objective, subtopic) and drop the four
fields already stated in the header.

Naming is filesystem-safe: invalid characters removed, spaces to underscores,
SHOUTING headings title-cased, names truncated so Windows' 260-character path
limit is not hit, Windows reserved device names avoided, and collisions within
a folder disambiguated with a numeric suffix.

After writing, every file is read back and the question ids are checked to be a
partition of the input -- each question exactly once, nothing lost, nothing
duplicated.

Usage::

    python tools/export/build_topic_tree.py
    python tools/export/build_topic_tree.py --out-dir exports/output --clean
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.append(str(Path(__file__).resolve().parents[2]))

DEFAULT_IN = "exports/questions/flat/all_questions_flat.json"
DEFAULT_OUT = "exports/output"

# Fields repeated in the file header, so they are dropped from each question.
_HEADER_FIELDS = {"class", "subject", "chapter", "chapter_number", "topic", "book"}
# Order questions are written in, matching the agreed schema.
_QUESTION_ORDER = [
    "question_id", "question_type", "difficulty", "subtopic", "question",
    "options", "answer", "explanation", "cognitive_level", "learning_objective",
]

# Windows forbids these characters anywhere in a path component.
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# ... and these names entirely, with or without an extension.
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

MAX_FOLDER_NAME = 60
MAX_FILE_STEM = 70


def safe_name(value: str, limit: int) -> str:
    """A readable, filesystem-safe path component."""
    text = str(value or "").strip()
    # SHOUTING OCR headings read badly as filenames; title-case them, but leave
    # mixed-case names (and acronyms like LCM inside them) alone.
    if text and text == text.upper() and re.search(r"[A-Z]{4}", text):
        text = text.title()
    text = _INVALID.sub("", text)
    text = text.replace("&", "and")
    text = re.sub(r"[\s\-]+", "_", text)
    text = re.sub(r"[^\w()]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("._")
    if not text:
        text = "Untitled"
    if text.upper().split(".")[0] in _RESERVED:
        text = f"{text}_"
    if len(text) > limit:
        text = text[:limit].rstrip("._")
    return text


def question_body(row: Dict[str, Any]) -> Dict[str, Any]:
    """Strip header-level fields and order the rest predictably."""
    body = OrderedDict()
    for key in _QUESTION_ORDER:
        if key in row:
            body[key] = row[key]
    for key, value in row.items():          # keep anything unforeseen
        if key not in body and key not in _HEADER_FIELDS:
            body[key] = value
    return body


def build(rows: List[Dict[str, Any]], out_dir: Path) -> Tuple[int, List[Dict[str, Any]]]:
    """Write the tree; return (files written, manifest rows)."""
    # (class, subject, chapter_number, chapter, casefolded topic) -> questions.
    # Case-folding the topic merges "Coal And Petroleum" with "Coal and
    # Petroleum" instead of emitting two files that differ only in capitals.
    buckets: Dict[Tuple, List[Dict[str, Any]]] = defaultdict(list)
    spellings: Dict[Tuple, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        topic = str(row.get("topic") or row.get("chapter") or "General").strip()
        key = (
            str(row.get("class") or "Unspecified"),
            str(row.get("subject") or "Unspecified"),
            row.get("chapter_number"),
            str(row.get("chapter") or "Unspecified"),
            topic.casefold(),
        )
        buckets[key].append(row)
        spellings[key][topic] += 1

    used: Dict[Path, int] = defaultdict(int)
    manifest: List[Dict[str, Any]] = []
    written = 0

    for key in sorted(buckets, key=lambda k: (
            _class_sort(k[0]), k[1], k[2] if k[2] is not None else 9999, k[4])):
        cls, subject, chapter_no, chapter, _folded = key
        questions = buckets[key]
        # Display the spelling the bank uses most often for this topic.
        topic = max(spellings[key].items(), key=lambda kv: (kv[1], kv[0]))[0]

        chapter_folder = (
            f"Chapter_{int(chapter_no):02d}_{safe_name(chapter, MAX_FOLDER_NAME)}"
            if chapter_no is not None
            else f"Chapter_XX_{safe_name(chapter, MAX_FOLDER_NAME)}"
        )
        folder = (out_dir / f"Class_{safe_name(cls, 12)}"
                  / safe_name(subject, 40) / chapter_folder)

        stem = safe_name(topic, MAX_FILE_STEM)
        # Two distinct topics can normalise to the same stem; keep both.
        used[folder / stem] += 1
        if used[folder / stem] > 1:
            stem = f"{stem}_{used[folder / stem]}"

        payload = OrderedDict([
            ("class", cls),
            ("subject", subject),
            ("chapter", chapter),
            ("chapter_number", chapter_no),
            ("topic", topic),
            ("question_count", len(questions)),
            ("questions", [question_body(q) for q in questions]),
        ])
        path = folder / f"{stem}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        written += 1
        manifest.append(OrderedDict([
            ("path", str(path.relative_to(out_dir)).replace("\\", "/")),
            ("class", cls), ("subject", subject),
            ("chapter_number", chapter_no), ("chapter", chapter),
            ("topic", topic), ("question_count", len(questions)),
        ]))
    return written, manifest


def _class_sort(label: str):
    return (0, int(label)) if str(label).isdigit() else (1, 0)


def verify(out_dir: Path, expected_ids: List[Any]) -> List[str]:
    """Read the tree back and prove it partitions the input exactly once."""
    problems: List[str] = []
    seen: Dict[Any, str] = {}
    duplicates = 0
    total = 0
    for path in out_dir.rglob("*.json"):
        if path.name == "_manifest.json":
            continue
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        for field in ("class", "subject", "chapter", "chapter_number", "topic",
                      "question_count", "questions"):
            if field not in data:
                problems.append(f"{path.name}: missing '{field}'")
        questions = data.get("questions", [])
        if data.get("question_count") != len(questions):
            problems.append(f"{path.name}: question_count != len(questions)")
        for question in questions:
            total += 1
            qid = question.get("question_id")
            if qid in seen:
                duplicates += 1
                if duplicates <= 5:
                    problems.append(f"question {qid} in both {seen[qid]} and {path.name}")
            seen[qid] = path.name
            if any(f in question for f in _HEADER_FIELDS):
                problems.append(f"{path.name}: question {qid} repeats a header field")

    expected = set(expected_ids)
    missing = expected - set(seen)
    extra = set(seen) - expected
    if missing:
        problems.append(f"{len(missing)} questions missing from the tree")
    if extra:
        problems.append(f"{len(extra)} unexpected question ids in the tree")
    if total != len(expected_ids):
        problems.append(f"wrote {total} questions, expected {len(expected_ids)}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", default=DEFAULT_IN)
    parser.add_argument("--out-dir", default=DEFAULT_OUT)
    parser.add_argument("--clean", action="store_true",
                        help="remove the output directory first (default: on)")
    parser.add_argument("--no-clean", dest="clean", action="store_false")
    parser.set_defaults(clean=True)
    args = parser.parse_args()

    with open(args.src, encoding="utf-8") as handle:
        data = json.load(handle)
    rows = data["questions"] if isinstance(data, dict) else data
    print(f"Loaded {args.src} ({len(rows)} questions)")

    out_dir = Path(args.out_dir)
    if args.clean and out_dir.exists():
        shutil.rmtree(out_dir)
        print(f"Cleared {out_dir}")

    written, manifest = build(rows, out_dir)
    ids = [r.get("question_id") for r in rows]
    del rows, data

    with (out_dir / "_manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(OrderedDict([
            ("total_files", len(manifest)),
            ("total_questions", sum(m["question_count"] for m in manifest)),
            ("files", manifest),
        ]), handle, ensure_ascii=False, indent=2)

    classes = len({m["class"] for m in manifest})
    subjects = len({(m["class"], m["subject"]) for m in manifest})
    chapters = len({(m["class"], m["subject"], m["chapter_number"]) for m in manifest})
    print(f"Wrote {written} topic files -> {out_dir}")
    print(f"  {classes} classes, {subjects} class/subject folders, {chapters} chapters")

    problems = verify(out_dir, ids)
    print(f"Verification: {'every question appears exactly once' if not problems else str(len(problems)) + ' problems'}")
    for problem in problems[:15]:
        print("   !", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
