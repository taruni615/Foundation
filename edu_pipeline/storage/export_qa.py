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

  python scripts/final_to_qa_table.py outputs/10TH\\ CHEMISTRY\\ FOUNDATION/10TH\\ CHEMISTRY\\ FOUNDATION_final.json
  python scripts/final_to_qa_table.py --dry-run outputs/book_final.json
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from edu_pipeline.generators.questions.classifier import classify_question
from edu_pipeline.extraction.topic_extractor import (
    apply_pedagogy_export_fields,
    chapter_name_from_topic,
    convert_markdown_tables_to_html,
)
from edu_pipeline.extraction.question_bank import normalize_fullwidth
from edu_pipeline.shared.constants import QA_SECTION_KEYS

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
    target: Union[str, Dict[str, Any], Any],
    *,
    book_slug: Optional[str] = None,
) -> Dict[str, Any]:
    from edu_pipeline.repository import BookRepository
    if isinstance(target, BookRepository):
        source = target.raw_json
        final_path = target.source_path or ""
    elif isinstance(target, dict):
        source = target
        final_path = ""
    else:
        final_path = str(target)
        with open(final_path, "r", encoding="utf-8") as handle:
            source = json.load(handle)

    meta = source.get("metadata") or {}
    slug = book_slug or _slug_book(
        meta.get("name") or (os.path.basename(final_path).replace("_final.json", "") if final_path else "book")
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


# A matching question is two labelled lists plus, sometimes, a set of
# combination options. The books are consistent about the labels: Column I runs
# (A)-(E), Column II runs (p)-(t) or (1)-(5), and any answer options run (a)-(d)
# whose *text* is a list of pairings ("A-2, B-1"). That last distinction matters:
# (a)-(d) would otherwise be mistaken for Column II entries.
MATCH_COLUMN_HEADER_RE = re.compile(
    r"^\s*(?:column|list)\s*[-–—]?\s*(i{1,3}|[12]|a|b)\s*[:.]?\s*$", re.IGNORECASE)
# "(A) text", "A. text" and "A) text" all occur.
MATCH_ITEM_RE = re.compile(r"^\s*\(?([A-Za-z]{1,3}|\d{1,2})[).]\s*(.*)$")
# The same labels found mid-line, for text whose newlines were collapsed away.
# The space after the label is optional: a matching table flattened out of HTML
# runs the label straight into its text ("(A)Acceleration(p)may be zero").
# "(A) text", "(A)text" (a matching table flattened out of HTML runs the label
# straight into its text) and "A. text" all occur. The bare form still needs the
# trailing space, or it would fire inside ordinary words.
# A parenthesised label is distinctive enough to match anywhere -- a matching
# table flattened out of HTML runs it straight into the preceding cell
# ("Column I(A)Acceleration"). The bare "A." form still needs to start a word,
# or it would fire inside ordinary prose.
MATCH_INLINE_LABEL_RE = re.compile(
    r"\(([A-Za-z]|\d{1,2})\)\s*|(?:(?<=[\s>])|^)([A-Za-z]|\d{1,2})[.)]\s+")
# Case-sensitive on purpose: Column I labels are upper case, and a hex image URL
# ("...4fb7-410b...") is full of lower-case letter-digit pairs that would
# otherwise read as pairings.
MATCH_PAIRING_RE = re.compile(r"\b[A-E]\s*[-–—→:>]+\s*[a-z0-9]\b")

_LIST1_LABELS = set("ABCDE") | {"I", "II", "III", "IV", "V"}
_LIST2_LABELS = set("pqrst") | set("12345")


def _looks_like_pairing_option(text: str) -> bool:
    """True for option text such as "A-2, B-1, C-4, D-3".

    Figures are stripped first: an image URL carries a hex id whose fragments
    look exactly like pairings, which would file a Column II diagram as an
    answer option. A real option is also compact -- prose that merely mentions
    a pairing is not one.
    """
    stripped = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", str(text or ""))
    stripped = re.sub(r"https?://\S+", " ", stripped)
    stripped = re.sub(r"\[image:[^\]]*\]", " ", stripped).strip()
    if len(stripped) > 80:
        return False
    return len(MATCH_PAIRING_RE.findall(stripped)) >= 2


def parse_matching_question(question_text: str) -> Optional[Dict[str, Any]]:
    """Split a matching question into its stem, two lists and any options.

    Returns None when the text does not actually carry two labelled lists, so
    the caller can fall back to leaving the question as plain text.
    """
    if not question_text:
        return None

    stem: List[str] = []
    list_1: List[Dict[str, str]] = []
    list_2: List[Dict[str, str]] = []
    options: List[Dict[str, str]] = []
    current: Optional[List[Dict[str, str]]] = None
    seen_item = False

    for raw_line in str(question_text).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        header = MATCH_COLUMN_HEADER_RE.match(line)
        if header:
            token = header.group(1).lower()
            current = list_2 if token in ("ii", "2", "b") else list_1
            continue

        item = MATCH_ITEM_RE.match(line)
        if not item:
            (stem if not seen_item else (current if current is not None else stem)).append(line)
            continue

        label, text = item.group(1), item.group(2).strip()
        seen_item = True
        if _looks_like_pairing_option(text):
            options.append({"id": label, "text": text})
        elif label in _LIST1_LABELS:
            list_1.append({"id": label, "text": text})
            current = list_1
        elif label.lower() in _LIST2_LABELS:
            list_2.append({"id": label, "text": text})
            current = list_2
        elif current is not None:
            current.append({"id": label, "text": text})
        else:
            stem.append(line)

    if not list_1 and not list_2:
        return _parse_matching_inline(question_text)
    return {
        "question": " ".join(stem).strip(),
        "list_1": list_1,
        "list_2": list_2,
        "options": options,
    }


def _parse_matching_inline(text: str) -> Optional[Dict[str, Any]]:
    """Fallback for matching text whose line breaks were collapsed away."""
    labels = list(MATCH_INLINE_LABEL_RE.finditer(text))
    if len(labels) < 2:
        return None

    stem = text[: labels[0].start()].strip()
    list_1: List[Dict[str, str]] = []
    list_2: List[Dict[str, str]] = []
    options: List[Dict[str, str]] = []
    for index, match in enumerate(labels):
        end = labels[index + 1].start() if index + 1 < len(labels) else len(text)
        label = match.group(1) or match.group(2)
        body = text[match.end():end].strip()
        if not body:
            continue
        if _looks_like_pairing_option(body):
            options.append({"id": label, "text": body})
        elif label in _LIST1_LABELS:
            list_1.append({"id": label, "text": body})
        elif label.lower() in _LIST2_LABELS:
            list_2.append({"id": label, "text": body})

    if not list_1 or not list_2:
        return None
    return {"question": stem, "list_1": list_1, "list_2": list_2, "options": options}


def parse_matching_answer(answer_text: str, options: List[Dict[str, str]]) -> Any:
    """The answer to a matching question.

    With combination options the answer is the option's own label; without them
    it is the pairing itself, kept as ``{"A": "p", ...}`` so it can be checked
    against the two lists.
    """
    text = str(answer_text or "").strip()
    if not text:
        return None

    if options:
        # "(c)" or a bare "c" naming one of the combination options.
        bare = re.match(r"^\(?([a-e])\)?\b", text, re.IGNORECASE)
        if bare and any(o["id"].lower() == bare.group(1).lower() for o in options):
            return bare.group(1).lower()

    pairs = re.findall(r"([A-E])\s*[-–—→:>]+\s*([a-z0-9]+)", text, re.IGNORECASE)
    if pairs:
        return {left.upper(): right.lower() for left, right in pairs}
    return text


IMAGE_TOKEN_RE = re.compile(r"\[image:(img_\d+)\]")
IMAGE_URL_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)]+)\)")

