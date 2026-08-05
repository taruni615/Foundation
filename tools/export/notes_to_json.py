"""Turn the Generated_Notes booklets into DB-ready JSON, one row per topic.

Two sources, in order of fidelity:

1. ``notes_spec/`` — the structured JSON the booklets were *generated from*
   (11 books). Lossless: the fields are read straight out of the spec.
2. ``Generated_Notes/*.pdf`` — for the 5 books whose spec is missing
   (Class10_Physics, Class6_Mathematics, Class6_Science, Class7_Mathematics,
   Class7_Science). The booklet layout is regular, so the same fields are
   recovered from the section markers the generator emitted.

The PDF path is checked against the spec path with ``--validate``: a book that
has *both* is parsed from its PDF and compared field-by-field with its spec,
which measures the parser rather than assuming it.

Output (``exports/notes/``)::

    all_notes_flat.json           every topic, with counts at the top
    by-class-subject/*.json       one file per class + subject
    by-chapter/*.json             one file per chapter
    _index.json                   file listing with counts

Usage::

    python tools/export/notes_to_json.py
    python tools/export/notes_to_json.py --validate        # score the PDF parser
    python tools/export/notes_to_json.py --sources spec    # skip PDF books
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

SPEC_DIR = Path("notes_spec")
NOTES_DIR = Path("Generated_Notes")
DEFAULT_OUT = "exports/notes"

# Section markers the DOCX/PDF generator writes, mapped to spec field names.
_SECTIONS = [
    ("quick_summary", "🔎 Quick Summary"),
    ("real_life", "🌍 Real-Life Example"),
    ("detailed", "📖 Detailed Explanation"),
    # The label carries its "(Exam Focus)" suffix -- matching the shorter form
    # leaves that suffix behind as a phantom first bullet.
    ("points", "✓ Points to Remember (Exam Focus)"),
    ("mistakes", "⚠ Common Student Mistakes"),
    ("memory_hook", "🧠 Memory Hook"),
    ("advanced", "🚀 Advanced Insights"),
    # These two are whole trailing sections, each holding several structured
    # entries -- not one text block. "Formula"/"Derivation" alone also appear
    # in the cover tagline ("Formula Sheets · Derivations"), so match the
    # section headings exactly.
    ("formulas", "Formula Section"),
    ("derivations", "Derivation Section"),
]
_SUBSECTIONS = ["Definition", "Key Idea", "Working Principle", "Applications"]

# Sub-headings inside one 📐 formula card, in the order the generator writes
# them, mapped to the spec's field names.
_FORMULA_FIELDS = [
    ("difficulty", "Difficulty"),
    ("formula", "Formula"),
    ("variables", "Meaning of Variables"),
    ("when_to_use", "When to Use"),
    ("common_mistakes", "Common Mistakes"),
    ("shortcut", "Shortcut / Memory Trick"),
]
# ... and inside one 🧮 derivation card.
_DERIVATION_FIELDS = [
    ("why", "Why This Derivation Matters"),
    ("assumptions", "Assumptions Used"),
    ("steps", "Step-by-Step Derivation"),
    ("result", "Final Result"),
    ("exam_perspective", "Exam Perspective"),
]
_LIST_SUBFIELDS = {"assumptions", "steps"}

_CHAPTER = re.compile(r"^Chapter\s+(\d+)\s*:\s*(.+?)\s*$", re.MULTILINE)
_TOPIC = re.compile(r"^(\d+\.\d+)\s+(.+?)\s*$", re.MULTILINE)
_META = re.compile(
    r"Estimated time:\s*(?P<time>[^\s].*?)\s{2,}"
    r"Difficulty:\s*(?P<difficulty>\S+)",
)
_BULLET = re.compile(r"^\s*[●•✓⚠▪·\-]\s*", re.MULTILINE)
# Booklet furniture that sits between topics: the periodic recap box and the
# chapter-end revision spread. Without cutting here, the last topic of every
# chapter absorbs the chapter's revision "Formula Sheet" as an extra formula.
_TOPIC_END = re.compile(
    r"⏸\s*Quick Recap"
    r"|—\s*End of Chapter Revision"
    r"|⚡\s*Quick Revision Section"
)
_PAGE_FURNITURE = re.compile(r"^(?:.*—\s*Notes|Page \d+ of \d+)\s*$", re.MULTILINE)


def clean(text: str) -> str:
    """Collapse whitespace and drop the soft hyphens the PDF layer inserts."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("­", "").replace("​", "")
    return re.sub(r"\s+", " ", text).strip()


