"""Markdown splitting, frontmatter parsing, and path derivation utilities.

Handles chunking the book's Mathpix markdown into topic-level markdown files,
extracting frontmatter metadata, and resolving directory layouts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from typing import Dict, List, Optional, Tuple

from edu_pipeline.shared.paths import MATHPIX_CACHE_DIR, OUTPUT_DIR


@dataclass
class TopicMeta:
    topic_number: int
    topic_name: str
    page_range: str = ""


@dataclass
class TopicChunk:
    meta: TopicMeta
    markdown: str
    start_line: int
    end_line: int
    headings: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class BookPaths:
    base_name: str
    mathpix_md: str
    output_json: str
    book_output_dir: str
    topics_md_dir: str
    topics_llm_md_dir: str
    topics_json_dir: str
    topics_db_json_dir: str
    manifest_path: str
    llm_md_manifest_path: str
    db_manifest_path: str
    db_output_json: str
    qa_table_output_json: str
    topics_study_notes_dir: str
    study_notes_output_json: str


def derive_paths(pdf_path: str) -> tuple[str, str, str]:
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    cache_path = os.path.join(MATHPIX_CACHE_DIR, f"{base_name}_mathpix.md")
    book_output_dir = os.path.join(OUTPUT_DIR, base_name)
    output_json = os.path.join(book_output_dir, f"{base_name}_final.json")
    return base_name, cache_path, output_json


def derive_book_paths(pdf_path: str) -> BookPaths:
    base_name, cache_path, output_json = derive_paths(pdf_path)
    book_output_dir = os.path.join(OUTPUT_DIR, base_name)
    qa_table_output_json = os.path.join(book_output_dir, f"{base_name}_qa_table.json")
    study_notes_output_json = os.path.join(book_output_dir, f"{base_name}_study_notes.json")
    topics_md_dir = os.path.join(book_output_dir, "topics_md")
    topics_llm_md_dir = os.path.join(book_output_dir, "topics_llm_md")
    topics_json_dir = os.path.join(book_output_dir, "topics_json")
    topics_study_notes_dir = os.path.join(book_output_dir, "topics_study_notes")
    topics_db_json_dir = os.path.join(book_output_dir, "topics_db_json")
    manifest_path = os.path.join(topics_md_dir, "manifest.json")
    llm_md_manifest_path = os.path.join(topics_llm_md_dir, "manifest.json")
    db_manifest_path = os.path.join(topics_db_json_dir, "manifest.json")
    db_output_json = os.path.join(OUTPUT_DIR, f"{base_name}_db.json")
    return BookPaths(
        base_name=base_name,
        mathpix_md=cache_path,
        output_json=output_json,
        book_output_dir=book_output_dir,
        topics_md_dir=topics_md_dir,
        topics_llm_md_dir=topics_llm_md_dir,
        topics_json_dir=topics_json_dir,
        topics_db_json_dir=topics_db_json_dir,
        manifest_path=manifest_path,
        llm_md_manifest_path=llm_md_manifest_path,
        db_manifest_path=db_manifest_path,
        db_output_json=db_output_json,
        qa_table_output_json=qa_table_output_json,
        topics_study_notes_dir=topics_study_notes_dir,
        study_notes_output_json=study_notes_output_json,
    )


def topic_md_filename(meta: TopicMeta) -> str:
    from edu_pipeline.extraction.topic_extractor import slugify
    return f"topic_{meta.topic_number:02d}_{slugify(meta.topic_name)}.md"


def topic_theory_md_filename(meta: TopicMeta) -> str:
    from edu_pipeline.extraction.topic_extractor import slugify
    return f"topic_{meta.topic_number:02d}_{slugify(meta.topic_name)}_theory.md"


def topic_examples_md_filename(meta: TopicMeta) -> str:
    from edu_pipeline.extraction.topic_extractor import slugify
    return f"topic_{meta.topic_number:02d}_{slugify(meta.topic_name)}_examples.md"


def topic_json_path(book_paths: BookPaths, topic_number: int) -> str:
    return os.path.join(book_paths.topics_json_dir, f"topic_{topic_number:02d}.json")


def topic_db_json_path(book_paths: BookPaths, topic_number: int) -> str:
    return os.path.join(book_paths.topics_db_json_dir, f"topic_{topic_number:02d}.json")


def topic_llm_md_path(book_paths: BookPaths, meta: TopicMeta) -> str:
    return os.path.join(book_paths.topics_llm_md_dir, topic_md_filename(meta))


def make_db_id(book_slug: str, topic_number: int, category: str, seq: int) -> str:
    from edu_pipeline.extraction.topic_extractor import slugify
    slug = slugify(book_slug).replace("-", "_") or "book"
    return f"{slug}_t{topic_number:02d}_{category}_{seq:03d}"


def read_topic_markdown_body(md_path: str) -> str:
    with open(md_path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :].lstrip("\n")
    return text


def _parse_topic_md_frontmatter(md_path: str) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    if not md_path or not os.path.isfile(md_path):
        return meta
    with open(md_path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        meta[key.strip()] = val.strip()
    return meta


def _parse_line_range(lines_spec: str) -> Tuple[Optional[int], Optional[int]]:
    match = re.match(r"(\d+)\s*-\s*(\d+)", str(lines_spec or "").strip())
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def split_topics(markdown: str) -> List[TopicChunk]:
    from edu_pipeline.extraction.topic_extractor import (
        find_topic_start_lines,
        parse_contents_topics,
        H2_RE,
    )
    lines = markdown.splitlines()
    topic_metas = parse_contents_topics(lines)
    if not topic_metas:
        print("  Warning: no topics found in ## CONTENTS; cannot split markdown.")
        return []

    start_lines = find_topic_start_lines(lines, topic_metas)
    sorted_topics = sorted(topic_metas, key=lambda topic: topic.topic_number)
    chunks: List[TopicChunk] = []

    for i, meta in enumerate(sorted_topics):
        start = start_lines.get(meta.topic_number)
        if start is None:
            print(f"  Warning: could not locate start for topic {meta.topic_number}: {meta.topic_name}")
            continue
        if i + 1 < len(sorted_topics):
            next_num = sorted_topics[i + 1].topic_number
            end = start_lines.get(next_num, len(lines)) - 1
        else:
            end = len(lines) - 1
        chunk_lines = lines[start : end + 1]
        headings: List[Dict[str, str]] = []
        for offset, raw in enumerate(chunk_lines):
            h2 = H2_RE.match(raw.strip())
            if h2:
                headings.append({"line": start + offset + 1, "title": h2.group(1).strip()})
        chunks.append(TopicChunk(
            meta=meta,
            markdown="\n".join(chunk_lines),
            start_line=start + 1,
            end_line=end + 1,
            headings=headings,
        ))
    return chunks