# Figures are embedded as base64 so a document is self-contained: it renders with
# no server and no network, which is what a copy shared with a reviewer needs.
# Set EMBED_IMAGE_DATA=0 for lean documents that point at image_cache/ instead.
EMBED_IMAGE_DATA = os.environ.get("EMBED_IMAGE_DATA", "1").lower() not in ("0", "false", "no")
_IMAGE_DATA_CACHE: Dict[str, str] = {}


def _image_data_uri(file_path: str) -> str:
    """base64 payload for a cached figure, read once per file per run."""
    if not EMBED_IMAGE_DATA or not file_path:
        return ""
    if file_path in _IMAGE_DATA_CACHE:
        return _IMAGE_DATA_CACHE[file_path]
    payload = ""
    for candidate in (file_path, os.path.join(os.getcwd(), file_path)):
        if os.path.isfile(candidate):
            try:
                with open(candidate, "rb") as handle:
                    payload = base64.b64encode(handle.read()).decode("ascii")
            except OSError:
                payload = ""
            break
    _IMAGE_DATA_CACHE[file_path] = payload
    return payload


def _unescape_url(url: str) -> str:
    """Undo the entity escaping a markdown-table -> HTML conversion applies.

    A figure inside a table comes out with ``&amp;`` in its query string, which
    no longer matches the ``source_url`` recorded on the asset.
    """
    return str(url or "").replace("&amp;", "&").replace("&#38;", "&")