def split_bullets(block: str) -> List[str]:
    """One entry per bullet, keeping wrapped lines with their bullet."""
    if not block.strip():
        return []
    parts = re.split(r"(?m)^\s*[●•✓⚠▪]\s*", block)
    items = [clean(p) for p in parts if clean(p)]
    if len(items) <= 1:
        # No bullet glyphs — fall back to one item per non-empty line.
        items = [clean(line) for line in block.splitlines() if clean(line)]
    return items


def class_subject(stem: str) -> Dict[str, str]:
    """"Class9_Physics" -> {"class": "9", "subject": "Physics"}."""
    match = re.match(r"Class(\d+)[_\s-]+(.+)$", stem)
    if not match:
        return {"class": "", "subject": stem}
    return {"class": match.group(1), "subject": match.group(2).replace("_", " ").strip()}


# ---------------------------------------------------------------------------
# Source 1: the generator's own spec
# ---------------------------------------------------------------------------
def rows_from_spec(book_json: Path) -> List[Dict[str, Any]]:
    book = json.loads(book_json.read_text(encoding="utf-8"))
    chapters_dir = SPEC_DIR / book.get("chapters_dir", book_json.stem)
    identity = class_subject(book_json.stem)
    rows: List[Dict[str, Any]] = []

    for chapter_file in sorted(chapters_dir.glob("ch*.json")):
        chapter = json.loads(chapter_file.read_text(encoding="utf-8"))
        for order, topic in enumerate(chapter.get("topics", []), start=1):
            detailed = topic.get("detailed") or {}
            rows.append(build_row(
                identity=identity,
                book=book_json.stem,
                book_title=book.get("book_title", ""),
                chapter_number=chapter.get("number"),
                chapter=chapter.get("title", ""),
                prerequisites=chapter.get("prerequisites") or [],
                order=order,
                topic=topic.get("title", ""),
                fields={
                    "estimated_time": topic.get("time", ""),
                    "difficulty": topic.get("difficulty", ""),
                    "importance": topic.get("importance"),
                    "quick_summary": topic.get("quick_summary", ""),
                    "real_life": topic.get("real_life", ""),
                    "definition": detailed.get("definition", ""),
                    "key_idea": detailed.get("key_idea", ""),
                    "working_principle": detailed.get("working_principle", ""),
                    "applications": detailed.get("applications") or [],
                    "points": topic.get("points") or [],
                    "mistakes": topic.get("mistakes") or [],
                    "memory_hook": topic.get("memory_hook", ""),
                    "advanced": topic.get("advanced", ""),
                    "formulas": topic.get("formulas") or [],
                    "derivations": topic.get("derivations") or [],
                },
                source="spec",
            ))
    return rows


# ---------------------------------------------------------------------------
# Source 2: the rendered PDF, for books whose spec is gone
# ---------------------------------------------------------------------------
def pdf_text(path: Path) -> str:
    import fitz  # PyMuPDF

    document = fitz.open(path)
    try:
        pages = [page.get_text() for page in document]
    finally:
        document.close()
    text = "\n".join(pages)
    return _PAGE_FURNITURE.sub("", text)


def section_blocks(body: str) -> Dict[str, str]:
    """Split one topic's body into its labelled sections."""
    marks = []
    for field, label in _SECTIONS:
        position = body.find(label)
        if position != -1:
            marks.append((position, field, label))
    marks.sort()
    blocks: Dict[str, str] = {}
    for index, (position, field, label) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(body)
        blocks[field] = body[position + len(label):end].strip()
    return blocks


