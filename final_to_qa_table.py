#!/usr/bin/env python3
"""Build QA table JSON from a v3 *_final.json file.

``topics[]`` (pedagogy only, per topic):

  - topic_number, chapter_name, page_range, summary, key_points, theory_sections
  - ``theory_sections[].topics`` (was ``title``)

``rows[]`` (MySQL insert, from full Final topic Q&A):

  - illustrations, check_your_knowledge_items, textbook_exercises,
    exercises, examples — each with ``question`` / ``answer``

See ``schema/topic_qa_content.sql``.

Usage::

  python final_to_qa_table.py outputs/10TH\\ CHEMISTRY\\ FOUNDATION/10TH\\ CHEMISTRY\\ FOUNDATION_final.json
  python final_to_qa_table.py --dry-run outputs/book_final.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from question_type_classifier import classify_question
from topicwise_pipeline import (
    apply_pedagogy_export_fields,
    chapter_name_from_topic,
    convert_markdown_tables_to_html,
)

QA_SECTION_KEYS = (
    "illustrations",
    "check_your_knowledge_items",
    "textbook_exercises",
    "exercises",
    "examples",
)

SECTION_TYPE_MAP = {
    "illustrations": "illustration",
    "check_your_knowledge_items": "check_your_knowledge",
    "textbook_exercises": "textbook_exercise",
    "exercises": "exercise",
    "examples": "example",
}

# Fields kept in *_qa_table.json topics[] (theory / pedagogy only).
QA_TOPIC_FIELDS = (
    "topic_number",
    "chapter_name",
    "page_range",
    "summary",
    "key_points",
    "theory_sections",
)


def _slug_book(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    slug = re.sub(r"[-\s]+", "_", slug.strip()).strip("_").lower()
    return slug or "book"


def _problem_text(item: Dict[str, Any]) -> str:
    return (
        item.get("problem")
        or item.get("problem_markdown")
        or item.get("prompt_markdown")
        or item.get("prompt")
        or ""
    )


def _solution_text(item: Dict[str, Any]) -> str:
    return (
        item.get("solution")
        or item.get("solution_markdown")
        or ""
    )


def rename_item_problem_solution(item: Dict[str, Any]) -> Dict[str, Any]:
    """Copy item with question/answer fields; drop problem/solution aliases."""
    out = copy.deepcopy(item)
    question = _problem_text(out)
    answer = _solution_text(out)
    for key in ("problem", "problem_markdown", "prompt_markdown", "prompt"):
        out.pop(key, None)
    for key in ("solution", "solution_markdown"):
        out.pop(key, None)
    if question:
        out["question"] = question
    if answer:
        out["answer"] = answer
    return out


def transform_topic_qa_arrays(topic: Dict[str, Any]) -> Dict[str, Any]:
    """Full topic copy with problem/solution → question/answer (for rows[] only)."""
    out = copy.deepcopy(topic)
    for key in QA_SECTION_KEYS:
        items = out.get(key)
        if not isinstance(items, list):
            continue
        out[key] = [rename_item_problem_solution(it) for it in items if isinstance(it, dict)]
    return apply_pedagogy_export_fields(out)


def enrich_qa_markdown_field(text: Any) -> Any:
    """Pipe markdown tables → HTML for QA export / DB viewer."""
    if not isinstance(text, str) or not text.strip():
        return text if text is not None else ""
    return convert_markdown_tables_to_html(text)


def enrich_qa_topic_markdown(topic: Dict[str, Any]) -> Dict[str, Any]:
    """Apply table conversion on all long-form markdown fields in a QA topic."""
    out = copy.deepcopy(topic)
    if isinstance(out.get("summary"), str):
        out["summary"] = enrich_qa_markdown_field(out["summary"])
    for kp in out.get("key_points") or []:
        if isinstance(kp, dict) and isinstance(kp.get("text"), str):
            kp["text"] = enrich_qa_markdown_field(kp["text"])
    for sec in out.get("theory_sections") or []:
        if not isinstance(sec, dict):
            continue
        if isinstance(sec.get("markdown"), str):
            sec["markdown"] = enrich_qa_markdown_field(sec["markdown"])
        if isinstance(sec.get("topic_explanation"), str):
            sec["topic_explanation"] = enrich_qa_markdown_field(sec["topic_explanation"])
    return out


def slim_qa_topic(topic: Dict[str, Any]) -> Dict[str, Any]:
    """Pedagogy-only topic record for *_qa_table.json topics[]."""
    slim: Dict[str, Any] = {
        "topic_number": topic.get("topic_number"),
        "chapter_name": chapter_name_from_topic(topic),
        "page_range": topic.get("page_range", ""),
        "summary": topic.get("summary", ""),
        "key_points": copy.deepcopy(topic.get("key_points") or []),
        "theory_sections": copy.deepcopy(topic.get("theory_sections") or []),
    }
    return apply_pedagogy_export_fields(enrich_qa_topic_markdown(slim))


def build_qa_metadata(source_meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = copy.deepcopy(source_meta)
    meta["layout"] = "qa_view"
    meta["topics_shape"] = list(QA_TOPIC_FIELDS)
    meta["qa_field_map"] = {
        "rows.problem": "question",
        "rows.solution": "answer",
        "row_arrays": list(QA_SECTION_KEYS),
        "theory_sections.title": "theory_sections.topics",
    }
    if str(meta.get("format_version", "")).startswith("3."):
        meta["format_version"] = "3.1"
    return meta


def _make_row_id(
    book_slug: str,
    topic_number: int,
    section_type: str,
    order: int,
    item_id: Optional[str],
) -> str:
    if item_id:
        safe = re.sub(r"[^\w.-]", "_", str(item_id))[:96]
        return f"{book_slug}__t{topic_number}__{section_type}__{safe}"
    return f"{book_slug}__t{topic_number}__{section_type}__{order:04d}"


def flatten_qa_rows(
    document: Dict[str, Any],
    book_slug: str,
) -> List[Dict[str, Any]]:
    """One row per Q&A item across the five section arrays."""
    rows: List[Dict[str, Any]] = []
    for topic in document.get("topics") or []:
        if not isinstance(topic, dict):
            continue
        tn = int(topic.get("topic_number") or 0)
        tname = chapter_name_from_topic(topic)
        for array_key in QA_SECTION_KEYS:
            section_type = SECTION_TYPE_MAP[array_key]
            for order, item in enumerate(topic.get(array_key) or [], start=1):
                if not isinstance(item, dict):
                    continue
                question = item.get("question") or _problem_text(item)
                answer = item.get("answer") or _solution_text(item)
                if not question and not answer:
                    continue
                item_id = item.get("id")
                rows.append({
                    "id": _make_row_id(book_slug, tn, section_type, order, item_id),
                    "book_slug": book_slug,
                    "topic_number": tn,
                    "chapter_name": tname,
                    "section_type": section_type,
                    "item_order": order,
                    "title": item.get("title") or "",
                    "question": enrich_qa_markdown_field(question),
                    "answer": enrich_qa_markdown_field(answer),
                    "question_type": classify_question(
                        question,
                        section_type=section_type,
                        subsection=item.get("title") or "",
                    ),
                    "source_type": item.get("source_type") or section_type,
                    "item_ref_id": item_id,
                    "format_version": str(
                        (document.get("metadata") or {}).get("format_version") or "3.0"
                    ),
                })
    return rows


def qa_json_path_from_final(final_path: str) -> str:
    """Sibling *_qa_table.json in the same directory as *_final.json."""
    if final_path.endswith("_final.json"):
        return final_path.replace("_final.json", "_qa_table.json")
    base, ext = os.path.splitext(final_path)
    return f"{base}_qa_table{ext or '.json'}"


def book_export_paths(base_name: str, output_dir: str = "outputs") -> Tuple[str, str]:
    """(final_json_path, qa_table_json_path) under outputs/<book>/."""
    book_output_dir = os.path.join(output_dir, base_name)
    final_path = os.path.join(book_output_dir, f"{base_name}_final.json")
    qa_path = os.path.join(book_output_dir, f"{base_name}_qa_table.json")
    return final_path, qa_path


def build_qa_table_export_from_document(
    document: Dict[str, Any],
    book_slug: str,
    *,
    source_final_path: str = "",
) -> Dict[str, Any]:
    """Build QA table export from an in-memory *_final.json document."""
    meta = document.get("metadata") or {}
    source_topics = [
        t for t in (document.get("topics") or []) if isinstance(t, dict)
    ]
    full_for_rows = [transform_topic_qa_arrays(t) for t in source_topics]
    rows = flatten_qa_rows(
        {"topics": full_for_rows, "metadata": meta},
        book_slug,
    )
    qa_topics = [slim_qa_topic(t) for t in source_topics]
    qa_meta = build_qa_metadata(meta)
    if source_final_path:
        qa_meta["source_final_json"] = source_final_path.replace("\\", "/")
    qa_meta["book_slug"] = book_slug
    qa_meta["row_count"] = len(rows)
    qa_meta["markdown_tables"] = "html"

    return {
        "schema_version": "3.0-qa",
        "metadata": qa_meta,
        "topics": qa_topics,
        "rows": rows,
    }


def build_qa_table_export(
    final_path: str,
    *,
    book_slug: Optional[str] = None,
) -> Dict[str, Any]:
    with open(final_path, "r", encoding="utf-8") as handle:
        source = json.load(handle)

    meta = source.get("metadata") or {}
    slug = book_slug or _slug_book(
        meta.get("name") or os.path.basename(final_path).replace("_final.json", "")
    )
    return build_qa_table_export_from_document(
        source,
        slug,
        source_final_path=final_path,
    )


def _print_qa_table_stats(export: Dict[str, Any], out_path: str) -> None:
    section_counts: Dict[str, int] = {}
    type_counts: Dict[str, int] = {}
    for row in export.get("rows") or []:
        st = row.get("section_type", "?")
        section_counts[st] = section_counts.get(st, 0) + 1
        qt = row.get("question_type", "?")
        type_counts[qt] = type_counts.get(qt, 0) + 1
    print(f"Saved QA table JSON: {out_path}")
    print(f"  Topics: {len(export.get('topics') or [])}")
    print(f"  Insert rows: {len(export.get('rows') or [])}")
    print(f"  By section: {section_counts}")
    print(f"  By question_type: {type_counts}")


def save_qa_table_json_from_document(
    document: Dict[str, Any],
    book_slug: str,
    output_path: str,
    *,
    source_final_path: str = "",
) -> str:
    """Write *_qa_table.json from an in-memory Final document (no re-read from disk)."""
    export = build_qa_table_export_from_document(
        document,
        book_slug,
        source_final_path=source_final_path,
    )
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(export, handle, indent=2, ensure_ascii=False)
    _print_qa_table_stats(export, output_path)
    return output_path


def save_qa_table_json(
    final_path: str,
    output_path: Optional[str] = None,
    *,
    book_slug: Optional[str] = None,
) -> str:
    out_path = output_path or qa_json_path_from_final(final_path)
    export = build_qa_table_export(final_path, book_slug=book_slug)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(export, handle, indent=2, ensure_ascii=False)
    _print_qa_table_stats(export, out_path)
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build QA table JSON (Final shape + flat rows) from *_final.json",
    )
    parser.add_argument(
        "final_json",
        help="Path to outputs/<book>/<book>_final.json",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output path (default: <book>_qa_table.json beside final)",
    )
    parser.add_argument(
        "--book-slug",
        default=None,
        help="Override book_slug used in row ids (default: derived from metadata.name)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts only; do not write file",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not os.path.exists(args.final_json):
        raise SystemExit(f"File not found: {args.final_json}")

    export = build_qa_table_export(args.final_json, book_slug=args.book_slug)
    counts: Dict[str, int] = {}
    for row in export["rows"]:
        st = row.get("section_type", "?")
        counts[st] = counts.get(st, 0) + 1

    print(f"Source: {args.final_json}")
    print(f"  Topics: {len(export['topics'])}")
    print(f"  Insert rows: {len(export['rows'])}")
    print(f"  By section: {counts}")

    if args.dry_run:
        return

    out_path = args.output or qa_json_path_from_final(args.final_json)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(export, handle, indent=2, ensure_ascii=False)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