def _tokenize_image_urls(text: Any, url_to_id: Dict[str, str]) -> Any:
    """Rewrite raw ``![](https://cdn…)`` to ``[image:img_003]``.

    Exercise questions are re-parsed from source markdown after the tokenising
    pass, so their text still carries the original CDN URL. Left alone it is the
    one thing in an otherwise self-contained document that still needs the
    network; as a token it resolves against the embedded figure instead.
    """
    if not isinstance(text, str) or "](http" not in text:
        return text

    def replace(match: re.Match) -> str:
        img_id = url_to_id.get(match.group(1)) or url_to_id.get(_unescape_url(match.group(1)))
        return "[image:" + img_id + "]" if img_id else match.group(0)

    return IMAGE_URL_RE.sub(replace, text)


def _resolve_images(topic: Dict[str, Any], item: Dict[str, Any]) -> List[Dict[str, str]]:
    """Figures referenced by one question or theory section, in order of use.

    References arrive two ways: as ``[image:img_003]`` tokens, left once the
    extractor has registered the figure, or as a raw markdown image URL when it
    has not -- exercise questions are re-parsed from source markdown after the
    tokenising pass and still carry URLs. Both resolve against the topic's
    ``image_assets``. Each figure carries its bytes so the document renders
    without the cache directory or the network (see EMBED_IMAGE_DATA).
    """
    assets: Dict[str, Any] = topic.get("image_assets") or {}
    url_to_id = {
        (asset or {}).get("source_url", ""): img_id for img_id, asset in assets.items()
    }

    text = " ".join(
        value for value in (
            item.get("question"), item.get("answer"), item.get("explanation"),
            item.get("problem"), item.get("solution"), item.get("markdown"),
            # A passage's diagram is referenced only from the passage, and
            # without it every question under that passage loses the figure.
            item.get("passage"),
        ) if isinstance(value, str)
    )
    found: List[str] = list(IMAGE_TOKEN_RE.findall(text))
    for url in IMAGE_URL_RE.findall(text) + list(item.get("image_urls") or []):
        img_id = url_to_id.get(url) or url_to_id.get(_unescape_url(url))
        if img_id:
            found.append(img_id)
    for image in item.get("images") or []:
        if isinstance(image, dict) and image.get("id"):
            found.append(image["id"])

    resolved: List[Dict[str, str]] = []
    seen: set = set()
    for img_id in found:
        if img_id in seen:
            continue
        seen.add(img_id)
        asset = assets.get(img_id) or {}
        entry = {
            "id": img_id,
            "file": asset.get("file", ""),
            "source_url": asset.get("source_url", ""),
        }
        # image_assets only holds base64 for the first MAX_TOPIC_IMAGES of a
        # topic, so read the cached file rather than trusting what is there.
        payload = asset.get("base64") or _image_data_uri(entry["file"])
        if payload:
            entry["base64"] = payload
            entry["mime_type"] = (
                "image/png" if entry["file"].lower().endswith(".png") else "image/jpeg"
            )
        resolved.append(entry)
    return resolved


# The book names its own question types in the heading each block sits under;
# that is far more reliable than inferring a type from the question's wording.
SUBSECTION_KIND_LABEL = {
    "multiple_matching": "Multiple Matching",
    "mcq": "MCQ",
    "single_option": "MCQ (Single Correct)",
    "multiple_option": "MCQ (Multiple Correct)",
    "assertion_reason": "Assertion-Reason",
    "fill_blanks": "Fill in the Blanks",
    "true_false": "True/False",
    "matching": "Matching",
    "passage": "Passage Based",
    "case_based": "Case Study",
    "very_short_answer": "Very Short Answer",
    "short_answer": "Short Answer",
    "long_answer": "Long Answer",
    "integer": "Integer",
    "hots": "HOTS",
    "reasoning": "Reasoning",
    "statement_based": "Statement Based",
    "diagram_based": "Diagram Based",
    "textbook": "Textbook Question",
    "exemplar": "Exemplar Question",
    "subjective": "Subjective",
    "miscellaneous": "Miscellaneous",
}