def parse_detailed(block: str) -> Dict[str, Any]:
    """Split the Detailed Explanation block into its four sub-headings."""
    found = []
    for name in _SUBSECTIONS:
        match = re.search(rf"(?m)^\s*{re.escape(name)}\s*$", block)
        if match:
            found.append((match.start(), match.end(), name))
    found.sort()
    out: Dict[str, Any] = {}
    for index, (start, end, name) in enumerate(found):
        stop = found[index + 1][0] if index + 1 < len(found) else len(block)
        chunk = block[end:stop].strip()
        key = name.lower().replace(" ", "_")
        out[key] = split_bullets(chunk) if name == "Applications" else clean(chunk)
    return out


def _cards(block: str, glyph: str, fields: List[tuple]) -> List[Dict[str, Any]]:
    """Split a Formula/Derivation section into one dict per card."""
    heads = list(re.finditer(rf"{glyph}\s*(?:Derivation:\s*)?(.+)", block))
    cards: List[Dict[str, Any]] = []
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(block)
        body = block[head.end():end]
        card: Dict[str, Any] = OrderedDict()
        card["name" if glyph == "📐" else "title"] = clean(head.group(1))

        found = []
        for key, label in fields:
            match = re.search(rf"(?m)^\s*{re.escape(label)}\s*$", body)
            if match:
                found.append((match.start(), match.end(), key))
        found.sort()
        for position, (start, stop, key) in enumerate(found):
            limit = found[position + 1][0] if position + 1 < len(found) else len(body)
            chunk = body[stop:limit].strip()
            card[key] = split_bullets(chunk) if key in _LIST_SUBFIELDS else clean(chunk)
        cards.append(card)
    return cards


def rows_from_pdf(pdf: Path) -> List[Dict[str, Any]]:
    stem = pdf.stem.replace("_Notes", "")
    identity = class_subject(stem)
    text = pdf_text(pdf)

    chapters = list(_CHAPTER.finditer(text))
    rows: List[Dict[str, Any]] = []
    for index, chapter_match in enumerate(chapters):
        start = chapter_match.end()
        end = chapters[index + 1].start() if index + 1 < len(chapters) else len(text)
        body = text[start:end]

        prerequisites: List[str] = []
        prereq = re.search(r"Prerequisites\s*(.*?)(?=^\d+\.\d+\s)", body, re.S | re.M)
        if prereq:
            prerequisites = [
                p for p in split_bullets(prereq.group(1))
                if not p.lower().startswith("before starting this chapter")
            ]

        topics = list(_TOPIC.finditer(body))
        for order, topic_match in enumerate(topics, start=1):
            t_start = topic_match.end()
            t_end = topics[order].start() if order < len(topics) else len(body)
            topic_body = body[t_start:t_end]
            cut = _TOPIC_END.search(topic_body)
            if cut:
                topic_body = topic_body[: cut.start()]

            meta = _META.search(topic_body)
            blocks = section_blocks(topic_body)
            detailed = parse_detailed(blocks.get("detailed", ""))
            rows.append(build_row(
                identity=identity,
                book=stem,
                book_title=f"{identity['class']} {identity['subject']} Foundation".strip(),
                chapter_number=int(chapter_match.group(1)),
                chapter=clean(chapter_match.group(2)),
                prerequisites=prerequisites,
                order=order,
                topic=clean(topic_match.group(2)),
                fields={
                    "estimated_time": clean(meta.group("time")) if meta else "",
                    "difficulty": clean(meta.group("difficulty")) if meta else "",
                    "importance": None,
                    "quick_summary": clean(blocks.get("quick_summary", "")),
                    "real_life": clean(blocks.get("real_life", "")),
                    "definition": detailed.get("definition", ""),
                    "key_idea": detailed.get("key_idea", ""),
                    "working_principle": detailed.get("working_principle", ""),
                    "applications": detailed.get("applications", []),
                    "points": split_bullets(blocks.get("points", "")),
                    "mistakes": split_bullets(blocks.get("mistakes", "")),
                    "memory_hook": clean(blocks.get("memory_hook", "")),
                    "advanced": clean(blocks.get("advanced", "")),
                    "formulas": _cards(blocks.get("formulas", ""), "📐", _FORMULA_FIELDS),
                    "derivations": _cards(blocks.get("derivations", ""), "🧮",
                                          _DERIVATION_FIELDS),
                },
                source="pdf",
                topic_number=topic_match.group(1),
            ))
    return rows


def build_row(*, identity, book, book_title, chapter_number, chapter, prerequisites,
              order, topic, fields, source, topic_number=None) -> Dict[str, Any]:
    return OrderedDict([
        ("note_id", f"{book}-c{chapter_number:02d}-t{order:02d}"
                    if isinstance(chapter_number, int) else f"{book}-{order}"),
        ("class", identity["class"]),
        ("subject", identity["subject"]),
        ("book", book),
        ("book_title", book_title),
        ("chapter_number", chapter_number),
        ("chapter", chapter),
        ("topic_order", order),
        ("topic_number", topic_number or (
            f"{chapter_number}.{order}" if chapter_number is not None else "")),
        ("topic", topic),
        ("estimated_time", fields["estimated_time"]),
        ("difficulty", fields["difficulty"]),
        ("importance", fields["importance"]),
        ("quick_summary", fields["quick_summary"]),
        ("real_life", fields["real_life"]),
        ("definition", fields["definition"]),
        ("key_idea", fields["key_idea"]),
        ("working_principle", fields["working_principle"]),
        ("applications", fields["applications"]),
        ("points", fields["points"]),
        ("mistakes", fields["mistakes"]),
        ("memory_hook", fields["memory_hook"]),
        ("advanced", fields["advanced"]),
        ("formulas", fields["formulas"]),
        ("derivations", fields["derivations"]),
        ("chapter_prerequisites", prerequisites),
        ("source", source),
    ])


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
TEXT_FIELDS = ["quick_summary", "real_life", "definition", "key_idea",
               "working_principle", "memory_hook", "advanced"]
LIST_FIELDS = ["applications", "points", "mistakes", "formulas", "derivations"]