MATCHING_TYPE_LABELS = frozenset({"Matching", "Multiple Matching"})


def _question_type_for(item: Dict[str, Any], array_key: str, question_text: str) -> str:
    """Type of a question, preferring the heading it was printed under.

    Only items with no heading -- illustrations and Check Your Knowledge, which
    are interleaved with the theory rather than filed under an exercise -- fall
    back to classifying the wording.
    """
    label = SUBSECTION_KIND_LABEL.get(item.get("subsection_kind") or "")
    if label:
        return label
    guessed = classify_question(
        question_text, section_type=array_key, subsection=item.get("subsection_title") or "",
    )
    lowered = (guessed or "").lower()
    if "mcq" in lowered:
        return "MCQ"
    if "integer" in lowered or "numerical" in lowered:
        return "Integer"
    if "match" in lowered:
        return "Matching"
    if "assertion" in lowered:
        return "Assertion-Reason"
    return guessed or "General"


# Competitive-exam provenance the books print inline ("... is [JSTSE] (a) ..."),
# 558 of them across the corpus. Useful metadata, noise inside the question, so
# it is lifted out to source.exam rather than discarded.
EXAM_TAG_RE = re.compile(
    r"\[\s*(NTSE|JSTSE|KVPY|NSO|IJSO|NSEJS|NSTSE|AIIMS|NEET|JEE)[^\]]{0,24}\]",
    re.IGNORECASE,
)
# The banner a Check Your Knowledge prompt is printed under. OCR doubles it
# ("Check Your Check Your Knowledge Knowledge") and breaks it across lines.
# It only counts as a banner when it stands on its own line: a question whose
# own wording opens "Check your knowledge of ..." is content, not furniture.
CYK_BANNER_RE = re.compile(
    r"^[ \t]*(?:[→>]\s*)?(?:Time\s+to\s+)?(?:Check\s+Your\s+)+Knowledge(?:\s+Knowledge)*"
    r"[ \t]*[-–—:.]*[ \t]*(?=\n|$)",
    re.IGNORECASE,
)
# A question or answer runs on into the furniture that follows it on the page:
# the Check Your Knowledge banner, or the next exercise's heading and its
# DIRECTIONS preamble. Everything past that boundary is extracted separately as
# its own items, so keeping it here only duplicates them.
RUNON_BOUNDARY_RES = (
    re.compile(
        r"^[ \t]*(?:[→>]\s*)?(?:Time\s+to\s*\n?\s*)?(?:Check\s+Your\s*\n?\s*)+Knowledge\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(r"^[ \t]*\\section\*\{", re.MULTILINE),
    re.compile(r"^[ \t]*DIRECTIONS\s*[:(]", re.IGNORECASE | re.MULTILINE),
    # An answer-key entry is a brief explanation; it never carries a SOLUTION
    # marker or an ILLUSTRATION heading of its own. Finding one means the entry
    # ran on into a worked example printed after it.
    re.compile(r"^[ \t]*(?:##\s*)?(?:SOLUTION|SOL\.)[ \t]*:?[ \t]*$",
               re.IGNORECASE | re.MULTILINE),
    re.compile(r"^[ \t]*(?:##\s*)?ILLUSTRATIO[NM]\b", re.IGNORECASE | re.MULTILINE),
)
LEFTOVER_TABLE_RULE_RE = re.compile(r"\|?\s*:?-{2,}:?\s*\|")
STRAY_MATH_DELIM_RE = re.compile(r"(?<!\$)\$\$(?!\$)")


def _trim_trailing_heading(text: str) -> str:
    """Drop a dangling exercise heading left at the end of a run-on cut.

    "... disinfection of water.\n\nMultiple Choice Questions (MCQs)" keeps the
    answer but not the title of the exercise that follows it.
    """
    lines = text.rstrip().split("\n")
    dropped = 0
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        # An option ("(d) activation energy") is content, and unguarded it looks
        # exactly like a short unpunctuated title -- so a heading is recognised
        # by starting on a word.
        if (dropped == 0 and len(last) <= 70
                and last[:1].isalpha()
                and not last.endswith((".", "?", ":", ";", ","))):
            lines.pop()
            dropped += 1
            continue
        break
    return "\n".join(lines)


def _cut_runon(text: str) -> str:
    """Cut a question/answer at the page furniture it ran on into.

    A block that legitimately *opens* on one of these markers (a Check Your
    Knowledge prompt, a bare ``DIRECTIONS :`` exercise) keeps it -- the cut only
    fires when real content precedes the boundary.
    """
    cut = len(text)
    for pattern in RUNON_BOUNDARY_RES:
        for match in pattern.finditer(text):
            if match.start() >= cut:
                break
            head = _trim_trailing_heading(text[: match.start()])
            if head.strip():
                cut = match.start()
                break
    if cut >= len(text):
        return text
    return _trim_trailing_heading(text[:cut])


def sanitize_question_text(text: Any) -> Tuple[Any, List[str]]:
    """Strip page furniture from a question, returning the exam tags removed.

    Only layout leftovers are touched -- an exam tag, the Check Your Knowledge
    banner, a run-on into the next exercise, a stranded table rule, an unpaired
    ``$$``. Nothing that carries meaning is removed.
    """
    if not isinstance(text, str) or not text.strip():
        return text, []

    # Mathpix renders whole pages in fullwidth forms, so a question's options
    # arrive as "（a）" and parse as nothing at all -- the reader sees the wide
    # glyphs and the question loses its options. Folding them back to ASCII here
    # happens before the options are parsed.
    text = normalize_fullwidth(text)
    tags = [match.group(1).upper() for match in EXAM_TAG_RE.finditer(text)]
    cleaned = EXAM_TAG_RE.sub(" ", text)
    cleaned = _cut_runon(cleaned)
    # Whatever banner survives the cut is this block's own heading, not content.
    cleaned = CYK_BANNER_RE.sub("", cleaned.lstrip(), count=1)
    cleaned = LEFTOVER_TABLE_RULE_RE.sub(" ", cleaned)
    # Only an unpaired delimiter is noise -- a matched "$$ ... $$" is display
    # math and removing it would strip the equation's markup, not furniture.
    if len(STRAY_MATH_DELIM_RE.findall(cleaned)) % 2:
        cleaned = STRAY_MATH_DELIM_RE.sub(" ", cleaned)
    # Collapse the runs of spaces those removals leave, without joining lines.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"^[ \t]*[-–—•]\s*", "", cleaned.strip())
    return cleaned.strip(), sorted(set(tags))


def _dedupe_key(item: Dict[str, Any], question_text: str) -> str:
    """Identity of a question for de-duplication across section arrays."""
    if item.get("id"):
        return f"id:{item['id']}"
    return "q:" + re.sub(r"\s+", " ", question_text).strip().lower()[:300]


def build_structured_questions_json(
    document: Dict[str, Any],
    book_slug: str,
) -> Dict[str, Any]:
    """Build structured questions JSON matching user target schema."""
    from edu_pipeline.storage.database import derive_attributes
    from edu_pipeline.generators.questions.mcq_parser import parse_options, parse_correct_index

    meta = document.get("metadata") or {}
    book_name = meta.get("name") or book_slug
    attrs = derive_attributes(book_name)

    class_val = attrs.get("class") or ""
    subject_val = attrs.get("subject") or ""
    source_file = meta.get("source_file") or f"{book_name}.pdf"

    SECTION_DISPLAY_MAP = {
        "illustrations": "Illustrations",
        "check_your_knowledge_items": "Check Your Knowledge",
        "textbook_exercises": "Exercise",
        "exercises": "Exercise",
        "practice_exercises": "Practice Questions",
        "examples": "Exercise",
        "case_studies": "Case Studies",
    }

    chapters = []
    source_topics = [t for t in (document.get("topics") or []) if isinstance(t, dict)]

    for topic in source_topics:
        chapter_num = int(topic.get("topic_number") or 1)
        chapter_name = chapter_name_from_topic(topic)
        # Raw CDN links in a question's text are rewritten to [image:...] tokens
        # so nothing in the exported document points off-machine.
        topic_url_to_id = {
            (asset or {}).get("source_url", ""): img_id
            for img_id, asset in (topic.get("image_assets") or {}).items()
            if (asset or {}).get("source_url")
        }
        questions = []
        q_counter = 1
        # ``examples`` is the union of the labelled buckets that precede it in
        # QA_SECTION_KEYS, so every question would otherwise be emitted twice.
        seen_questions: set = set()

        for array_key in QA_SECTION_KEYS:
            display_section = SECTION_DISPLAY_MAP.get(array_key, "Exercise")
            items = topic.get(array_key) or []
            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                q_text = item.get("question") or _problem_text(item)
                a_text = item.get("answer") or _solution_text(item)
                if not q_text and not a_text:
                    continue

                dedupe_key = _dedupe_key(item, q_text)
                if dedupe_key in seen_questions:
                    continue
                seen_questions.add(dedupe_key)

                q_text_clean = _tokenize_image_urls(enrich_qa_markdown_field(q_text), topic_url_to_id)
                a_text_clean = _tokenize_image_urls(enrich_qa_markdown_field(a_text), topic_url_to_id)
                # Page furniture is removed before options are parsed: an exam
                # tag sitting between the stem and "(a)" otherwise lands inside
                # the first option.
                q_text_clean, exam_tags = sanitize_question_text(q_text_clean)
                a_text_clean, _ = sanitize_question_text(a_text_clean)

                target_q_type = _question_type_for(item, array_key, q_text_clean)

                parsed_stem, option_list = parse_options(q_text_clean)
                options_dict = None
                parsed_answer = None
                matching_lists = None

                # Both matching sub-kinds carry two lists; gating on the plain
                # "Matching" label alone sends "Multiple Matching" down the MCQ
                # path, where Column I entries become answer options.
                matching = (parse_matching_question(q_text_clean)
                            if target_q_type in MATCHING_TYPE_LABELS else None)
                if matching:
                    # Matching questions carry their two lists as first-class
                    # fields; options[] holds the combination choices when the
                    # book prints them, and is empty when it expects a direct
                    # pairing instead.
                    q_text_clean = matching["question"] or q_text_clean
                    matching_lists = matching
                    options_dict = matching["options"]
                    parsed_answer = parse_matching_answer(a_text_clean, matching["options"])
                elif option_list and len(option_list) >= 2:
                    letters = ["a", "b", "c", "d"]
                    options_dict = {letters[i]: option_list[i] for i in range(min(len(option_list), 4))}
                    correct_idx = parse_correct_index(a_text_clean, option_list)
                    if correct_idx is not None and correct_idx < len(letters):
                        parsed_answer = letters[correct_idx]
                    else:
                        parsed_answer = a_text_clean if a_text_clean else None
                elif item.get("options") and isinstance(item["options"], dict):
                    options_dict = item["options"]
                    parsed_answer = a_text_clean or item.get("answer")
                elif item.get("options") and isinstance(item["options"], list):
                    letters = ["a", "b", "c", "d"]
                    opts = item["options"]
                    options_dict = {letters[i]: opts[i] for i in range(min(len(opts), 4))}
                    parsed_answer = a_text_clean or item.get("answer")
                else:
                    options_dict = None
                    parsed_answer = a_text_clean if a_text_clean else None

                explanation, _ = sanitize_question_text(
                    _tokenize_image_urls(item.get("explanation"), topic_url_to_id))
                explanation = explanation or (
                    a_text_clean if (options_dict and parsed_answer and str(parsed_answer) != str(a_text_clean)) else None
                )

                pdf_page = item.get("pdf_page_number") or topic.get("pdf_page_number")
                printed_page = item.get("printed_page_number") or topic.get("printed_page_number")

                questions.append({
                    "_order": item.get("source_order", 10 ** 9),
                    "question_number": str(q_counter),
                    "question_type": target_q_type,
                    "source": {
                        "file_name": source_file,
                        "pdf_page_number": pdf_page,
                        "printed_page_number": printed_page,
                        "section": item.get("section_name") or display_section,
                        "heading": item.get("subsection_title") or "",
                        # Which competitive exam the book credits the question
                        # to; kept here rather than left inline in the text.
                        **({"exam": exam_tags} if exam_tags else {}),
                    },
                    # The shared passage a question refers back to. Named
                    # question_stem so a consumer can show it above the question
                    # without re-deriving which questions share it.
                    **({"question_stem": sanitize_question_text(_tokenize_image_urls(
                        enrich_qa_markdown_field(item["passage"]), topic_url_to_id))[0]}
                       if str(item.get("passage") or "").strip() else {}),
                    "question": q_text_clean,
                    **({"list_1": matching_lists["list_1"],
                        "list_2": matching_lists["list_2"]} if matching_lists else {}),
                    "options": options_dict,
                    "answer": parsed_answer,
                    "explanation": explanation,
                    "images": _resolve_images(topic, item),
                })
                q_counter += 1

        # Sections are collected bucket by bucket, so restore the sequence the
        # questions appear in inside the book before numbering them.
        questions.sort(key=lambda q: q["_order"])
        for index, question in enumerate(questions, start=1):
            question.pop("_order", None)
            question["question_number"] = str(index)

        chapters.append({
            "chapter_number": chapter_num,
            "chapter_name": chapter_name,
            "questions": questions,
        })

    return {
        "class": class_val,
        "subject": subject_val,
        "book_name": book_name,
        "source_file": source_file,
        "chapters": chapters,
    }


def build_structured_theory_json(
    document: Dict[str, Any],
    book_slug: str,
) -> Dict[str, Any]:
    """Build the theory half of a book, mirroring the questions JSON envelope.

    Questions and theory are exported as two documents over the same
    ``chapters[]`` spine so either can be loaded, reviewed or regenerated
    without carrying the other.
    """
    from edu_pipeline.storage.database import derive_attributes

    meta = document.get("metadata") or {}
    book_name = meta.get("name") or book_slug
    attrs = derive_attributes(book_name)
    source_file = meta.get("source_file") or f"{book_name}.pdf"

    chapters = []
    for topic in (document.get("topics") or []):
        if not isinstance(topic, dict):
            continue
        topic_url_to_id = {
            (asset or {}).get("source_url", ""): img_id
            for img_id, asset in (topic.get("image_assets") or {}).items()
            if (asset or {}).get("source_url")
        }
        sections = []
        for index, section in enumerate(topic.get("theory_sections") or [], start=1):
            if not isinstance(section, dict):
                continue
            markdown = _tokenize_image_urls(
                enrich_qa_markdown_field(section.get("markdown") or ""), topic_url_to_id)
            title = section.get("topics") or section.get("title") or f"Section {index}"
            if not str(markdown).strip() and not str(title).strip():
                continue
            sections.append({
                "section_number": str(index),
                "title": title,
                "section_kind": section.get("section_kind") or "theory",
                "source": {
                    "file_name": source_file,
                    "pdf_page_number": topic.get("pdf_page_number"),
                    "printed_page_number": topic.get("printed_page_number"),
                },
                "markdown": markdown,
                "images": _resolve_images(topic, {"markdown": markdown}),
            })

        chapters.append({
            "chapter_number": int(topic.get("topic_number") or 1),
            "chapter_name": chapter_name_from_topic(topic),
            "page_range": topic.get("page_range") or "",
            "summary": _tokenize_image_urls(
                enrich_qa_markdown_field(topic.get("summary") or ""), topic_url_to_id),
            "key_points": [
                enrich_qa_markdown_field(point) if isinstance(point, str)
                else point.get("text", "") if isinstance(point, dict) else ""
                for point in (topic.get("key_points") or [])
            ],
            "sections": sections,
        })

    return {
        "class": attrs.get("class") or "",
        "subject": attrs.get("subject") or "",
        "book_name": book_name,
        "source_file": source_file,
        "chapters": chapters,
    }


def save_theory_json_from_document(
    document: Dict[str, Any],
    book_slug: str,
    output_path: str,
) -> str:
    export = build_structured_theory_json(document, book_slug)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(export, handle, indent=2, ensure_ascii=False)
    print(f"Saved structured theory JSON: {output_path}")
    return output_path


def save_questions_json_from_document(
    document: Dict[str, Any],
    book_slug: str,
    output_path: str,
) -> str:
    export = build_structured_questions_json(document, book_slug)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(export, handle, indent=2, ensure_ascii=False)
    print(f"Saved structured questions JSON: {output_path}")
    return output_path


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