def tally(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    filled = {f: sum(1 for r in rows if str(r.get(f, "")).strip()) for f in TEXT_FIELDS}
    filled.update({f: sum(1 for r in rows if r.get(f)) for f in LIST_FIELDS})
    return OrderedDict([
        ("chapters", len({(r["book"], r["chapter_number"]) for r in rows})),
        ("by_source", OrderedDict(Counter(r["source"] for r in rows).most_common())),
        ("fields_populated", OrderedDict(sorted(filled.items()))),
    ])


def wrap(rows: List[Dict[str, Any]], scope: Optional[Dict] = None) -> Dict[str, Any]:
    payload = OrderedDict([("total_topics", len(rows))])
    if scope:
        payload["scope"] = OrderedDict(scope)
    payload["counts"] = tally(rows)
    payload["notes"] = rows
    return payload


def slug(value: Any) -> str:
    s = re.sub(r"[^\w\s-]+", "", str(value or "")).strip().lower()
    return re.sub(r"[-\s_]+", "-", s).strip("-") or "unspecified"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def write_outputs(rows: List[Dict[str, Any]], out_dir: Path) -> None:
    write_json(out_dir / "all_notes_flat.json", wrap(rows))
    groups = {
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
    }
    manifest = []
    for folder, (keyer, scoper) in groups.items():
        target = out_dir / folder
        if target.exists():
            for stale in target.glob("*.json"):
                stale.unlink()
        buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            buckets[keyer(row)].append(row)
        for name in sorted(buckets):
            items = buckets[name]
            write_json(target / f"{name}.json", wrap(items, scoper(items[0])))
            manifest.append(OrderedDict([("file", f"{folder}/{name}.json"),
                                         ("total_topics", len(items))]))
    write_json(out_dir / "_index.json", OrderedDict([
        ("total_topics", len(rows)),
        ("total_files", len(manifest)),
        ("files", manifest),
    ]))


# ---------------------------------------------------------------------------
# Parser validation
# ---------------------------------------------------------------------------
def validate(out: Path) -> None:
    """Parse PDFs that also have a spec, and score the parser against it."""
    scored = Counter()
    per_field = defaultdict(lambda: [0, 0])
    for book_json in sorted(SPEC_DIR.glob("*.json")):
        pdf = NOTES_DIR / f"{book_json.stem}_Notes.pdf"
        if not pdf.exists():
            continue
        spec_rows = {(r["chapter_number"], r["topic_order"]): r
                     for r in rows_from_spec(book_json)}
        pdf_rows = {(r["chapter_number"], r["topic_order"]): r
                    for r in rows_from_pdf(pdf)}
        scored["books compared"] += 1
        scored["topics in spec"] += len(spec_rows)
        scored["topics recovered from pdf"] += len(set(spec_rows) & set(pdf_rows))
        for key, spec_row in spec_rows.items():
            pdf_row = pdf_rows.get(key)
            if not pdf_row:
                continue
            for field in TEXT_FIELDS + LIST_FIELDS + ["topic"]:
                expected, actual = spec_row.get(field), pdf_row.get(field)
                if not expected:
                    continue
                per_field[field][1] += 1
                if isinstance(expected, list):
                    if len(actual or []) == len(expected):
                        per_field[field][0] += 1
                elif clean(str(expected))[:80] == clean(str(actual))[:80]:
                    per_field[field][0] += 1

    print("\nPDF-parser validation (books that have both a spec and a PDF)")
    for key, value in scored.items():
        print(f"  {value:6d}  {key}")
    print("  field-level match rate:")
    for field, (ok, total) in sorted(per_field.items()):
        if total:
            print(f"    {100*ok/total:5.1f}%  {field}  ({ok}/{total})")
    write_json(out, OrderedDict([
        ("summary", OrderedDict(scored.most_common())),
        ("field_match_rate", {f: {"matched": ok, "checked": n}
                              for f, (ok, n) in sorted(per_field.items())}),
    ]))
    print(f"  wrote {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=DEFAULT_OUT)
    parser.add_argument("--sources", choices=["spec", "pdf", "both"], default="both")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    if args.validate:
        validate(out_dir / "_parser_validation.json")
        return 0

    rows: List[Dict[str, Any]] = []
    spec_books = sorted(SPEC_DIR.glob("*.json"))
    covered = {p.stem for p in spec_books}

    if args.sources in ("spec", "both"):
        for book_json in spec_books:
            book_rows = rows_from_spec(book_json)
            rows.extend(book_rows)
            print(f"  spec  {book_json.stem:24s} {len(book_rows):4d} topics")

    if args.sources in ("pdf", "both"):
        for pdf in sorted(NOTES_DIR.glob("*.pdf")):
            stem = pdf.stem.replace("_Notes", "")
            if stem in covered:
                continue
            book_rows = rows_from_pdf(pdf)
            rows.extend(book_rows)
            print(f"  pdf   {stem:24s} {len(book_rows):4d} topics")

    rows.sort(key=lambda r: (
        int(r["class"]) if str(r["class"]).isdigit() else 99,
        r["subject"], r["chapter_number"] or 0, r["topic_order"]))

    write_outputs(rows, out_dir)
    counts = tally(rows)
    print(f"\n{len(rows)} topics across {counts['chapters']} chapters -> {out_dir}")
    print(f"  by source: {dict(counts['by_source'])}")
    for field, n in counts["fields_populated"].items():
        print(f"    {n:5d}  {field}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
