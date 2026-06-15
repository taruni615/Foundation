"""Topic-wise textbook extraction pipeline (format v3 only).

Pipeline (6 steps)
------------------
  Step 1/6  Resolve PDF (or continue from cached Markdown)
  Step 2/6  Mathpix -> cached book Markdown (Mathpix_Cache/<book>.md)
  Step 3/6  Split cache -> per-topic Markdown (outputs/<book>/topics_md/)
  Step 4-5/6  Ollama enrichment -> per-topic JSON (outputs/<book>/topics_json/)
  Step 6/6  Merge -> outputs/<book>/<book>_final.json (+ <book>_qa_table.json)

No v2 flat export, no db-format exporter, no MySQL insert.
"""

from __future__ import annotations


import argparse
import base64
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from xml.etree import ElementTree as ET

import requests

try:
    import latex2mathml.converter as latex2mathml_converter
except ImportError:
    latex2mathml_converter = None


DEFAULT_PDF_PATH = os.path.join("Input_PDFs", "10 PHYSICS FOUNDATION.pdf")

MATHPIX_APP_ID = os.environ.get("MATHPIX_APP_ID", "mylp_936a22_ae4623")
MATHPIX_APP_KEY = os.environ.get("MATHPIX_APP_KEY", "7633cfe17550debec4ab73eb9ae3bedcb49de0774edb6ed2d249ca979d47b2d6")

MATHPIX_POLL_SECONDS = 2
MATHPIX_API_BASE = "https://api.mathpix.com/v3/pdf"
MATHPIX_CACHE_DIR = "Mathpix_Cache"
MATHPIX_CACHE_DIR_ALIASES = ["Mathpix_Cache", "mathpix_cache", "Mathpix_Cache".lower()]
OUTPUT_DIR = "outputs"
IMAGE_CACHE_DIR = os.path.join(OUTPUT_DIR, "image_cache")
LLM_CACHE_DIR = os.path.join(OUTPUT_DIR, ".cache")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "1800"))
OLLAMA_RETRIES = int(os.environ.get("OLLAMA_RETRIES", "3"))
MAX_PRACTICE_EXERCISES = int(os.environ.get("MAX_PRACTICE_EXERCISES", "6"))
LLM_FIELD_MAX_CHARS = int(os.environ.get("LLM_FIELD_MAX_CHARS", "1500"))
LLM_THEORY_PREVIEW_CHARS = int(os.environ.get("LLM_THEORY_PREVIEW_CHARS", "3500"))
LLM_MAX_EXAMPLES = int(os.environ.get("LLM_MAX_EXAMPLES", "8"))
LLM_MAX_PRACTICE = int(os.environ.get("LLM_MAX_PRACTICE", "12"))
LLM_MAX_CASE_STUDIES = int(os.environ.get("LLM_MAX_CASE_STUDIES", "3"))
LLM_MAX_USER_CHARS = int(os.environ.get("LLM_MAX_USER_CHARS", "48000"))
LLM_MD_MAX_CHARS = int(os.environ.get("LLM_MD_MAX_CHARS", "48000"))
OLLAMA_MD_NUM_PREDICT = int(os.environ.get("OLLAMA_MD_NUM_PREDICT", "16384"))
MAX_TOPIC_IMAGES = int(os.environ.get("MAX_TOPIC_IMAGES", "80"))
CONCEPT_MAP_LOOKBACK_LINES = int(os.environ.get("CONCEPT_MAP_LOOKBACK_LINES", "50"))
CONCEPT_MAP_OPENING_LINES = int(os.environ.get("CONCEPT_MAP_OPENING_LINES", "80"))
CONCEPT_MAP_BACKWARD_LINES = int(os.environ.get("CONCEPT_MAP_BACKWARD_LINES", "45"))
CONCEPT_MAP_MULTI_CROP_MAX = int(os.environ.get("CONCEPT_MAP_MULTI_CROP_MAX", "12"))
MIN_CONCEPT_MAP_IMAGE_AREA = int(os.environ.get("MIN_CONCEPT_MAP_IMAGE_AREA", "120000"))
FOUNDATION_LOGO_MIN_X = int(os.environ.get("FOUNDATION_LOGO_MIN_X", "1300"))
FOUNDATION_LOGO_MAX_Y = int(os.environ.get("FOUNDATION_LOGO_MAX_Y", "650"))
FOUNDATION_LOGO_BAND_PX = int(os.environ.get("FOUNDATION_LOGO_BAND_PX", "460"))
LLM_SUMMARY_MAX_SECTIONS = int(os.environ.get("LLM_SUMMARY_MAX_SECTIONS", "30"))
LLM_SUMMARY_SECTION_EXCERPT = int(os.environ.get("LLM_SUMMARY_SECTION_EXCERPT", "1200"))
LLM_SUMMARY_BATCH_SIZE = int(os.environ.get("LLM_SUMMARY_BATCH_SIZE", "12"))
STUDENT_SUMMARY_MAX_CHARS = int(os.environ.get("STUDENT_SUMMARY_MAX_CHARS", "650"))
CHAPTER_OVERVIEW_MAX_CHARS = int(os.environ.get("CHAPTER_OVERVIEW_MAX_CHARS", "900"))
CHAPTER_OVERVIEW_HEADING = "Chapter overview"

STUDENT_CHAPTER_OVERVIEW_SYSTEM = (
    "You write a single chapter-level revision overview for Class 10 physics students. "
    "Return ONLY valid JSON: "
    '{"chapter_overview": "string"}. '
    "Write 5-8 short sentences in plain English that cover the whole chapter in one place: "
    "main theme, most important ideas, key laws/formulas to remember, and how the parts connect. "
    "Do NOT copy textbook sentences. Do NOT use markdown headings inside chapter_overview."
)

STUDENT_SUMMARY_SYSTEM = (
    "You write short topic-wise revision notes for Class 10 physics students (ages 14-16). "
    "Return ONLY valid JSON: "
    '{"sections": [{"heading": "string", "level": 2|3, "summary": "string"}]}. '
    "Each item is ONE theory topic/subtopic (not the whole chapter). Rules:\n"
    "- level 2 = main topic heading, level 3 = subtopic under that topic.\n"
    "- 3-5 short sentences per section in plain, easy English (not textbook prose).\n"
    "- Explain what to remember for exams: main idea, key terms, one central formula or law "
    "if relevant, and a quick memory tip or common mistake when useful.\n"
    "- Write in your own words. Do NOT copy sentences from the excerpt.\n"
    "- Do NOT repeat the section heading inside the summary.\n"
    "- No figure captions, page numbers, MCQs, or long bullet lists from the source.\n"
    "- Preserve any [image:img_NNN] tokens exactly if they appear in the excerpt.\n"
    "- Use the same heading text as provided in the input."
)


def skip_images() -> bool:
    """When True, do not download, embed, or export image base64 (faster, smaller JSON)."""
    return os.environ.get("SKIP_IMAGES", "1").lower() in ("1", "true", "yes")


def skip_mathml() -> bool:
    """When True, leave $...$ / $$...$$ LaTeX in text (no MathML conversion)."""
    return os.environ.get("SKIP_MATHML", "0").lower() in ("1", "true", "yes")


MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
HTML_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
MATHPIX_URL_RE = re.compile(r"https?://[^)\s]*mathpix[^)\s]*", re.IGNORECASE)


def strip_images_from_markdown(md: str) -> str:
    """Remove all markdown/HTML images (standalone lines, table cells, headings)."""
    lines: List[str] = []
    for raw_line in md.splitlines():
        line = HTML_IMG_RE.sub("", raw_line)
        line = MARKDOWN_IMAGE_RE.sub("", line)
        line = BR_TAG_RE.sub(" ", line)
        line = re.sub(r"[ \t]{2,}", " ", line).rstrip()
        if not line.strip():
            continue
        lines.append(line)

    out: List[str] = []
    prev_blank = False
    for line in lines:
        blank = not line.strip()
        if blank and prev_blank:
            continue
        out.append(line)
        prev_blank = blank
    return compact_markdown("\n".join(out))


def strip_markdown_images(text: str) -> str:
    """Remove images from JSON text fields when SKIP_IMAGES is enabled."""
    if not text or not skip_images():
        return text or ""
    return strip_images_from_markdown(text)


def sanitize_topic_text_fields(topic: Dict[str, Any]) -> Dict[str, Any]:
    """Strip images from all markdown-bearing fields in a topic dict."""
    if not skip_images():
        return topic
    if isinstance(topic.get("summary"), str):
        topic["summary"] = strip_markdown_images(topic["summary"])
    if isinstance(topic.get("theory_notes"), str):
        topic["theory_notes"] = strip_markdown_images(topic["theory_notes"])
    for sec in topic.get("theory_sections") or []:
        if isinstance(sec.get("markdown"), str):
            sec["markdown"] = strip_markdown_images(sec["markdown"])
        heading_key = "topics" if "topics" in sec else "title"
        if isinstance(sec.get(heading_key), str):
            sec[heading_key] = strip_markdown_images(sec[heading_key])
    for key in (
        "illustrations", "check_your_knowledge_items", "textbook_exercises",
        "exercises", "examples",
    ):
        for item in topic.get(key) or []:
            if not isinstance(item, dict):
                continue
            for field in (
                "title", "problem", "solution", "problem_markdown",
                "solution_markdown", "prompt_markdown", "question",
            ):
                if isinstance(item.get(field), str):
                    item[field] = strip_markdown_images(item[field])
    for cs in topic.get("case_studies") or []:
        if isinstance(cs.get("title"), str):
            cs["title"] = strip_markdown_images(cs["title"])
        if isinstance(cs.get("description"), str):
            cs["description"] = strip_markdown_images(cs["description"])
        if isinstance(cs.get("body_markdown"), str):
            cs["body_markdown"] = strip_markdown_images(cs["body_markdown"])
        for q in cs.get("questions") or []:
            if isinstance(q, str):
                pass  # handled below via list mutation
    for i, kp in enumerate(topic.get("key_points") or []):
        if isinstance(kp, str):
            topic["key_points"][i] = strip_markdown_images(kp)
        elif isinstance(kp, dict) and isinstance(kp.get("text"), str):
            kp["text"] = strip_markdown_images(kp["text"])
    for pe in topic.get("practice_exercises") or []:
        if isinstance(pe.get("question"), str):
            pe["question"] = strip_markdown_images(pe["question"])
    return topic

CHAPTER_RE = re.compile(r"^##\s+(\d+)\s+(.+?)\s*$")
SECTION_RE = re.compile(r"^###\s+(\d+\.\d+)\s+(.+?)\s*$")
EXERCISE_RE = re.compile(r"^##\s+Exercise\s+(\d+\.\d+[A-Za-z])\s*$", re.IGNORECASE)
REVISION_RE = re.compile(r"^##\s+Revision exercise\s+(\d+)\s*$", re.IGNORECASE)
EXAM_RE = re.compile(r"^##\s+Examination-style exercise\s+(\d+)\s*$", re.IGNORECASE)
ANSWER_HEADING_RE = re.compile(
    r"^(?:##\s+)?(?:(Exercise)\s+(\d+\.\d+[A-Za-z])|(Revision exercise)\s+(\d+)|(Examination-style exercise)\s+(\d+))\s*$",
    re.IGNORECASE,
)
QUESTION_RE = re.compile(r"^(\d+)\.\s*(.*)$")
TOC_DOTTED_RE = re.compile(r"^(.+?)\s+\.{3,}\s+([A-Za-z0-9ivxlcdmIVXLCDM]+)\s*$")
TOC_TABLE_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*([A-Za-z0-9ivxlcdmIVXLCDM]+)\s*\|$")
TOC_TOPIC_RE = re.compile(r"^(\d+)\.\s+(.+?)(?:\s*\.{3,}\s*|\s*)(\d+-\d+)\s*$")
TOC_HEADING_TOPIC_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s+(\d+-\d+)\s*$")
TOC_PAGE_RANGE_RE = re.compile(r"^(\d+-\d+)\s*$")
TOC_TOPIC_NUM_ONLY_RE = re.compile(r"^(\d+)\.\s+(.+)$")
# Mathpix sometimes emits page ranges as $63-102$ or glued to the title (Reproduce103-142).
TOC_MATHPIX_PAGE_SUFFIX_RE = re.compile(r"\$?(\d+-\d+)\$?\s*$")
TOPIC_CHAPTER_ALIASES: Dict[int, List[str]] = {
    1: ["life process", "life processes", "what are the life processes"],
    4: ["heredity", "heredity and evolution"],
    5: ["our environment", "ecosystem"],
    8: ["biomolecules"],
}
SUBSECTION_NOT_CHAPTER_RE = re.compile(
    r"origin of life|evolution vs|case\s*[-:]?\s*(study|[iv]+)|connecting topic|"
    r"concept\s*map|foundation\s*builder|exercise\s+\d",
    re.IGNORECASE,
)
GENERIC_TOPIC_FIRST_WORDS = frozenset({
    "life", "process", "environment", "evolution", "natural", "management",
})
CONCEPT_MAP_HEADING_RE = re.compile(
    r"(?:^##\s*)?\(?\s*"
    r"(?:C\s*O\s*N\s*C\s*E\s*P\s*T\s*M?\s*A?\s*P"
    r"|CONCEPT\s*M?\s*A?\s*P)",
    re.IGNORECASE,
)
CHAPTER_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(https?://[^)]+\)")
STOP_TITLE_WORDS = frozenset({
    "the", "a", "an", "of", "and", "in", "to", "its", "for", "on", "or", "with", "by",
})
FALSE_CHAPTER_HEADING_RE = re.compile(
    r"^(\d+)\.\s+(\([a-d]\)|Steps of construction|Column\s*-?\s*I\b)|^\(\d+\)",
    re.IGNORECASE,
)

H2_RE = re.compile(r"^##\s+(.+?)\s*$")
H3_RE = re.compile(r"^###\s+(.+?)\s*$")
SUMMARY_SECTION_MAX_CHARS = int(os.environ.get("SUMMARY_SECTION_MAX_CHARS", "700"))
SUMMARY_SUBSECTION_MAX_CHARS = int(os.environ.get("SUMMARY_SUBSECTION_MAX_CHARS", "450"))
SUMMARY_MAX_PARAGRAPHS = int(os.environ.get("SUMMARY_MAX_PARAGRAPHS", "2"))
CASE_STUDY_RE = re.compile(r"^##\s+CASE STUDY", re.IGNORECASE)
ILLUSTRATION_RE = re.compile(r"^##\s+ILLUSTRATION\s*:?\s*(.+)$", re.IGNORECASE)
SOLUTION_RE = re.compile(r"^##\s+SOLUTION\s*:?\s*$", re.IGNORECASE)
NON_THEORY_SECTION_RE = re.compile(
    r"^(ILLUSTRATION|CASE\s+STUDY|Exercise|Text-?Book|Foundation\s+Builder|Exemplar|"
    r"Excercise|Single\s+Option|Multiple\s+Option|DIRECTIONS|SOLUTION|Physics)$",
    re.IGNORECASE,
)
CHECK_KNOWLEDGE_RE = re.compile(
    r"(Time to\s+)?Check Your Knowledge|Check your knowledge",
    re.IGNORECASE,
)
# Top-level exercise blocks only (not "## Text-Book Exercise" subsections).
EXERCISE_HEADING_RE = re.compile(
    r"^##\s+Exercise(?:\s+\d+|\s+\d+\s*<br\s*/?>|\s*<br\s*/?>|\s+Foundation|\s*$|\s+(?!Questions))",
    re.IGNORECASE,
)
EXERCISE_HEADING_EXCERCISE_RE = re.compile(r"^##\s+Excercise\s+\d+", re.IGNORECASE)
EXERCISE_SUBSECTION_PLAIN_RE = re.compile(
    r"^(Text-?Book\s+(?:Exercise|Questions)|Exemplar\s+Questions|"
    r"Foundation\s+Builder|Revision\s+Exercise|Examination-Style\s+Exercise)\s*:?\s*$",
    re.IGNORECASE,
)
EXERCISE_BANK_START_RE = re.compile(
    r"^##\s+(?:Single\s+Option|Multiple\s+Option|Passage\s+Based|Assertion|"
    r"Multiple\s+Matching|Integer/|MISCELLANEOUS\s+SOLVED)",
    re.IGNORECASE,
)
DIRECTIONS_QS_RE = re.compile(r"^DIRECTIONS\s*\(Qs", re.IGNORECASE)
MISCELLANEOUS_SOLVED_RE = re.compile(r"^##\s+MISCELLANEOUS\s+SOLVED", re.IGNORECASE)
INLINE_SOL_RE = re.compile(r"^(?:Sol\.|SOLUTION)\s*:?\s*$", re.IGNORECASE)
KEY_POINTS_RE = re.compile(r"^##\s+(Keep in Memory|Learn More)", re.IGNORECASE)
STOP_SOLUTION_RE = re.compile(
    r"^##\s+(ILLUSTRATION|CASE STUDY|Exercise|Text-?Book|Foundation Builder|Keep in Memory|Learn More|CONNECTING)",
    re.IGNORECASE,
)
IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)]+)\)")
LATEX_INLINE_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", re.DOTALL)
LATEX_BLOCK_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
LATEX_LEAK_RE = re.compile(r"\$[^$]+\$|\$\$[^$]+\$\$")


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


def derive_paths(pdf_path: str) -> tuple[str, str, str]:
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    cache_path = os.path.join(MATHPIX_CACHE_DIR, f"{base_name}_mathpix.md")
    book_output_dir = os.path.join(OUTPUT_DIR, base_name)
    output_json = os.path.join(book_output_dir, f"{base_name}_final.json")
    return base_name, cache_path, output_json


DB_SCHEMA_VERSION = "1.0"
RELATIONAL_SCHEMA_VERSION = "2.0"

# DATABASE CONFIGURATION (override via environment variables)
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "root")
DB_NAME = os.environ.get("DB_NAME", "foundation")
DB_CHARSET = os.environ.get("DB_CHARSET", "utf8mb4")
DB_COLLATION = os.environ.get("DB_COLLATION", "utf8mb4_unicode_ci")

# Insert child tables after parents (FK-style dependencies on topic_number / section ids).
TABLE_INSERT_ORDER: List[str] = [
    "topics",
    "theory_sections",
    "illustration_problems",
    "illustration_solutions",
    "check_your_knowledge",
    "case_studies",
    "case_study_prompts",
    "exercise_sections",
    "questions",
    "key_points",
    "image_assets",
]

RELATIONAL_TABLE_PRIMARY_KEYS: Dict[str, List[str]] = {
    "topics": ["id"],
    "theory_sections": ["id"],
    "illustration_problems": ["id"],
    "illustration_solutions": ["id"],
    "check_your_knowledge": ["id"],
    "case_studies": ["id"],
    "case_study_prompts": ["id"],
    "exercise_sections": ["id"],
    "questions": ["id"],
    "key_points": ["id"],
    "image_assets": ["id"],
}

# MySQL column types for CREATE TABLE / parameterized INSERT tooling.
MYSQL_COLUMN_TYPES: Dict[str, Dict[str, str]] = {
    "topics": {
        "id": "VARCHAR(128) NOT NULL",
        "topic_number": "INT NOT NULL",
        "topic_name": "VARCHAR(512) NOT NULL",
        "page_range": "VARCHAR(32) DEFAULT NULL",
        "summary": "LONGTEXT",
        "source_topic_md": "VARCHAR(512) DEFAULT NULL",
    },
    "theory_sections": {
        "id": "VARCHAR(128) NOT NULL",
        "topic_number": "INT NOT NULL",
        "order": "INT NOT NULL",
        "title": "VARCHAR(512) NOT NULL",
        "markdown": "LONGTEXT NOT NULL",
    },
    "illustration_problems": {
        "id": "VARCHAR(128) NOT NULL",
        "topic_number": "INT NOT NULL",
        "order": "INT NOT NULL",
        "title": "VARCHAR(512) DEFAULT NULL",
        "problem_markdown": "LONGTEXT",
    },
    "illustration_solutions": {
        "id": "VARCHAR(128) NOT NULL",
        "illustration_problem_id": "VARCHAR(128) NOT NULL",
        "topic_number": "INT NOT NULL",
        "order": "INT NOT NULL",
        "solution_markdown": "LONGTEXT",
    },
    "check_your_knowledge": {
        "id": "VARCHAR(128) NOT NULL",
        "topic_number": "INT NOT NULL",
        "order": "INT NOT NULL",
        "prompt_markdown": "LONGTEXT",
        "solution_markdown": "LONGTEXT",
    },
    "case_studies": {
        "id": "VARCHAR(128) NOT NULL",
        "topic_number": "INT NOT NULL",
        "order": "INT NOT NULL",
        "title": "VARCHAR(512) DEFAULT NULL",
        "body_markdown": "LONGTEXT",
    },
    "case_study_prompts": {
        "id": "VARCHAR(128) NOT NULL",
        "case_study_id": "VARCHAR(128) NOT NULL",
        "topic_number": "INT NOT NULL",
        "order": "INT NOT NULL",
        "label": "VARCHAR(64) DEFAULT NULL",
        "prompt_markdown": "LONGTEXT",
    },
    "exercise_sections": {
        "id": "VARCHAR(128) NOT NULL",
        "topic_number": "INT NOT NULL",
        "order": "INT NOT NULL",
        "title": "VARCHAR(512) DEFAULT NULL",
        "kind": "VARCHAR(64) DEFAULT NULL",
        "instruction_markdown": "LONGTEXT",
    },
    "questions": {
        "id": "VARCHAR(128) NOT NULL",
        "exercise_section_id": "VARCHAR(128) NOT NULL",
        "topic_number": "INT NOT NULL",
        "order": "INT NOT NULL",
        "number": "VARCHAR(32) DEFAULT NULL",
        "prompt_markdown": "LONGTEXT",
        "solution_markdown": "LONGTEXT",
        "question_type": "VARCHAR(64) DEFAULT NULL",
        "subsection_title": "VARCHAR(512) DEFAULT NULL",
    },
    "key_points": {
        "id": "VARCHAR(128) NOT NULL",
        "topic_number": "INT NOT NULL",
        "order": "INT NOT NULL",
        "text": "TEXT NOT NULL",
    },
    "image_assets": {
        "id": "VARCHAR(128) NOT NULL",
        "topic_number": "INT NOT NULL",
        "caption": "VARCHAR(512) DEFAULT NULL",
        "mime_type": "VARCHAR(64) DEFAULT NULL",
        "base64": "LONGTEXT",
    },
}


def get_table_name_map(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Optional logical→physical table rename map (embedded in *_tables.json only)."""
    mapping: Dict[str, str] = {}
    raw = os.environ.get("DB_TABLE_MAP", "").strip()
    if raw:
        mapping.update(json.loads(raw))
    if extra:
        mapping.update({str(k): str(v) for k, v in extra.items()})
    return mapping


def get_db_config() -> Dict[str, Any]:
    """Optional connection metadata embedded in *_tables.json (not used for MySQL here)."""
    return {
        "engine": "mysql",
        "host": DB_HOST,
        "port": DB_PORT,
        "user": DB_USER,
        "password": DB_PASSWORD,
        "database": DB_NAME,
        "charset": DB_CHARSET,
        "collation": DB_COLLATION,
        "table_name_map": get_table_name_map(),
    }


def get_insertion_config(table_names: Optional[List[str]] = None) -> Dict[str, Any]:
    """Metadata required by insert scripts (order, keys, SQL types)."""
    names = table_names or list(RELATIONAL_TABLE_SCHEMA.keys())
    order = [t for t in TABLE_INSERT_ORDER if t in names]
    for t in names:
        if t not in order:
            order.append(t)
    tables_meta: Dict[str, Any] = {}
    for name in order:
        columns = RELATIONAL_TABLE_SCHEMA.get(name, [])
        tables_meta[name] = {
            "columns": columns,
            "column_types": {
                col: MYSQL_COLUMN_TYPES.get(name, {}).get(col, "TEXT")
                for col in columns
            },
            "primary_key": RELATIONAL_TABLE_PRIMARY_KEYS.get(name, ["id"]),
        }
    return {
        "table_order": order,
        "batch_size": int(os.environ.get("DB_INSERT_BATCH_SIZE", "100")),
        "on_duplicate": os.environ.get("DB_ON_DUPLICATE", "UPDATE"),
        "tables": tables_meta,
    }


# Column names per logical table (for SQL CREATE TABLE / imports).
RELATIONAL_TABLE_SCHEMA: Dict[str, List[str]] = {
    "topics": [
        "id", "topic_number", "topic_name", "page_range", "summary", "source_topic_md",
    ],
    "theory_sections": [
        "id", "topic_number", "order", "title", "markdown",
    ],
    "illustration_problems": [
        "id", "topic_number", "order", "title", "problem_markdown",
    ],
    "illustration_solutions": [
        "id", "illustration_problem_id", "topic_number", "order", "solution_markdown",
    ],
    "check_your_knowledge": [
        "id", "topic_number", "order", "prompt_markdown", "solution_markdown",
    ],
    "case_studies": [
        "id", "topic_number", "order", "title", "body_markdown",
    ],
    "case_study_prompts": [
        "id", "case_study_id", "topic_number", "order", "label", "prompt_markdown",
    ],
    "exercise_sections": [
        "id", "topic_number", "order", "title", "kind", "instruction_markdown",
    ],
    "questions": [
        "id", "exercise_section_id", "topic_number", "order", "number",
        "prompt_markdown", "solution_markdown", "question_type", "subsection_title",
    ],
    "key_points": [
        "id", "topic_number", "order", "text",
    ],
    "image_assets": [
        "id", "topic_number", "caption", "mime_type", "base64",
    ],
}
SOLUTIONS_HEADING_RE = re.compile(r"^##\s+SOLUTIONS\b", re.IGNORECASE)
EXERCISE_TOP_RE = re.compile(r"^##\s+Exercise\s+\d+", re.IGNORECASE)
EXERCISE_PLAIN_RE = re.compile(r"^Exercise\s+\d+", re.IGNORECASE)
ANSWER_LIKE_RE = re.compile(r"^\([a-d]\)|^[A-D]\)|^\([ivx]+\)", re.IGNORECASE)
CASE_PROMPT_RE = re.compile(
    r"^(CASE\s*-\s*[IVXLCDM]+|Q\.\s*\d+)\s*[:：]?\s*(.*)$",
    re.IGNORECASE,
)
QUESTION_TYPE_SECTION_RE = re.compile(
    r"(multiple choice|mcq|assertion|fill in the blank|true\s*/\s*false|match the following|"
    r"match following|passage\s+based|passage based|very short answer|short answer|"
    r"long answer|reasoning|hots|case study based|text\s*-\s*book|exemplar|"
    r"revision\s+exercise|examination|give answer in)",
    re.IGNORECASE,
)
DIRECTIONS_HEADING_RE = re.compile(r"^DIRECTIONS\s*:", re.IGNORECASE)
CASE_STUDY_MAIN_RE = re.compile(r"^CASE\s+STUDY\s*[-:]?\s*\d+", re.IGNORECASE)
MCQ_SECTION_RE = re.compile(r"^##\s+Multiple\s+Choice\s+Questions", re.IGNORECASE)


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


def derive_book_paths(pdf_path: str) -> BookPaths:
    base_name, cache_path, output_json = derive_paths(pdf_path)
    book_output_dir = os.path.join(OUTPUT_DIR, base_name)
    qa_table_output_json = os.path.join(book_output_dir, f"{base_name}_qa_table.json")
    topics_md_dir = os.path.join(book_output_dir, "topics_md")
    topics_llm_md_dir = os.path.join(book_output_dir, "topics_llm_md")
    topics_json_dir = os.path.join(book_output_dir, "topics_json")
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
    )


def topic_md_filename(meta: TopicMeta) -> str:
    return f"topic_{meta.topic_number:02d}_{slugify(meta.topic_name)}.md"


def topic_theory_md_filename(meta: TopicMeta) -> str:
    return f"topic_{meta.topic_number:02d}_{slugify(meta.topic_name)}_theory.md"


def topic_examples_md_filename(meta: TopicMeta) -> str:
    return f"topic_{meta.topic_number:02d}_{slugify(meta.topic_name)}_examples.md"


def topic_json_path(book_paths: BookPaths, topic_number: int) -> str:
    return os.path.join(book_paths.topics_json_dir, f"topic_{topic_number:02d}.json")


def topic_db_json_path(book_paths: BookPaths, topic_number: int) -> str:
    return os.path.join(book_paths.topics_db_json_dir, f"topic_{topic_number:02d}.json")


def topic_llm_md_path(book_paths: BookPaths, meta: TopicMeta) -> str:
    return os.path.join(book_paths.topics_llm_md_dir, topic_md_filename(meta))


def make_db_id(book_slug: str, topic_number: int, category: str, seq: int) -> str:
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


def _mathpix_cache_path_for_topic(
    topic_doc: Dict[str, Any],
    book_name: str,
) -> str:
    source_md_path = _resolve_source_topic_md_path(topic_doc)
    meta = _parse_topic_md_frontmatter(source_md_path) if source_md_path else {}
    cache_path = str(meta.get("source_markdown") or "").strip()
    if cache_path and not os.path.isfile(cache_path):
        cache_path = ""
    if not cache_path:
        cache_path = find_existing_markdown_cache(book_name) or ""
    return cache_path if cache_path and os.path.isfile(cache_path) else ""


def _mathpix_chunk_lines_for_topic(
    topic_doc: Dict[str, Any],
    book_name: str,
    *,
    lookback_lines: int = 0,
) -> str:
    """Slice Mathpix cache for a topic; optional lookback catches concept maps on page boundaries."""
    cache_path = _mathpix_cache_path_for_topic(topic_doc, book_name)
    if not cache_path:
        return ""
    source_md_path = _resolve_source_topic_md_path(topic_doc)
    meta = _parse_topic_md_frontmatter(source_md_path) if source_md_path else {}
    lines_spec = meta.get("lines") or str(topic_doc.get("lines") or "")
    start, end = _parse_line_range(lines_spec)
    if start is None or end is None:
        return ""
    with open(cache_path, "r", encoding="utf-8") as handle:
        all_lines = handle.read().splitlines()
    start_idx = max(0, start - 1 - max(0, lookback_lines))
    end_idx = min(len(all_lines), end)
    return "\n".join(all_lines[start_idx:end_idx])


def _concept_map_opening_markdown_for_topic(
    topic_doc: Dict[str, Any],
    book_name: str,
) -> str:
    """
    Only the chapter-opening slice for concept-map detection (not the full topic).
    Includes lookback before the topic start line and a short forward window so maps
    on the page before/after the first heading are found without scanning mid-topic text.
    """
    cache_path = _mathpix_cache_path_for_topic(topic_doc, book_name)
    if not cache_path:
        return ""
    source_md_path = _resolve_source_topic_md_path(topic_doc)
    meta = _parse_topic_md_frontmatter(source_md_path) if source_md_path else {}
    lines_spec = meta.get("lines") or str(topic_doc.get("lines") or "")
    start, _end = _parse_line_range(lines_spec)
    if start is None:
        return ""
    with open(cache_path, "r", encoding="utf-8") as handle:
        all_lines = handle.read().splitlines()
    start_idx = max(0, start - 1 - CONCEPT_MAP_LOOKBACK_LINES)
    end_idx = min(len(all_lines), start - 1 + CONCEPT_MAP_OPENING_LINES)
    return "\n".join(all_lines[start_idx:end_idx])


def _theory_markdown_with_images_for_topic(
    topic_doc: Dict[str, Any],
    book_name: str,
) -> str:
    """Theory markdown with images from Mathpix cache when per-topic MD stripped them."""
    source_md_path = _resolve_source_topic_md_path(topic_doc)
    theory = (
        extract_theory_notes(read_topic_markdown_body(source_md_path))
        if source_md_path
        else ""
    )
    if theory and IMAGE_MD_RE.search(theory):
        return theory
    chunk_md = _mathpix_chunk_lines_for_topic(topic_doc, book_name, lookback_lines=0)
    return extract_theory_notes(chunk_md) or theory


def _mathpix_image_area(url: str) -> int:
    match = re.search(r"height=(\d+)&width=(\d+)", url, re.IGNORECASE)
    if match:
        return int(match.group(1)) * int(match.group(2))
    return 0


def _parse_mathpix_crop(url: str) -> Tuple[int, int, int, int]:
    """Return width, height, top_left_x, top_left_y (0 when absent)."""
    width = height = top_x = top_y = 0
    match = re.search(r"height=(\d+)&width=(\d+)", url, re.IGNORECASE)
    if match:
        height, width = int(match.group(1)), int(match.group(2))
    match = re.search(r"top_left_y=(\d+)", url, re.IGNORECASE)
    if match:
        top_y = int(match.group(1))
    match = re.search(r"top_left_x=(\d+)", url, re.IGNORECASE)
    if match:
        top_x = int(match.group(1))
    return width, height, top_x, top_y


def _is_foundation_brand_logo_url(url: str) -> bool:
    """Detect the 'Build Strong Foundation' star logo (upper-right chapter opener)."""
    width, height, top_x, top_y = _parse_mathpix_crop(url)
    if not width or not height:
        return False
    return (
        top_x >= FOUNDATION_LOGO_MIN_X
        and top_y <= FOUNDATION_LOGO_MAX_Y
        and 380 <= width <= 550
        and 380 <= height <= 550
    )


def _recrop_concept_map_excluding_logo_band(url: str) -> str:
    """Drop standalone logo crops; trim logo band from full-page concept-map crops."""
    if _is_foundation_brand_logo_url(url):
        return ""
    width, height, _top_x, top_y = _parse_mathpix_crop(url)
    if not width or not height:
        return url
    if top_y <= 500 and width >= 1200 and height >= 1200:
        new_top_y = top_y + FOUNDATION_LOGO_BAND_PX
        new_height = height - FOUNDATION_LOGO_BAND_PX
        if new_height >= 400:
            url = re.sub(
                r"top_left_y=\d+",
                f"top_left_y={new_top_y}",
                url,
                count=1,
                flags=re.IGNORECASE,
            )
            url = re.sub(
                r"height=\d+",
                f"height={new_height}",
                url,
                count=1,
                flags=re.IGNORECASE,
            )
    return url


def _prepare_concept_map_urls(urls: List[str]) -> List[str]:
    seen: Set[str] = set()
    prepared: List[str] = []
    for url in urls:
        processed = _recrop_concept_map_excluding_logo_band(url)
        if processed and processed not in seen:
            seen.add(processed)
            prepared.append(processed)
    return prepared


def _strip_foundation_logo_images_from_markdown(markdown: str) -> str:
    """Remove logo ![](...) references from concept-map markdown text."""
    if not markdown:
        return markdown
    cleaned = markdown
    for url in IMAGE_MD_RE.findall(markdown):
        if _is_foundation_brand_logo_url(url):
            cleaned = cleaned.replace(f"![]({url})", "")
    return compact_markdown(cleaned)


def _remove_concept_map_sections(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            kept.append(sec)
            continue
        if sec.get("section_kind") == "concept_map":
            continue
        if CONCEPT_MAP_HEADING_RE.search(theory_section_heading(sec) or ""):
            continue
        kept.append(sec)
    return kept


def _is_fullpage_concept_map_url(url: str) -> bool:
    """Single full-spread concept map image (chapter 1 style)."""
    width, height, _, _ = _parse_mathpix_crop(url)
    if not width or not height:
        return False
    return (
        width >= 1200
        and height >= 1200
        and width * height >= MIN_CONCEPT_MAP_IMAGE_AREA
    )


def _mathpix_page_key(url: str) -> str:
    match = re.search(r"cropped/(.+?)(?:-\d+)?\.jpg", url, re.IGNORECASE)
    return match.group(1) if match else url


def _concept_map_body_text_only(body: str) -> str:
    text = body or ""
    text = IMAGE_MD_RE.sub("", text)
    text = re.sub(r"\[\^\d+\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _collect_image_urls_between_lines(
    lines: List[str],
    start_idx: int,
    end_idx: int,
) -> List[str]:
    urls: List[str] = []
    for i in range(max(0, start_idx), min(len(lines), end_idx)):
        for url in IMAGE_MD_RE.findall(lines[i]):
            if url not in urls:
                urls.append(url)
    return urls


def _collect_urls_before_chapter_heading(
    lines: List[str],
    chapter_idx: int,
    *,
    max_lookback: int = CONCEPT_MAP_BACKWARD_LINES,
) -> List[str]:
    """Concept maps often appear on the page immediately before the chapter ## heading."""
    urls: List[str] = []
    start = max(0, chapter_idx - max_lookback)
    for i in range(chapter_idx - 1, start - 1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("## "):
            break
        found = IMAGE_MD_RE.findall(lines[i])
        for url in reversed(found):
            if url not in urls:
                urls.insert(0, url)
    return urls


def _select_concept_map_urls(urls: List[str]) -> List[str]:
    """Pick the best concept-map image(s): one full page, or a multi-crop page group."""
    prepared = _prepare_concept_map_urls(urls)
    if not prepared:
        return []

    full_page = [u for u in prepared if _is_fullpage_concept_map_url(u)]
    if full_page:
        return [max(full_page, key=_mathpix_image_area)]

    by_page: Dict[str, List[str]] = {}
    for url in prepared:
        by_page.setdefault(_mathpix_page_key(url), []).append(url)

    best_group: List[str] = []
    best_score = 0
    for group in by_page.values():
        score = sum(_mathpix_image_area(u) for u in group)
        if score > best_score:
            best_score = score
            best_group = group

    if best_group and best_score >= MIN_CONCEPT_MAP_IMAGE_AREA:
        return sorted(best_group, key=_mathpix_image_area, reverse=True)[:CONCEPT_MAP_MULTI_CROP_MAX]

    return [max(prepared, key=_mathpix_image_area)]


def _concept_map_result_from_urls(urls: List[str]) -> Dict[str, Any]:
    selected = _select_concept_map_urls(urls)
    if not selected:
        return {}
    md_block = "\n\n".join(f"![]({u})" for u in selected)
    return {
        "heading": "Concept Map",
        "markdown": md_block,
        "source_urls": selected,
    }


def _concept_map_result_from_section_body(body: str, urls: List[str]) -> Dict[str, Any]:
    body = _strip_foundation_logo_images_from_markdown(compact_markdown(body))
    urls = _select_concept_map_urls(list(dict.fromkeys(urls)))
    if not urls and not body.strip():
        return {}
    full_page = [u for u in urls if _is_fullpage_concept_map_url(u)]
    if full_page and len(_concept_map_body_text_only(body)) < 120:
        return _concept_map_result_from_urls(full_page)
    if urls and len(_concept_map_body_text_only(body)) < 120:
        return _concept_map_result_from_urls(urls)
    if body.strip():
        return {
            "heading": "Concept Map",
            "markdown": body,
            "source_urls": urls,
        }
    return _concept_map_result_from_urls(urls)


def extract_concept_map_from_markdown(markdown: str) -> Dict[str, Any]:
    """
    Find chapter concept-map image(s) from Mathpix markdown.
    Handles explicit (CONCEPT MAP) headings, full-page openers, and maps on the
    page before the chapter heading (common for chapters 2, 3, 5, 8).
    """
    if not isinstance(markdown, str) or not markdown.strip():
        return {}

    for sec in _split_all_h2_sections(markdown):
        title = (sec.get("title") or "").strip()
        if not CONCEPT_MAP_HEADING_RE.search(title):
            continue
        body = str(sec.get("body") or "")
        urls = list(dict.fromkeys(IMAGE_MD_RE.findall(body)))
        result = _concept_map_result_from_section_body(body, urls)
        if result:
            return result

    lines = markdown.replace("\r", "").splitlines()
    chapter_idx: Optional[int] = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("## "):
            continue
        title = stripped[3:].strip()
        if CONCEPT_MAP_HEADING_RE.search(title):
            continue
        if _is_non_theory_title(title):
            continue
        chapter_idx = i
        break

    if chapter_idx is None:
        return {}

    candidate_urls: List[str] = []
    for url in _collect_urls_before_chapter_heading(lines, chapter_idx):
        if url not in candidate_urls:
            candidate_urls.append(url)

    prefix_urls: List[str] = []
    j = chapter_idx + 1
    while j < len(lines):
        stripped = lines[j].strip()
        if stripped.startswith("## "):
            break
        for url in IMAGE_MD_RE.findall(lines[j]):
            if url not in prefix_urls:
                prefix_urls.append(url)
        j += 1

    for url in prefix_urls:
        if url not in candidate_urls:
            candidate_urls.append(url)

    return _concept_map_result_from_urls(candidate_urls)


def _topic_has_concept_map_section(sections: List[Dict[str, Any]]) -> bool:
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        if CONCEPT_MAP_HEADING_RE.search(theory_section_heading(sec) or ""):
            return True
    return False


def _concept_map_image_ids_from_topic(topic_doc: Dict[str, Any]) -> Set[str]:
    cm_md = str((topic_doc.get("concept_map") or {}).get("markdown") or "")
    ids = set(re.findall(r"\[image:(img_\d+)\]", cm_md, re.IGNORECASE))
    for sec in topic_doc.get("theory_sections") or []:
        if not isinstance(sec, dict):
            continue
        if sec.get("section_kind") == "concept_map":
            ids.update(re.findall(
                r"\[image:(img_\d+)\]",
                str(sec.get("markdown") or ""),
                re.IGNORECASE,
            ))
            break
    return ids


def _is_concept_map_theory_section(sec: Dict[str, Any]) -> bool:
    if sec.get("section_kind") == "concept_map":
        return True
    return bool(CONCEPT_MAP_HEADING_RE.search(theory_section_heading(sec) or ""))


def _strip_image_tokens_from_markdown(markdown: str, image_ids: Set[str]) -> str:
    if not markdown or not image_ids:
        return markdown or ""
    cleaned = markdown
    for img_id in image_ids:
        cleaned = re.sub(
            rf"\[image:\s*{re.escape(img_id)}\]\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    return compact_markdown(cleaned)


def _order_theory_sections_for_display(
    sections: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Concept Map first, then all other topic-wise theory sections."""
    concept: List[Dict[str, Any]] = []
    other: List[Dict[str, Any]] = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        if _is_concept_map_theory_section(sec):
            concept.append(sec)
        else:
            other.append(sec)
    return concept + other


def _dedupe_concept_map_in_theory_sections(topic_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Keep concept-map images only on the Concept Map section."""
    sections = list(topic_doc.get("theory_sections") or [])
    if not sections:
        return topic_doc

    cm_ids = _concept_map_image_ids_from_topic(topic_doc)
    cm_idx: Optional[int] = None
    for idx, sec in enumerate(sections):
        if isinstance(sec, dict) and _is_concept_map_theory_section(sec):
            cm_idx = idx
            break

    cleaned_sections: List[Dict[str, Any]] = []
    for idx, sec in enumerate(sections):
        if not isinstance(sec, dict):
            cleaned_sections.append(sec)
            continue
        sec = dict(sec)
        if _is_concept_map_theory_section(sec):
            sec["topics"] = "Concept Map"
            sec["section_kind"] = "concept_map"
            cleaned_sections.append(sec)
            continue
        if cm_ids:
            sec["markdown"] = _strip_image_tokens_from_markdown(
                str(sec.get("markdown") or ""), cm_ids,
            )
        cleaned_sections.append(sec)

    if cm_idx is not None:
        cm_sec = cleaned_sections[cm_idx]
        cm_md = str(cm_sec.get("markdown") or "").strip()
        topic_doc["concept_map"] = {
            "heading": "Concept Map",
            "markdown": cm_md,
        }

    topic_doc["theory_sections"] = cleaned_sections
    topic_doc = _remove_chapter_title_opener_sections(topic_doc)
    topic_doc["theory_sections"] = _order_theory_sections_for_display(
        topic_doc["theory_sections"],
    )
    return topic_doc


CHAPTER_NUMBERED_THEORY_RE = re.compile(r"^\d+\.\s+.+", re.IGNORECASE)


def _is_chapter_title_opener_theory_section(
    sec: Dict[str, Any],
    chapter_name: str,
    topic_number: Optional[int] = None,
) -> bool:
    """Drop duplicate ``N. Chapter title`` opener (logo / empty) in theory_sections."""
    if _is_concept_map_theory_section(sec):
        return False
    title = theory_section_heading(sec).strip()
    if not CHAPTER_NUMBERED_THEORY_RE.match(title):
        return False
    rest = re.sub(r"^\d+\.\s+", "", title, count=1).strip()
    if topic_number is not None:
        num_match = re.match(rf"^{int(topic_number)}\.\s+(.+)$", title, re.IGNORECASE)
        if not num_match:
            return False
        rest = num_match.group(1).strip()
    if title_word_overlap_score(chapter_name, rest) < 0.35:
        return False
    md = str(sec.get("markdown") or "").strip()
    text_only = re.sub(r"\[image:\s*img_\d+\]", "", md, flags=re.IGNORECASE)
    text_only = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text_only)
    text_only = re.sub(r"<[^>]+>", "", text_only)
    text_only = re.sub(r"\s+", " ", text_only).strip()
    return len(text_only) < 120


def _remove_chapter_title_opener_sections(topic_doc: Dict[str, Any]) -> Dict[str, Any]:
    chapter = str(
        topic_doc.get("chapter_name") or topic_doc.get("topic_name") or "",
    ).strip()
    tn = topic_doc.get("topic_number")
    kept: List[Any] = []
    for sec in topic_doc.get("theory_sections") or []:
        if (
            isinstance(sec, dict)
            and chapter
            and _is_chapter_title_opener_theory_section(sec, chapter, tn)
        ):
            continue
        kept.append(sec)
    topic_doc["theory_sections"] = kept
    return topic_doc


def _apply_concept_map_to_topic(
    topic_doc: Dict[str, Any],
    resolver: "ImageResolver",
) -> Dict[str, Any]:
    """Register concept-map images and expose them on the topic + theory_sections."""
    if skip_images():
        return topic_doc

    sections = _remove_concept_map_sections(list(topic_doc.get("theory_sections") or []))
    cm_markdown = ""
    cm_urls: List[str] = []

    raw = extract_concept_map_from_markdown(
        topic_doc.get("_concept_map_source_md") or ""
    )
    if raw:
        cm_markdown = str(raw.get("markdown") or "").strip()
        cm_urls = list(raw.get("source_urls") or [])

    if not cm_markdown and not cm_urls:
        topic_doc["theory_sections"] = sections
        topic_doc.pop("concept_map", None)
        return topic_doc

    for url in cm_urls:
        resolver.register_markdown(f"![]({url})")
    cm_tokens = resolver.replace_urls_with_ids(cm_markdown)
    if not skip_mathml():
        cm_tokens = MathConverter().convert_text(cm_tokens)

    # Concept Map section: images only when the map is a figure (not a text-heavy map).
    cm_section_md = cm_tokens
    if (
        len(_concept_map_body_text_only(cm_markdown)) < 120
        and re.search(r"\[image:\s*img_\d+\]", cm_tokens, re.IGNORECASE)
    ):
        cm_section_md = "\n\n".join(
            m.group(0)
            for m in re.finditer(r"\[image:\s*img_\d+\]", cm_tokens, re.IGNORECASE)
        ).strip()

    topic_doc["concept_map"] = {
        "heading": "Concept Map",
        "markdown": cm_section_md,
    }

    sections.insert(0, {
        "topics": "Concept Map",
        "markdown": cm_section_md,
        "section_kind": "concept_map",
    })
    topic_doc["theory_sections"] = sections

    n_cm = len(re.findall(r"\[image:(img_\d+)\]", cm_tokens))
    print(f"    Concept map: {n_cm} image(s)")
    return topic_doc


def find_existing_markdown_cache(base_name: str) -> Optional[str]:
    candidates = []
    for d in MATHPIX_CACHE_DIR_ALIASES:
        if not d:
            continue
        candidates.append(os.path.join(d, f"{base_name}_mathpix.md"))
        candidates.append(os.path.join(d, f"{base_name}.md"))
        candidates.append(os.path.join(d, f"{base_name}.markdown"))
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def ensure_mathpix_markdown(pdf_path: str, cache_path: str) -> bool:
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    if os.path.exists(cache_path):
        print(f"Loading cached Markdown: {cache_path}")
        return True

    if not os.path.exists(pdf_path):
        print(f"PDF not found: {pdf_path}")
        return False

    if not MATHPIX_APP_ID or not MATHPIX_APP_KEY:
        print("Missing Mathpix credentials. Set MATHPIX_APP_ID and MATHPIX_APP_KEY env vars.")
        return False

    print("Uploading PDF to Mathpix...")
    headers = {"app_id": MATHPIX_APP_ID, "app_key": MATHPIX_APP_KEY}
    options = {
        "conversion_formats": {"md": True},
        "math_inline_delimiters": ["$", "$"],
        "rm_spaces": True,
    }

    with open(pdf_path, "rb") as handle:
        res = requests.post(
            MATHPIX_API_BASE,
            headers=headers,
            data={"options_json": json.dumps(options)},
            files={"file": handle},
            timeout=120,
        )

    if res.status_code != 200:
        print(f"Mathpix upload failed: HTTP {res.status_code} {res.text[:300]}")
        return False

    pdf_id = (res.json() or {}).get("pdf_id")
    if not pdf_id:
        print("Mathpix upload response missing pdf_id.")
        return False

    print(f"Processing ID: {pdf_id} ...")
    while True:
        poll = requests.get(f"{MATHPIX_API_BASE}/{pdf_id}", headers=headers, timeout=60)
        payload = poll.json() if poll.ok else {}
        status = payload.get("status")
        if status == "completed":
            break
        if status == "error":
            err = (payload.get("error_info") or {}).get("id")
            if err == "pdf_page_limit_exceeded":
                print(
                    "Mathpix quota exceeded for this app_id/group_id. "
                    "Provide an existing markdown cache or use different Mathpix credentials."
                )
            print(f"Mathpix processing error: {payload}")
            return False
        time.sleep(MATHPIX_POLL_SECONDS)

    md_url = f"{MATHPIX_API_BASE}/{pdf_id}.md"
    md_res = requests.get(md_url, headers=headers, timeout=120)
    if not md_res.ok or not md_res.text.strip():
        print(f"Mathpix markdown download failed: HTTP {md_res.status_code}")
        return False

    with open(cache_path, "w", encoding="utf-8") as handle:
        handle.write(md_res.text)
    print(f"Saved Markdown cache: {cache_path}")
    return True


def compact_markdown(text: str) -> str:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


PIPE_TABLE_SEPARATOR_RE = re.compile(
    r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$"
)
MATHML_BLOCK_RE = re.compile(r"<math[\s\S]*?</math>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")


def plain_section_title(title: str, *, max_len: int = 500) -> str:
    """Short plain heading for ``theory_sections[].topics`` / DB ``topic_name``."""
    text = str(title or "").strip()
    text = MATHML_BLOCK_RE.sub(" ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."
    return text


def _normalize_heading_text(title: str) -> str:
    text = re.sub(r"^#+\s*", "", str(title or "").strip())
    return re.sub(r"\s+", " ", text).strip().lower()


def strip_duplicate_section_heading(markdown: str, section_title: str) -> str:
    """Drop a leading markdown heading that repeats the section title (shown in the UI)."""
    raw = str(markdown or "").replace("\r", "")
    title = str(section_title or "").strip()
    if not raw.strip() or not title:
        return raw.strip()
    norm_title = _normalize_heading_text(title)
    lines = raw.split("\n")
    start = 0
    while start < len(lines):
        line = lines[start].strip()
        if not line:
            start += 1
            continue
        hm = re.match(r"^(#{1,6})\s+(.*)$", line)
        if hm:
            htext = _normalize_heading_text(hm.group(2))
            if (
                htext == norm_title
                or htext.startswith(norm_title)
                or norm_title.startswith(htext)
            ):
                start += 1
                while start < len(lines) and not lines[start].strip():
                    start += 1
                continue
        if _normalize_heading_text(line) == norm_title:
            start += 1
            while start < len(lines) and not lines[start].strip():
                start += 1
            continue
        break
    return compact_markdown("\n".join(lines[start:]))


def _split_pipe_table_cells(line: str) -> List[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_pipe_table_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped or "|" not in stripped:
        return False
    if PIPE_TABLE_SEPARATOR_RE.match(stripped):
        return True
    return len(_split_pipe_table_cells(stripped)) >= 2


def _is_pipe_table_separator(line: str) -> bool:
    return bool(PIPE_TABLE_SEPARATOR_RE.match(line.strip()))


def _table_cell_html(cell: str, *, tag: str = "td") -> str:
    """Render a table cell; preserve figures/tokens already resolved for output."""
    cell = (cell or "").strip()
    if not cell:
        return f"<{tag}></{tag}>"
    lowered = cell.lower()
    if (
        "[image:" in cell
        or "<img" in lowered
        or "<math" in lowered
        or "$" in cell
    ):
        return f'<{tag} class="rich">{cell}</{tag}>'
    return f"<{tag}>{html.escape(cell)}</{tag}>"


def _render_pipe_table_html(
    block_lines: List[str],
    *,
    resolver: Optional["ImageResolver"] = None,
) -> str:
    rows: List[List[str]] = []
    for line in block_lines:
        if _is_pipe_table_separator(line):
            continue
        cells = _split_pipe_table_cells(line)
        if len(cells) >= 2:
            rows.append(cells)
    if not rows:
        return "\n".join(block_lines)

    header = rows[0]
    body = rows[1:]
    parts = ['<table class="theory-table">', "<thead><tr>"]
    for cell in header:
        processed = (
            resolver.replace_urls_with_ids(cell) if resolver else cell
        )
        parts.append(_table_cell_html(processed, tag="th"))
    parts.append("</tr></thead>")
    if body:
        parts.append("<tbody>")
        for row in body:
            padded = row + [""] * max(0, len(header) - len(row))
            parts.append("<tr>")
            for i in range(len(header)):
                processed = (
                    resolver.replace_urls_with_ids(padded[i]) if resolver else padded[i]
                )
                parts.append(_table_cell_html(processed))
            parts.append("</tr>")
        parts.append("</tbody>")
    parts.append("</table>")
    return "".join(parts)


def convert_markdown_tables_to_html(
    text: str,
    *,
    resolver: Optional["ImageResolver"] = None,
) -> str:
    """Convert GFM pipe tables in markdown to HTML ``<table>`` blocks (with figure cells)."""
    if not isinstance(text, str) or "|" not in text:
        return text or ""
    lines = text.splitlines()
    out: List[str] = []
    i = 0
    while i < len(lines):
        if _is_pipe_table_row(lines[i]) and not _is_pipe_table_separator(lines[i]):
            block: List[str] = []
            while i < len(lines) and _is_pipe_table_row(lines[i]):
                block.append(lines[i])
                i += 1
            out.append(_render_pipe_table_html(block, resolver=resolver))
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def process_theory_markdown_for_images(
    markdown: str,
    resolver: "ImageResolver",
) -> str:
    """Replace Mathpix figure URLs with [image:img_NNN] and render pipe tables as HTML."""
    if not markdown or not markdown.strip():
        return markdown or ""
    md = resolver.replace_urls_with_ids(markdown)
    md = convert_markdown_tables_to_html(md, resolver=resolver)
    if not skip_mathml():
        md = MathConverter().convert_text(md)
    return md


def _truncate_text(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def preview_lines(text: str, limit: int = 4) -> List[str]:
    out: List[str] = []
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            out.append(clean)
        if len(out) >= limit:
            break
    return out


def slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug or "section"


def toc_entry_type(label: str) -> str:
    label_lower = label.lower()
    if re.match(r"^\d+\.\d+", label):
        return "section"
    if re.match(r"^\d+\.", label):
        return "chapter"
    if "revision exercise" in label_lower:
        return "revision_exercise"
    if "examination-style exercise" in label_lower:
        return "exam_exercise"
    if label_lower in {"answers", "index", "introduction"}:
        return "backmatter" if label_lower in {"answers", "index"} else "frontmatter"
    return "entry"


def parse_toc(lines: List[str]) -> List[Dict[str, str]]:
    toc: List[Dict[str, str]] = []
    in_contents = False
    for raw_line in lines:
        line = raw_line.strip()
        if not in_contents:
            if line in ("## Contents", "## CONTENTS"):
                in_contents = True
            continue

        if _is_contents_end_heading(line):
            break
        if in_contents and line.startswith("## ") and line.upper() not in ("## CONTENTS", "## Contents"):
            heading_topic = TOC_HEADING_TOPIC_RE.match(line)
            if heading_topic:
                toc.append({
                    "entry_type": "chapter",
                    "label": f"{heading_topic.group(1)}. {heading_topic.group(2).strip()}",
                    "page": heading_topic.group(3),
                })
            continue
        if not line or line.startswith("| :---"):
            continue

        match = TOC_DOTTED_RE.match(line) or TOC_TABLE_RE.match(line)
        if not match:
            topic_match = TOC_TOPIC_RE.match(line)
            if topic_match:
                toc.append({
                    "entry_type": "chapter",
                    "label": f"{topic_match.group(1)}. {topic_match.group(2).strip()}",
                    "page": topic_match.group(3),
                })
            continue

        label = match.group(1).strip()
        page = match.group(2).strip()
        toc.append({
            "entry_type": toc_entry_type(label),
            "label": label,
            "page": page,
        })
    return toc


def normalize_title_words(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [word for word in words if word not in STOP_TITLE_WORDS and len(word) > 1]


def title_word_overlap_score(topic_name: str, heading: str) -> float:
    topic_words = normalize_title_words(topic_name)
    heading_words = normalize_title_words(heading)
    if not topic_words or not heading_words:
        return 0.0
    matches = 0
    for topic_word in topic_words:
        for heading_word in heading_words:
            if topic_word == heading_word:
                matches += 1
                break
            prefix = min(len(topic_word), len(heading_word), 4)
            if prefix >= 4 and (
                topic_word.startswith(heading_word[:prefix])
                or heading_word.startswith(topic_word[:prefix])
            ):
                matches += 1
                break
    return matches / len(topic_words)


def normalize_toc_entry_line(line: str) -> str:
    """Normalize Mathpix TOC quirks before regex matching."""
    stripped = line.strip()
    stripped = re.sub(r"\$(\d+-\d+)\$", r" ..... \1", stripped)
    stripped = re.sub(r"([A-Za-z])(\d+-\d+)\s*$", r"\1 ..... \2", stripped)
    return stripped


def _is_contents_end_heading(line: str) -> bool:
    """True when a ## heading marks the start of chapter body (end of TOC block)."""
    if not line.startswith("## ") or line.upper() in ("## CONTENTS", "## Contents"):
        return False
    if TOC_HEADING_TOPIC_RE.match(line):
        return False
    if TOC_MATHPIX_PAGE_SUFFIX_RE.search(line):
        return False
    return True


def find_contents_end_line(lines: List[str]) -> int:
    """First body chapter heading after the TOC block (not a mid-book ## N. chapter)."""
    in_contents = False
    for idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not in_contents:
            if line in ("## Contents", "## CONTENTS"):
                in_contents = True
            continue
        if not line.startswith("## ") or line.upper() in ("## CONTENTS", "## Contents"):
            continue
        if TOC_HEADING_TOPIC_RE.match(line):
            continue
        if TOC_MATHPIX_PAGE_SUFFIX_RE.search(line):
            continue
        return idx
    return 0


def near_chapter_boundary(lines: List[str], idx: int, window: int = 12) -> bool:
    start = max(0, idx - window)
    end = min(len(lines), idx + window + 1)
    for pos in range(start, end):
        stripped = lines[pos].strip()
        if CONCEPT_MAP_HEADING_RE.search(stripped):
            return True
        if re.search(r"\|\s*\(\s*C\s+O\s+N", stripped):
            return True
        if CHAPTER_IMAGE_RE.search(stripped) and pos <= idx:
            return True
    return False


def parse_contents_topics(lines: List[str]) -> List[TopicMeta]:
    topics: List[TopicMeta] = []
    in_contents = False
    pending_num: Optional[int] = None
    pending_name_parts: List[str] = []

    def flush_pending(page_range: str) -> None:
        nonlocal pending_num, pending_name_parts
        if pending_num is not None and pending_name_parts and page_range:
            topics.append(TopicMeta(
                topic_number=pending_num,
                topic_name=" ".join(pending_name_parts).strip(),
                page_range=page_range,
            ))
        pending_num = None
        pending_name_parts = []

    for raw_line in lines:
        line = raw_line.strip()
        if not in_contents:
            if line in ("## Contents", "## CONTENTS"):
                in_contents = True
            continue

        if _is_contents_end_heading(line):
            break

        if in_contents and line.startswith("## ") and line.upper() not in ("## CONTENTS", "## Contents"):
            heading_topic = TOC_HEADING_TOPIC_RE.match(line)
            if heading_topic:
                flush_pending("")
                topics.append(TopicMeta(
                    topic_number=int(heading_topic.group(1)),
                    topic_name=heading_topic.group(2).strip(),
                    page_range=heading_topic.group(3),
                ))
            continue

        if not line:
            continue

        line = normalize_toc_entry_line(line)

        dotted_match = TOC_DOTTED_RE.match(line) or TOC_TABLE_RE.match(line)
        if dotted_match:
            label = dotted_match.group(1).strip()
            page_range = dotted_match.group(2).strip()
            topic_match = TOC_TOPIC_RE.match(f"{label} ..... {page_range}")
            if topic_match:
                flush_pending("")
                topics.append(TopicMeta(
                    topic_number=int(topic_match.group(1)),
                    topic_name=topic_match.group(2).strip(),
                    page_range=topic_match.group(3),
                ))
            continue

        topic_match = TOC_TOPIC_RE.match(line)
        if topic_match:
            flush_pending("")
            topics.append(TopicMeta(
                topic_number=int(topic_match.group(1)),
                topic_name=topic_match.group(2).strip(),
                page_range=topic_match.group(3),
            ))
            continue

        page_match = TOC_PAGE_RANGE_RE.match(line)
        if page_match and pending_num is not None:
            flush_pending(page_match.group(1))
            continue

        num_match = TOC_TOPIC_NUM_ONLY_RE.match(line)
        if num_match and not re.search(r"\d+-\d+\s*$", line):
            flush_pending("")
            pending_num = int(num_match.group(1))
            pending_name_parts = [num_match.group(2).strip()]
            continue

        if pending_num is not None:
            pending_name_parts.append(line)

    flush_pending("")
    return topics


def _title_matches_topic_aliases(topic_number: int, title: str) -> bool:
    title_lower = title.lower()
    for alias in TOPIC_CHAPTER_ALIASES.get(topic_number, []):
        if alias in title_lower:
            return True
    return False


def score_topic_start_candidate(line: str, meta: TopicMeta) -> float:
    stripped = line.strip()
    if not stripped.startswith("## "):
        return 0.0

    title = stripped[3:].strip()
    topic_number = meta.topic_number
    topic_name = meta.topic_name

    if re.search(r"check your knowledge|did you know", title, re.IGNORECASE):
        return 0.0
    if "<br>" in title.lower():
        return 0.0
    if SUBSECTION_NOT_CHAPTER_RE.search(title):
        return 0.0

    if FALSE_CHAPTER_HEADING_RE.match(title):
        return 0.0

    if _title_matches_topic_aliases(topic_number, title):
        return 98.0

    numbered_match = re.match(rf"^{topic_number}\.\s+(.+)$", title, re.IGNORECASE)
    if numbered_match:
        rest = numbered_match.group(1).strip()
        overlap = title_word_overlap_score(topic_name, rest)
        if overlap >= 0.5:
            return 100.0
        if overlap >= 0.25:
            return 90.0
        return 0.0

    if re.match(r"^\d+\.", title):
        return 0.0

    overlap = title_word_overlap_score(topic_name, title)
    topic_words = normalize_title_words(topic_name)
    heading_words = normalize_title_words(title)
    if len(topic_words) >= 2 and overlap < 1.0:
        first_topic_word = topic_words[0]
        if not any(
            first_topic_word == heading_word
            or first_topic_word.startswith(heading_word[:4])
            or heading_word.startswith(first_topic_word[:4])
            for heading_word in heading_words
        ):
            return 0.0
    elif len(topic_words) == 1:
        topic_word = topic_words[0]
        if not any(
            topic_word == heading_word
            or topic_word.startswith(heading_word[:4])
            or heading_word.startswith(topic_word[:4])
            for heading_word in heading_words
        ):
            return 0.0

    if overlap >= 0.6:
        score = 95.0
    elif overlap >= 0.4:
        score = 88.0
    elif overlap >= 0.25:
        score = 82.0
    else:
        topic_words = normalize_title_words(topic_name)
        if (
            topic_words
            and topic_words[0].upper() in title.upper()
            and len(topic_words[0]) >= 5
            and topic_words[0] not in GENERIC_TOPIC_FIRST_WORDS
        ):
            score = 80.0
        elif CONCEPT_MAP_HEADING_RE.search(title):
            score = 72.0
        else:
            return 0.0

    if (
        len(topic_words) >= 2
        and overlap < 0.6
        and topic_words[0] in GENERIC_TOPIC_FIRST_WORDS
    ):
        return 0.0

    if title == title.upper() and 1 <= len(normalize_title_words(title)) <= 4:
        score = max(score, 92.0)
    elif title != title.upper() and len(re.findall(r"[A-Za-z]+", title)) > 4:
        score = min(score, 82.0)

    return score


def estimate_topic_min_line(
    lines: List[str],
    meta: TopicMeta,
    topic_metas: List[TopicMeta],
    contents_end: int,
) -> int:
    page_ends: List[int] = []
    for topic in topic_metas:
        match = re.match(r"^(\d+)-(\d+)$", topic.page_range or "")
        if match:
            page_ends.append(int(match.group(2)))
    if not page_ends:
        return contents_end

    body_lines = max(len(lines) - contents_end, 1)
    total_pages = max(page_ends)
    match = re.match(r"^(\d+)", meta.page_range or "")
    topic_page = int(match.group(1)) if match else 0
    ratio = max(topic_page - 1, 0) / max(total_pages, 1)
    slack = max(int(body_lines * 0.03), 80)
    return max(contents_end, contents_end + int(body_lines * ratio) - slack)


def find_topic_start_lines(lines: List[str], topic_metas: List[TopicMeta]) -> Dict[int, int]:
    if not topic_metas:
        return {}

    contents_end = find_contents_end_line(lines)
    sorted_topics = sorted(topic_metas, key=lambda topic: topic.topic_number)
    starts: Dict[int, int] = {}
    search_from = contents_end

    for meta in sorted_topics:
        min_line = estimate_topic_min_line(lines, meta, topic_metas, contents_end)
        scan_from = search_from
        best_idx: Optional[int] = None
        best_score = 0.0
        for idx in range(scan_from, len(lines)):
            score = score_topic_start_candidate(lines[idx], meta)
            if score <= 0:
                continue
            if not near_chapter_boundary(lines, idx) and score < 95:
                continue
            if score > best_score or (
                score == best_score and (best_idx is None or idx < best_idx)
            ):
                best_score = score
                best_idx = idx

        if best_idx is not None and best_score >= 72.0:
            starts[meta.topic_number] = best_idx
            search_from = best_idx + 1
            continue

        print(f"  Warning: topic {meta.topic_number} start not matched by heading heuristics")

    missing = [meta for meta in sorted_topics if meta.topic_number not in starts]
    if missing:
        concept_lines = [
            idx for idx in range(contents_end, len(lines))
            if lines[idx].strip().startswith("## ")
            and CONCEPT_MAP_HEADING_RE.search(lines[idx].strip()[3:])
        ]
        concept_cursor = 0
        for meta in missing:
            prev_line = max(
                (starts[num] for num in starts if num < meta.topic_number),
                default=contents_end,
            )
            next_line = min(
                (starts[num] for num in starts if num > meta.topic_number),
                default=len(lines),
            )
            min_line = estimate_topic_min_line(lines, meta, topic_metas, contents_end)
            chosen: Optional[int] = None
            while concept_cursor < len(concept_lines):
                candidate = concept_lines[concept_cursor]
                concept_cursor += 1
                if max(prev_line, min_line) < candidate < next_line:
                    chosen = candidate
                    break
            if chosen is None:
                for idx in range(max(prev_line + 1, min_line), next_line):
                    if near_chapter_boundary(lines, idx):
                        chosen = idx
                        break
            if chosen is None and max(prev_line + 1, min_line) < next_line:
                chosen = max(prev_line + 1, min_line)
            if chosen is not None:
                starts[meta.topic_number] = chosen
                search_from = max(search_from, chosen + 1)

    return starts


def split_topics(markdown: str) -> List[TopicChunk]:
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


def split_topic_markdown_into_theory_and_examples(markdown: str) -> Tuple[str, str]:
    """Split topic markdown into theory-only and examples/non-theory bodies."""
    theory_parts: List[str] = []
    examples_parts: List[str] = []
    for sec in _split_all_h2_sections(markdown):
        title = sec.get("title", "").strip()
        body = sec.get("body", "").strip()
        if not title:
            if body:
                theory_parts.append(body)
            continue
        block = f"## {title}\n\n{body}" if body else f"## {title}"
        if _is_non_theory_title(title):
            examples_parts.append(block)
        else:
            theory_parts.append(block)
    return (
        compact_markdown("\n\n".join(theory_parts)),
        compact_markdown("\n\n".join(examples_parts)),
    )


def _topic_md_has_images(body: str) -> bool:
    return bool(
        MARKDOWN_IMAGE_RE.search(body)
        or HTML_IMG_RE.search(body)
        or MATHPIX_URL_RE.search(body)
    )


def _write_topic_md_file(
    path: str,
    chunk: TopicChunk,
    body: str,
    source_markdown: str,
    md_kind: str,
    force: bool,
) -> None:
    body = strip_images_from_markdown(body)
    front_matter = (
        f"---\n"
        f"topic_number: {chunk.meta.topic_number}\n"
        f"topic_name: {chunk.meta.topic_name}\n"
        f"page_range: {chunk.meta.page_range}\n"
        f"source_markdown: {source_markdown}\n"
        f"md_kind: {md_kind}\n"
        f"lines: {chunk.start_line}-{chunk.end_line}\n"
        f"---\n\n"
    )
    action = "Wrote"
    if os.path.exists(path) and not force:
        cached_body = read_topic_markdown_body(path)
        if not _topic_md_has_images(cached_body):
            print(f"  Using cached topic {md_kind} MD: {path}")
            return
        body = strip_images_from_markdown(cached_body)
        action = "Stripped images in cached"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(front_matter + body)
    img_left = len(re.findall(r"cdn\.mathpix\.com|!\[[^\]]*\]\(", body))
    note = "images stripped" if img_left == 0 else f"WARNING: {img_left} image ref(s) remain"
    print(f"  {action} topic {md_kind} MD: {path} ({len(body):,} chars, {note})")


def write_topic_markdown_files(
    raw_markdown: str,
    book_paths: BookPaths,
    source_markdown: str,
    topic_filter: Optional[List[int]] = None,
    force_topics: bool = False,
    split_theory_examples: bool = False,
) -> List[Tuple[TopicChunk, str, Optional[str]]]:
    chunks = split_topics(raw_markdown)
    if topic_filter:
        chunks = [c for c in chunks if c.meta.topic_number in topic_filter]

    os.makedirs(book_paths.topics_md_dir, exist_ok=True)
    manifest: List[Dict[str, Any]] = []
    entries: List[Tuple[TopicChunk, str, Optional[str]]] = []

    for chunk in chunks:
        body = strip_images_from_markdown(chunk.markdown)
        if split_theory_examples:
            theory_body, examples_body = split_topic_markdown_into_theory_and_examples(body)
            theory_path = os.path.join(
                book_paths.topics_md_dir, topic_theory_md_filename(chunk.meta)
            )
            examples_path = os.path.join(
                book_paths.topics_md_dir, topic_examples_md_filename(chunk.meta)
            )
            _write_topic_md_file(
                theory_path, chunk, theory_body, source_markdown, "theory", force_topics
            )
            _write_topic_md_file(
                examples_path, chunk, examples_body, source_markdown, "examples", force_topics
            )
            manifest.append({
                "topic_number": chunk.meta.topic_number,
                "topic_name": chunk.meta.topic_name,
                "page_range": chunk.meta.page_range,
                "theory_md_path": theory_path.replace("\\", "/"),
                "examples_md_path": examples_path.replace("\\", "/"),
                "json_path": topic_json_path(book_paths, chunk.meta.topic_number).replace("\\", "/"),
                "lines": f"{chunk.start_line}-{chunk.end_line}",
            })
            entries.append((chunk, theory_path, examples_path))
        else:
            fname = topic_md_filename(chunk.meta)
            md_path = os.path.join(book_paths.topics_md_dir, fname)
            _write_topic_md_file(
                md_path, chunk, body, source_markdown, "combined", force_topics
            )
            manifest.append({
                "topic_number": chunk.meta.topic_number,
                "topic_name": chunk.meta.topic_name,
                "page_range": chunk.meta.page_range,
                "md_path": md_path.replace("\\", "/"),
                "json_path": topic_json_path(book_paths, chunk.meta.topic_number).replace("\\", "/"),
                "lines": f"{chunk.start_line}-{chunk.end_line}",
            })
            entries.append((chunk, md_path, None))

    with open(book_paths.manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
    print(f"  Wrote manifest: {book_paths.manifest_path}")
    return entries


def _split_all_h2_sections(markdown: str) -> List[Dict[str, str]]:
    return _split_sections_by_heading(markdown, H2_RE)


def _normalize_illustration_id(raw: str) -> str:
    cleaned = re.sub(r"\$|\\[a-zA-Z]+|\{|\}|\\", "", raw)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", cleaned.strip()).strip("_")
    return cleaned or "unknown"


def _classify_exercise_source(title: str) -> str:
    t = title.lower()
    if "text-book" in t or "textbook" in t:
        return "textbook_exercise"
    if "foundation builder" in t:
        return "foundation_builder"
    if "exemplar" in t:
        return "exemplar"
    if "exercise" in t:
        return "exercise"
    return "exercise"


def _classify_exercise_kind(title: str, context: str = "") -> str:
    t = f"{title} {context}".lower()
    if "master board" in t:
        return "master_boards"
    if "master ncert" in t:
        return "master_ncert"
    if "foundation builder +" in t or "foundation builder+" in t:
        return "foundation_builder_plus"
    if "foundation builder" in t:
        return "foundation_builder"
    if "text-book" in t or "textbook" in t or "text - book" in t:
        return "textbook"
    if "exemplar" in t:
        return "exemplar"
    if "multiple choice" in t or "mcq" in t:
        return "mcq"
    if "assertion" in t:
        return "assertion_reason"
    return "other"


def _guess_question_type(prompt: str, subsection: str = "", *, section_type: str = "") -> str:
    """Delegate to question_type_classifier (stakeholder labels)."""
    from question_type_classifier import classify_question

    return classify_question(
        prompt,
        section_type=section_type,
        subsection=subsection,
    )


def _is_question_bank_title(title: str) -> bool:
    """H2 headings that are exercise / exam blocks, not pedagogy theory."""
    if not title:
        return False
    stripped = title.strip()
    if QUESTION_TYPE_SECTION_RE.search(stripped):
        return True
    if MCQ_SECTION_RE.match(f"## {stripped}"):
        return True
    if DIRECTIONS_HEADING_RE.match(stripped):
        return True
    if stripped.lower() in ("or", "solutions", "answer key", "answers"):
        return True
    return False


def _is_non_theory_title(title: str) -> bool:
    if not title:
        return False
    if _is_question_bank_title(title):
        return True
    if NON_THEORY_SECTION_RE.match(title):
        return True
    if ILLUSTRATION_RE.match(f"## {title}"):
        return True
    if CASE_STUDY_RE.match(f"## {title}"):
        return True
    if EXERCISE_HEADING_RE.match(f"## {title}"):
        return True
    if EXERCISE_TOP_RE.match(f"## {title}"):
        return True
    if SOLUTION_RE.match(f"## {title}") or SOLUTIONS_HEADING_RE.match(f"## {title}"):
        return True
    if CHECK_KNOWLEDGE_RE.search(title):
        return True
    return False


def _strip_inline_cyk_from_body(body: str) -> str:
    lines = body.splitlines()
    out: List[str] = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if CHECK_KNOWLEDGE_RE.search(stripped):
            skip = True
            continue
        if skip and SOLUTION_RE.match(stripped):
            skip = False
            continue
        if skip:
            continue
        out.append(line)
    return compact_markdown("\n".join(out))


def extract_theory_sections(markdown: str) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    order = 0
    for sec in _split_all_h2_sections(markdown):
        title = sec.get("title", "").strip()
        if _is_non_theory_title(title):
            continue
        body = _strip_inline_cyk_from_body(sec.get("body", "").strip())
        if not title and not body:
            continue
        order += 1
        sections.append({
            "order": order,
            "topics": plain_section_title(title) or f"Section {order}",
            "markdown": f"## {title}\n\n{body}" if title and body else (body or f"## {title}"),
        })
    return sections


def parse_case_study_prompts(body: str) -> List[Dict[str, str]]:
    prompts: List[Dict[str, str]] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("!["):
            continue
        match = CASE_PROMPT_RE.match(stripped)
        if match:
            label = match.group(1).strip()
            text = match.group(2).strip()
            prompts.append({"label": label, "text": text})
        elif prompts and not stripped.startswith("##"):
            prompts[-1]["text"] = compact_markdown(
                f"{prompts[-1]['text']}\n{stripped}".strip()
            )
    return prompts


def _is_top_level_exercise_heading(stripped: str) -> bool:
    return bool(
        EXERCISE_HEADING_RE.match(stripped)
        or EXERCISE_HEADING_EXCERCISE_RE.match(stripped)
        or EXERCISE_TOP_RE.match(stripped)
    )


def _first_exercise_line_index(lines: List[str]) -> Optional[int]:
    candidates: List[int] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if (
            _is_top_level_exercise_heading(stripped)
            or EXERCISE_PLAIN_RE.match(stripped)
            or EXERCISE_BANK_START_RE.match(stripped)
            or MCQ_SECTION_RE.match(stripped)
            or (
                H2_RE.match(stripped)
                and QUESTION_TYPE_SECTION_RE.search(stripped.lstrip("#").strip())
            )
            or MISCELLANEOUS_SOLVED_RE.match(stripped)
        ):
            candidates.append(idx)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not DIRECTIONS_QS_RE.match(stripped):
            continue
        prev = lines[idx - 1].strip() if idx > 0 else ""
        if EXERCISE_BANK_START_RE.match(prev) or MISCELLANEOUS_SOLVED_RE.match(prev):
            candidates.append(idx - 1)
        elif H2_RE.match(prev) and QUESTION_TYPE_SECTION_RE.search(prev):
            candidates.append(idx - 1)
        else:
            candidates.append(idx)
    if candidates:
        return min(candidates)
    for idx, line in enumerate(lines):
        if SOLUTIONS_HEADING_RE.match(line.strip()):
            return idx
    return None


def _looks_like_answer_line(q_match: re.Match) -> bool:
    rest = q_match.group(2).strip()
    if not rest:
        return False
    if ANSWER_LIKE_RE.match(rest):
        return True
    if len(rest) < 120 and re.search(r"\([a-d]\)", rest, re.IGNORECASE):
        return True
    return False


def _subsection_slug(title: str) -> str:
    return slugify(title) or "general"


def extract_exercise_sections(markdown: str) -> List[Dict[str, Any]]:
    lines = markdown.splitlines()
    start_idx = _first_exercise_line_index(lines)
    if start_idx is None:
        return []

    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    current_subsection = ""
    subsection_lines: List[str] = []
    preamble_lines: List[str] = []
    subsection_visits: Dict[str, int] = {}

    def reset_subsection_visits() -> None:
        nonlocal subsection_visits
        subsection_visits = {}

    def flush_subsection() -> None:
        nonlocal subsection_lines, current_subsection
        if current is None or not subsection_lines:
            subsection_lines = []
            return
        current.setdefault("subsections", []).append({
            "title": current_subsection,
            "body": compact_markdown("\n".join(subsection_lines)),
        })
        subsection_lines = []

    def finalize_exercise() -> None:
        nonlocal current, preamble_lines
        if current is None:
            return
        flush_subsection()
        context = compact_markdown("\n".join(preamble_lines))
        current["kind"] = _classify_exercise_kind(current.get("title", ""), context)
        current["instruction_markdown"] = context
        questions: List[Dict[str, Any]] = []
        for sub in current.get("subsections", []):
            parsed = parse_questions(sub["body"])
            sub_title = sub.get("title", "")
            sub_slug = _subsection_slug(sub_title)
            for q in parsed.get("questions", []):
                questions.append({
                    "number": q["question_number"],
                    "prompt_markdown": q["prompt"],
                    "solution_markdown": q.get("solution", ""),
                    "question_type": _guess_question_type(
                        q["prompt"], sub_title, section_type="exercise"
                    ),
                    "subsection": sub_slug,
                    "subsection_title": sub_title,
                })
        if not questions and current.get("preamble_body"):
            parsed = parse_questions(current["preamble_body"])
            for q in parsed.get("questions", []):
                questions.append({
                    "number": q["question_number"],
                    "prompt_markdown": q["prompt"],
                    "solution_markdown": q.get("solution", ""),
                    "question_type": _guess_question_type(
                        q["prompt"],
                        current.get("title", ""),
                        section_type="exercise",
                    ),
                    "subsection": "general",
                    "subsection_title": "",
                })
        current["questions"] = questions
        for key in ("subsections", "preamble_body", "lines"):
            current.pop(key, None)
        sections.append(current)
        current = None
        preamble_lines = []

    for line in lines[start_idx:]:
        stripped = line.strip()
        if SOLUTIONS_HEADING_RE.match(stripped):
            finalize_exercise()
            break
        if (
            _is_top_level_exercise_heading(stripped)
            or EXERCISE_PLAIN_RE.match(stripped)
            or EXERCISE_BANK_START_RE.match(stripped)
            or MISCELLANEOUS_SOLVED_RE.match(stripped)
        ):
            finalize_exercise()
            title = stripped.lstrip("#").strip()
            current = {"title": title, "subsections": [], "preamble_body": ""}
            current_subsection = ""
            subsection_lines = []
            preamble_lines = []
            reset_subsection_visits()
            continue
        if current is None and DIRECTIONS_QS_RE.match(stripped):
            current = {
                "title": "Exercise bank",
                "subsections": [],
                "preamble_body": "",
            }
            current_subsection = ""
            subsection_lines = [line]
            continue
        if current is None:
            continue
        if DIRECTIONS_QS_RE.match(stripped):
            flush_subsection()
            current_subsection = "Directions"
            subsection_lines = [line]
            continue
        if H2_RE.match(stripped) and not QUESTION_RE.match(stripped):
            flush_subsection()
            heading = stripped.lstrip("#").strip()
            if (
                QUESTION_TYPE_SECTION_RE.search(heading)
                or MCQ_SECTION_RE.match(stripped)
                or EXERCISE_BANK_START_RE.match(stripped)
                or MISCELLANEOUS_SOLVED_RE.match(stripped)
                or NON_THEORY_SECTION_RE.match(heading)
            ):
                slug = _subsection_slug(heading)
                subsection_visits[slug] = subsection_visits.get(slug, 0) + 1
                if subsection_visits[slug] > 1:
                    current_subsection = ""
                    subsection_lines = []
                    continue
                current_subsection = heading
                subsection_lines = []
            else:
                preamble_lines.append(line)
            continue
        if current_subsection:
            subsection_lines.append(line)
        else:
            preamble_lines.append(line)

    finalize_exercise()
    return sections


def extract_solution_answer_map(markdown: str) -> Dict[Tuple[str, str], str]:
    lines = markdown.splitlines()
    start_idx = _first_exercise_line_index(lines)
    if start_idx is None:
        return {}

    answers: Dict[Tuple[str, str], str] = {}
    in_solutions = False
    current_subsection = ""
    current_num = ""
    current_lines: List[str] = []
    subsection_visits: Dict[str, int] = {}

    def flush_answer() -> None:
        nonlocal current_num, current_lines
        if not current_num:
            current_lines = []
            return
        text = compact_markdown("\n".join(current_lines))
        if text:
            slug = _subsection_slug(current_subsection)
            answers[(slug, current_num)] = text
            answers[("", current_num)] = text
        current_num = ""
        current_lines = []

    def capture_answer(q_match: re.Match) -> None:
        nonlocal current_num, current_lines
        flush_answer()
        current_num = q_match.group(1)
        rest = q_match.group(2).strip()
        current_lines = [rest] if rest else []

    for line in lines[start_idx:]:
        stripped = line.strip()
        if SOLUTIONS_HEADING_RE.match(stripped):
            flush_answer()
            in_solutions = True
            current_subsection = ""
            continue
        if EXERCISE_SUBSECTION_PLAIN_RE.match(stripped):
            flush_answer()
            in_solutions = True
            current_subsection = stripped.rstrip(":").strip()
            subsection_visits[_subsection_slug(current_subsection)] = (
                subsection_visits.get(_subsection_slug(current_subsection), 0) + 1
            )
            continue
        if H2_RE.match(stripped) and not QUESTION_RE.match(stripped):
            flush_answer()
            heading = stripped.lstrip("#").strip()
            slug = _subsection_slug(heading)
            subsection_visits[slug] = subsection_visits.get(slug, 0) + 1
            current_subsection = heading
            if in_solutions or subsection_visits[slug] > 1:
                in_solutions = True
            continue
        q_match = QUESTION_RE.match(stripped)
        if not q_match:
            if current_num:
                current_lines.append(line)
            continue
        slug = _subsection_slug(current_subsection)
        is_answer = (
            in_solutions
            or subsection_visits.get(slug, 0) > 1
            or _looks_like_answer_line(q_match)
        )
        if is_answer:
            capture_answer(q_match)
        elif current_num:
            flush_answer()

    flush_answer()
    return answers


def attach_solutions_to_exercises(
    exercise_sections: List[Dict[str, Any]],
    answer_map: Dict[Tuple[str, str], str],
) -> None:
    for section in exercise_sections:
        for question in section.get("questions", []):
            num = str(question.get("number", ""))
            sub = question.get("subsection", "")
            solution = answer_map.get((sub, num), "") or answer_map.get(("", num), "")
            if not solution:
                for (slug, qnum), text in answer_map.items():
                    if qnum == num and (not sub or slug == sub):
                        solution = text
                        break
            question["solution_markdown"] = solution


def extract_theory_notes(markdown: str) -> str:
    """Regex extraction of all theory sections (excludes illustrations, exercises, case studies)."""
    parts: List[str] = []
    for sec in _split_all_h2_sections(markdown):
        title = sec.get("title", "").strip()
        if not title:
            if sec.get("body"):
                parts.append(sec["body"])
            continue
        if _is_non_theory_title(title):
            continue
        if NON_THEORY_SECTION_RE.match(title):
            continue
        if ILLUSTRATION_RE.match(f"## {title}"):
            continue
        if CASE_STUDY_RE.match(f"## {title}"):
            continue
        if EXERCISE_HEADING_RE.match(f"## {title}"):
            continue
        body = sec.get("body", "").strip()
        if not body and not title:
            continue
        parts.append(f"## {title}\n\n{body}" if body else f"## {title}")
    return compact_markdown("\n\n".join(parts))


def _is_summary_candidate_paragraph(para: str) -> bool:
    p = para.strip()
    if not p or len(p) < 40:
        return False
    if p.startswith("!["):
        return False
    if p.startswith("|") or _is_pipe_table_separator(p):
        return False
    if p.startswith("- ") or p.startswith("* ") or re.match(r"^\(\w+\)", p):
        return False
    if re.match(r"^Fig\.\s", p, re.IGNORECASE):
        return False
    if p.startswith("[image:"):
        return False
    lines = [ln.strip() for ln in p.splitlines() if ln.strip()]
    if lines and all(
        ln.startswith("-")
        or ln.startswith("*")
        or re.match(r"^\(\w+\)", ln)
        for ln in lines
    ):
        return False
    return True


def _summarize_section_body(body: str, *, max_chars: int = SUMMARY_SECTION_MAX_CHARS) -> str:
    """Regex fallback only — extracts a short excerpt, not a student rewrite."""
    if not body or not str(body).strip():
        return ""
    text = _strip_inline_cyk_from_body(str(body))
    text = MARKDOWN_IMAGE_RE.sub("", text)
    text = HTML_IMG_RE.sub("", text)
    paragraphs: List[str] = []
    for para in text.replace("\r", "").split("\n\n"):
        para = compact_markdown(para)
        if _is_summary_candidate_paragraph(para):
            paragraphs.append(para)
        if len(paragraphs) >= 1:
            break
    if not paragraphs:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("!["):
                paragraphs.append(line)
                break
    excerpt = _truncate_text("\n\n".join(paragraphs), max_chars).strip()
    if not excerpt:
        return ""
    return (
        "Key ideas (auto-excerpt — run with --summarize-llm for student-friendly notes):\n"
        + excerpt
    )


def _split_section_markdown_into_subparts(markdown: str) -> List[Dict[str, str]]:
    """Split section markdown into intro and nested ## / ### blocks."""
    parts: List[Dict[str, str]] = []
    current_title = ""
    current_lines: List[str] = []
    for line in (markdown or "").splitlines():
        stripped = line.strip()
        if H2_RE.match(stripped) or H3_RE.match(stripped):
            if current_title or current_lines:
                parts.append({
                    "title": current_title,
                    "body": compact_markdown("\n".join(current_lines)),
                })
            current_title = stripped.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_title or current_lines:
        parts.append({
            "title": current_title,
            "body": compact_markdown("\n".join(current_lines)),
        })
    return parts


def _normalize_summary_heading(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _is_auxiliary_theory_title(title: str) -> bool:
    """Pedagogy side-box headings that should not appear as summary sections."""
    if not title:
        return False
    stripped = title.strip()
    if KEY_POINTS_RE.match(f"## {stripped}"):
        return True
    lowered = stripped.lower()
    if lowered in ("physics", "connecting topic", "abstract"):
        return True
    if CHECK_KNOWLEDGE_RE.search(stripped):
        return True
    return False


def build_hierarchical_summary_from_sections(
    sections: List[Dict[str, Any]],
    *,
    chapter_name: str = "",
) -> str:
    """
    Build summary as::

        ## Chapter overview
        one unified chapter summary

        ## Topic heading
        topic summary
        ### Subtopic heading
        subtopic summary
    """
    blocks: List[str] = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        main_heading = plain_section_title(theory_section_heading(sec)) or "Section"
        if _is_auxiliary_theory_title(main_heading):
            continue
        markdown = str(sec.get("markdown") or "").strip()
        if not markdown:
            body_only = str(sec.get("body") or "").strip()
            summary = _summarize_section_body(body_only)
            if summary:
                blocks.append(f"## {main_heading}\n{summary}")
            continue

        subparts = _split_section_markdown_into_subparts(markdown)
        main_norm = _normalize_summary_heading(main_heading)
        nested = [
            sp for sp in subparts
            if sp.get("title")
            and _normalize_summary_heading(sp["title"]) != main_norm
        ]

        if nested:
            intro_body = ""
            for sp in subparts:
                title_norm = _normalize_summary_heading(sp.get("title", ""))
                if not sp.get("title"):
                    intro_body = sp.get("body", "")
                    break
                if title_norm == main_norm:
                    intro_body = sp.get("body", "")
                    break
            intro = _summarize_section_body(intro_body)
            if intro:
                blocks.append(f"## {main_heading}\n{intro}")
            for sp in nested:
                sub_heading = plain_section_title(sp.get("title", ""))
                if _is_auxiliary_theory_title(sub_heading):
                    continue
                sub_summary = _summarize_section_body(
                    sp.get("body", ""),
                    max_chars=SUMMARY_SUBSECTION_MAX_CHARS,
                )
                if sub_heading and sub_summary:
                    blocks.append(f"### {sub_heading}\n{sub_summary}")
            continue

        body = ""
        if len(subparts) == 1:
            body = subparts[0].get("body", "")
            if not body.strip() and subparts[0].get("title"):
                body = markdown
        if not body.strip():
            body = markdown
        summary = _summarize_section_body(body)
        if summary:
            blocks.append(f"## {main_heading}\n{summary}")

    topic_md = compact_markdown("\n\n".join(blocks))
    overview = _regex_chapter_overview_from_topic_blocks(blocks, chapter_name)
    return format_student_summary_document(overview, topic_md)


def format_student_summary_document(overview: str, topic_sections_md: str) -> str:
    """Chapter overview block + topic-wise ## / ### sections."""
    parts: List[str] = []
    overview = str(overview or "").strip()
    topic_sections_md = str(topic_sections_md or "").strip()
    if overview:
        parts.append(f"## {CHAPTER_OVERVIEW_HEADING}\n{overview}")
    if topic_sections_md:
        parts.append(topic_sections_md)
    return compact_markdown("\n\n".join(parts))


def _regex_chapter_overview_from_topic_blocks(
    topic_blocks: List[str],
    chapter_name: str,
) -> str:
    """Fallback: stitch short snippets from topic sections into one overview."""
    snippets: List[str] = []
    for block in topic_blocks:
        lines = block.split("\n", 1)
        if len(lines) < 2:
            continue
        body = lines[1].strip()
        body = re.sub(
            r"^Key ideas \(auto-excerpt[^)]*\):\s*",
            "",
            body,
            flags=re.IGNORECASE,
        ).strip()
        first_para = body.split("\n\n")[0].strip()
        if first_para and len(first_para) > 35:
            snippets.append(_truncate_text(first_para, 200))
        if len(snippets) >= 6:
            break
    if not snippets:
        return ""
    intro = (
        f"This chapter ({chapter_name}) covers the following core ideas. "
        if chapter_name else "This chapter covers the following core ideas. "
    )
    return _truncate_text(intro + " ".join(snippets), CHAPTER_OVERVIEW_MAX_CHARS).strip()


def build_hierarchical_summary_from_theory_notes(
    theory_notes: str,
    *,
    chapter_name: str = "",
) -> str:
    if not isinstance(theory_notes, str) or not theory_notes.strip():
        return ""
    sections, _question_md = split_theory_and_question_bank_markdown(theory_notes)
    return build_hierarchical_summary_from_sections(sections, chapter_name=chapter_name)


def _build_llm_summary_payload(
    sections: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build compact section excerpts for LLM summarization."""
    payload: List[Dict[str, Any]] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        heading = plain_section_title(theory_section_heading(sec))
        if not heading or _is_auxiliary_theory_title(heading):
            continue
        markdown = str(sec.get("markdown") or "").strip()
        subparts = _split_section_markdown_into_subparts(markdown) if markdown else []
        nested = [
            sp for sp in subparts
            if sp.get("title")
            and _normalize_summary_heading(sp["title"]) != _normalize_summary_heading(heading)
        ]
        if nested:
            intro_body = ""
            for sp in subparts:
                title_norm = _normalize_summary_heading(sp.get("title", ""))
                if not sp.get("title"):
                    intro_body = sp.get("body", "")
                    break
                if title_norm == _normalize_summary_heading(heading):
                    intro_body = sp.get("body", "")
                    break
            if intro_body.strip():
                payload.append({
                    "heading": heading,
                    "level": 2,
                    "excerpt": _truncate_text(intro_body, LLM_SUMMARY_SECTION_EXCERPT),
                })
            for sp in nested:
                sub_heading = plain_section_title(sp.get("title", ""))
                if not sub_heading or _is_auxiliary_theory_title(sub_heading):
                    continue
                body = sp.get("body", "")
                if not body.strip():
                    continue
                payload.append({
                    "heading": sub_heading,
                    "level": 3,
                    "parent": heading,
                    "excerpt": _truncate_text(body, LLM_SUMMARY_SECTION_EXCERPT),
                })
        else:
            body = ""
            if len(subparts) == 1:
                body = subparts[0].get("body", "")
            if not body.strip():
                body = markdown
            if not body.strip():
                continue
            payload.append({
                "heading": heading,
                "level": 2,
                "excerpt": _truncate_text(body, LLM_SUMMARY_SECTION_EXCERPT),
            })
        if len(payload) >= LLM_SUMMARY_MAX_SECTIONS:
            break
    return payload


def _polish_student_summary_markdown(md: str) -> str:
    """Drop duplicate headings inside summary bodies; cap section length."""
    blocks: List[str] = []
    for block in (md or "").split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        first = lines[0].strip()
        if not first.startswith("#"):
            continue
        body_lines: List[str] = []
        for ln in lines[1:]:
            stripped = ln.strip()
            if stripped.startswith("##"):
                continue
            body_lines.append(ln)
        body = compact_markdown("\n".join(body_lines))
        body = _truncate_text(body, STUDENT_SUMMARY_MAX_CHARS).strip()
        if body:
            blocks.append(f"{first}\n{body}")
    return compact_markdown("\n\n".join(blocks))


def _llm_sections_to_summary_markdown(raw: Dict[str, Any]) -> str:
    blocks: List[str] = []
    for item in raw.get("sections") or []:
        if not isinstance(item, dict):
            continue
        heading = plain_section_title(str(item.get("heading") or ""))
        summary = str(item.get("summary") or "").strip()
        if not heading or not summary:
            continue
        summary = re.sub(r"^#+\s+.*$", "", summary, flags=re.MULTILINE).strip()
        summary = _truncate_text(summary, STUDENT_SUMMARY_MAX_CHARS).strip()
        if not summary:
            continue
        level = int(item.get("level") or 2)
        prefix = "###" if level == 3 else "##"
        blocks.append(f"{prefix} {heading}\n{summary}")
    return _polish_student_summary_markdown(compact_markdown("\n\n".join(blocks)))


def _llm_generate_chapter_overview(
    client: OllamaClient,
    meta: TopicMeta,
    payload_sections: List[Dict[str, Any]],
) -> str:
    """One unified chapter summary before topic-wise sections."""
    if not payload_sections:
        return ""
    outline = []
    for item in payload_sections[:20]:
        outline.append({
            "heading": item.get("heading", ""),
            "level": item.get("level", 2),
            "excerpt": _truncate_text(str(item.get("excerpt") or ""), 350),
        })
    user = json.dumps({
        "task": (
            f"Write ONE complete chapter overview for topic {meta.topic_number}: "
            f"{meta.topic_name}. The reader should grasp the whole chapter from this block alone."
        ),
        "audience": "Class 10 physics students preparing for exams",
        "topic_number": meta.topic_number,
        "topic_name": meta.topic_name,
        "page_range": meta.page_range,
        "section_outline": outline,
    }, ensure_ascii=False)
    try:
        raw = client.chat_json(STUDENT_CHAPTER_OVERVIEW_SYSTEM, user)
        overview = str(raw.get("chapter_overview") or "").strip()
        overview = re.sub(r"^#+\s+.*$", "", overview, flags=re.MULTILINE).strip()
        return _truncate_text(overview, CHAPTER_OVERVIEW_MAX_CHARS).strip()
    except RuntimeError as exc:
        print(f"  Warning: chapter overview LLM failed ({exc}); using regex overview.")
        return ""


def _llm_extract_hierarchical_summary(
    client: OllamaClient,
    meta: TopicMeta,
    sections: List[Dict[str, Any]],
) -> str:
    payload_sections = _build_llm_summary_payload(sections)
    if not payload_sections:
        return ""
    overview = _llm_generate_chapter_overview(client, meta, payload_sections)
    if not overview:
        topic_blocks: List[str] = []
        for item in payload_sections:
            heading = plain_section_title(str(item.get("heading") or ""))
            excerpt = str(item.get("excerpt") or "").strip()
            if heading and excerpt:
                topic_blocks.append(f"## {heading}\n{excerpt[:200]}")
        overview = _regex_chapter_overview_from_topic_blocks(topic_blocks, meta.topic_name)

    system = STUDENT_SUMMARY_SYSTEM
    section_blocks: List[str] = []
    for start in range(0, len(payload_sections), LLM_SUMMARY_BATCH_SIZE):
        batch = payload_sections[start:start + LLM_SUMMARY_BATCH_SIZE]
        user = json.dumps({
            "task": (
                f"Write topic-wise student notes for topic {meta.topic_number}: "
                f"{meta.topic_name} (batch {start // LLM_SUMMARY_BATCH_SIZE + 1}). "
                "Each section is one theory topic or subtopic — NOT the whole chapter."
            ),
            "audience": "Class 10 physics students preparing for exams",
            "topic_number": meta.topic_number,
            "topic_name": meta.topic_name,
            "sections": batch,
        }, ensure_ascii=False)
        raw = client.chat_json(system, user)
        part = _llm_sections_to_summary_markdown(raw)
        if part:
            section_blocks.append(part)
    topic_md = compact_markdown("\n\n".join(section_blocks))
    return format_student_summary_document(overview, topic_md)


def enrich_topic_summary_with_llm(topic_doc: Dict[str, Any]) -> Dict[str, Any]:
    sections = topic_doc.get("theory_sections") or []
    if not sections:
        return topic_doc
    meta = TopicMeta(
        topic_number=int(topic_doc.get("topic_number") or 0),
        topic_name=str(
            topic_doc.get("chapter_name")
            or topic_doc.get("topic_name")
            or ""
        ),
        page_range=str(topic_doc.get("page_range") or ""),
    )
    client = OllamaClient()
    client.ensure_model()
    print(
        f"  Calling Ollama ({OLLAMA_MODEL}) for summary — "
        f"topic {meta.topic_number}: {meta.topic_name}..."
    )
    summary = _llm_extract_hierarchical_summary(client, meta, sections)
    if summary:
        topic_doc["summary"] = summary
        topic_doc["summary_source"] = "student_llm"
    return topic_doc


def _resolve_source_topic_md_path(topic_doc: Dict[str, Any]) -> str:
    rel = str(topic_doc.get("source_topic_md") or "").strip()
    if not rel:
        return ""
    candidates = [
        rel,
        os.path.normpath(rel),
        os.path.join(os.getcwd(), rel.replace("/", os.sep)),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def _filter_referenced_image_assets(
    assets: Dict[str, Dict[str, str]],
    referenced_ids: Set[str],
    *,
    priority_ids: Optional[Set[str]] = None,
) -> Dict[str, Dict[str, str]]:
    if not referenced_ids:
        return {}
    priority_ids = priority_ids or set()
    priority = sorted(
        img_id for img_id in referenced_ids
        if img_id in priority_ids and img_id in assets
    )
    rest = sorted(
        img_id for img_id in referenced_ids
        if img_id not in priority_ids and img_id in assets
    )
    ordered = priority + rest
    if len(ordered) > MAX_TOPIC_IMAGES:
        ordered = ordered[:MAX_TOPIC_IMAGES]
    return {img_id: assets[img_id] for img_id in ordered}


def _count_image_tokens(text: str) -> int:
    return len(re.findall(r"\[image:\s*img_\d+\]", text or "", re.IGNORECASE))


def attach_topic_images_from_source(
    topic_doc: Dict[str, Any],
    book_name: str,
) -> Dict[str, Any]:
    """
    Restore figures and table-cell images from Mathpix cache into theory_sections.
    Downloads cropped CDN images, stores base64 in image_assets, uses [image:img_NNN] tokens.
    """
    if skip_images():
        return topic_doc
    source_md_path = _resolve_source_topic_md_path(topic_doc)
    if not source_md_path and not topic_doc.get("lines"):
        return topic_doc

    theory_source = _theory_markdown_with_images_for_topic(topic_doc, book_name)
    cm_source = _concept_map_opening_markdown_for_topic(topic_doc, book_name)
    if not theory_source.strip() and cm_source.strip():
        theory_source = extract_theory_notes(cm_source) or cm_source
    if not theory_source.strip():
        return topic_doc

    topic_doc = dict(topic_doc)
    topic_doc["_concept_map_source_md"] = cm_source or theory_source

    source_sections, _question_md = split_theory_and_question_bank_markdown(theory_source)
    source_by_heading = {
        _normalize_summary_heading(theory_section_heading(sec)): str(sec.get("markdown") or "")
        for sec in source_sections
        if isinstance(sec, dict)
    }

    resolver = ImageResolver(
        book_name,
        topic_doc.get("topic_number"),
    )
    resolver.register_markdown(theory_source)
    topic_doc = _apply_concept_map_to_topic(topic_doc, resolver)

    referenced: Set[str] = set()
    existing_sections = topic_doc.get("theory_sections") or []
    for idx, sec in enumerate(existing_sections):
        if not isinstance(sec, dict):
            continue
        if _is_concept_map_theory_section(sec):
            referenced.update(re.findall(
                r"\[image:(img_\d+)\]", sec.get("markdown", ""), re.IGNORECASE,
            ))
            continue
        key = _normalize_summary_heading(theory_section_heading(sec))
        src_md = source_by_heading.get(key, "")
        if not src_md and idx < len(source_sections):
            src_md = str((source_sections[idx] or {}).get("markdown") or "")
        body = src_md or str(sec.get("markdown") or "")
        if body.strip():
            processed = process_theory_markdown_for_images(body, resolver)
            sec["markdown"] = strip_duplicate_section_heading(
                processed,
                theory_section_heading(sec),
            )
        referenced.update(re.findall(r"\[image:(img_\d+)\]", sec.get("markdown", "")))
    cm_md = str((topic_doc.get("concept_map") or {}).get("markdown") or "")
    cm_image_ids = set(re.findall(r"\[image:(img_\d+)\]", cm_md, re.IGNORECASE))
    referenced.update(cm_image_ids)

    if isinstance(topic_doc.get("summary"), str) and topic_doc["summary"].strip():
        topic_doc["summary"] = process_theory_markdown_for_images(
            topic_doc["summary"], resolver
        )
        referenced.update(re.findall(r"\[image:(img_\d+)\]", topic_doc["summary"]))

    assets = embed_base64_in_assets(resolver)
    topic_doc["image_assets"] = _filter_referenced_image_assets(
        assets, referenced, priority_ids=cm_image_ids,
    )
    topic_doc = _dedupe_concept_map_in_theory_sections(topic_doc)
    img_n = len(topic_doc.get("image_assets") or {})
    if img_n:
        print(f"    Images: {img_n} assets, {_count_image_tokens(_theory_sections_combined_markdown(existing_sections))} refs in theory")
    if not skip_mathml():
        topic_doc = apply_mathml_conversion(topic_doc, MathConverter())
    topic_doc.pop("_concept_map_source_md", None)
    topic_doc["theory_sections"] = _order_theory_sections_for_display(
        topic_doc.get("theory_sections") or [],
    )
    return topic_doc


def fix_mathml_in_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """Convert all remaining $...$ / $$...$$ LaTeX to MathML in topics[]."""
    if skip_mathml():
        return document
    math = MathConverter()
    topics_out: List[Dict[str, Any]] = []
    leak_total = 0
    for topic in document.get("topics") or []:
        if not isinstance(topic, dict):
            continue
        converted = apply_mathml_conversion(dict(topic), math)
        converted = apply_math_plain_conversion(converted)
        leak_total += len(MathConverter.scan_latex_leaks(converted))
        topics_out.append(converted)
    document = dict(document)
    document["topics"] = topics_out
    meta = dict(document.get("metadata") or {})
    meta["mathml"] = "plain_text"
    document["metadata"] = meta
    if leak_total:
        print(f"  Warning: {leak_total} topic(s) may still contain LaTeX delimiters")
    return document


def attach_images_to_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """Attach Mathpix figures/tables to every topic in a *_final.json document."""
    if skip_images():
        return document
    meta = document.get("metadata") or {}
    book_name = str(meta.get("name") or "")
    topics_out: List[Dict[str, Any]] = []
    for topic in document.get("topics") or []:
        if not isinstance(topic, dict):
            continue
        tn = topic.get("topic_number")
        name = topic.get("chapter_name") or topic.get("topic_name") or tn
        print(f"  Attach images — topic {tn}: {name}")
        topic_doc = attach_topic_images_from_source(dict(topic), book_name)
        topics_out.append(topic_doc)
    document = dict(document)
    document["topics"] = topics_out
    meta = dict(document.get("metadata") or {})
    meta["images_from_mathpix"] = True
    document["metadata"] = meta
    return document


def expand_image_tokens_to_data_urls(
    text: str,
    image_assets: Any,
) -> str:
    """Inline [image:img_NNN] as data-URL <img> tags (for MySQL / DB viewer)."""
    if not text or not image_assets:
        return text or ""
    assets_map: Dict[str, Dict[str, Any]] = {}
    if isinstance(image_assets, dict):
        assets_map = image_assets
    elif isinstance(image_assets, list):
        for item in image_assets:
            if isinstance(item, dict) and item.get("id"):
                assets_map[str(item["id"])] = item

    def repl(match: re.Match[str]) -> str:
        img_id = match.group(1)
        asset = assets_map.get(img_id) or {}
        b64 = str(asset.get("base64") or "").strip()
        if b64:
            mime = str(asset.get("mime_type") or "image/jpeg")
            clean = re.sub(r"\s+", "", b64)
            return (
                f'<img class="topic-image" alt="{html.escape(img_id)}" '
                f'src="data:{mime};base64,{clean}"/>'
            )
        url = str(asset.get("source_url") or "").strip()
        if url:
            return (
                f'<img class="topic-image" alt="{html.escape(img_id)}" '
                f'src="{html.escape(url)}"/>'
            )
        return match.group(0)

    return re.sub(r"\[image:\s*(img_\d+)\]", repl, text, flags=re.IGNORECASE)


def force_student_summary() -> bool:
    return os.environ.get("FORCE_SUMMARY", "0").lower() in ("1", "true", "yes")


def has_student_summary(topic_doc: Dict[str, Any]) -> bool:
    src = str(topic_doc.get("summary_source") or "").strip().lower()
    if src in ("student_llm", "llm"):
        return bool(str(topic_doc.get("summary") or "").strip())
    return False


def _apply_topic_summary(topic_doc: Dict[str, Any], *, skip_llm: bool = False) -> Dict[str, Any]:
    """Student-friendly summary via Ollama, or regex excerpt fallback."""
    summarize_llm = os.environ.get("LLM_SUMMARY", "0").lower() in ("1", "true", "yes")
    if has_student_summary(topic_doc) and not force_student_summary():
        if topic_doc.get("summary_source") == "llm":
            topic_doc["summary_source"] = "student_llm"
        return topic_doc
    if summarize_llm and not skip_llm:
        try:
            return enrich_topic_summary_with_llm(topic_doc)
        except RuntimeError as exc:
            print(f"  Warning: summary LLM failed ({exc}); using regex excerpt.")
    hierarchical_summary = build_hierarchical_summary_from_sections(
        topic_doc.get("theory_sections") or [],
        chapter_name=str(
            topic_doc.get("chapter_name")
            or topic_doc.get("topic_name")
            or ""
        ),
    )
    if hierarchical_summary:
        topic_doc["summary"] = hierarchical_summary
        topic_doc["summary_source"] = "regex"
    return topic_doc


def _sync_summary_to_topics_json_cache(
    document: Dict[str, Any],
    topic_doc: Dict[str, Any],
) -> None:
    """Keep topics_json/*.json summary in sync after student summary regeneration."""
    meta = document.get("metadata") or {}
    rel_dir = str(meta.get("topics_json_dir") or "").strip().replace("\\", "/")
    if not rel_dir:
        return
    tn = topic_doc.get("topic_number")
    if tn is None:
        return
    cache_path = os.path.join(rel_dir, f"topic_{int(tn):02d}.json")
    if not os.path.isfile(cache_path):
        return
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            cached = json.load(handle)
        cached["summary"] = topic_doc.get("summary", "")
        cached["summary_source"] = topic_doc.get("summary_source", "")
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump(cached, handle, indent=2, ensure_ascii=False)
        print(f"    Updated cache: {cache_path}")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"    Warning: could not update {cache_path}: {exc}")


def parse_topic_number_filter(topics_arg: Optional[str]) -> Optional[Set[int]]:
    if not topics_arg or not str(topics_arg).strip():
        return None
    out: Set[int] = set()
    for part in str(topics_arg).split(","):
        part = part.strip()
        if not part:
            continue
        out.add(int(part))
    return out or None


def regenerate_student_summaries_in_document(
    document: Dict[str, Any],
    *,
    topic_filter: Optional[Set[int]] = None,
) -> Dict[str, Any]:
    """Re-run Ollama student summaries on topics in an existing *_final.json document."""
    os.environ["LLM_SUMMARY"] = "1"
    os.environ["FORCE_SUMMARY"] = "1"
    topics_in = document.get("topics") or []
    topics_out: List[Dict[str, Any]] = []
    for topic in topics_in:
        if not isinstance(topic, dict):
            continue
        tn = int(topic.get("topic_number") or 0)
        if topic_filter and tn not in topic_filter:
            topics_out.append(topic)
            continue
        topic_doc = dict(topic)
        name = topic_doc.get("chapter_name") or topic_doc.get("topic_name") or f"Topic {tn}"
        print(f"  Student summary — topic {tn}: {name}")
        if not topic_doc.get("theory_sections"):
            theory_notes = topic_doc.get("theory_notes") or ""
            if theory_notes.strip():
                sections, _qb = split_theory_and_question_bank_markdown(theory_notes)
                topic_doc["theory_sections"] = sections
        if not topic_doc.get("theory_sections"):
            print(f"    Warning: no theory_sections for topic {tn}, skipping.")
            topics_out.append(topic_doc)
            continue
        topic_doc = enrich_topic_summary_with_llm(topic_doc)
        _sync_summary_to_topics_json_cache(document, topic_doc)
        topics_out.append(topic_doc)
    document = dict(document)
    document["topics"] = topics_out
    meta = dict(document.get("metadata") or {})
    meta["summary_style"] = "student_llm"
    document["metadata"] = meta
    return document


THEORY_NOTES_PREVIEW_LEN = int(os.environ.get("THEORY_NOTES_PREVIEW_LEN", "1500"))


def split_examples_into_labeled_buckets(
    examples: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Split merged `examples` into labelled arrays for final JSON / viewers."""
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "illustrations": [],
        "check_your_knowledge": [],
        "textbook_exercises": [],
        "exercises": [],
    }
    for ex in examples:
        source_type = ex.get("source_type", "exercise")
        if source_type == "illustration":
            buckets["illustrations"].append(ex)
        elif source_type == "check_your_knowledge":
            buckets["check_your_knowledge"].append(ex)
        elif source_type == "textbook_exercise":
            buckets["textbook_exercises"].append(ex)
        else:
            buckets["exercises"].append(ex)
    return buckets


def chapter_name_from_topic(topic: Dict[str, Any]) -> str:
    """Chapter label on a topic object (export key ``chapter_name``)."""
    return str(topic.get("chapter_name") or topic.get("topic_name") or "").strip()


def theory_section_heading(section: Dict[str, Any]) -> str:
    """Subtopic heading inside ``theory_sections[]`` (export key ``topics``)."""
    return str(section.get("topics") or section.get("title") or "").strip()


def apply_pedagogy_export_fields(topic_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    v3 export vocabulary: ``topic_name`` → ``chapter_name``;
    ``theory_sections[].title`` → ``theory_sections[].topics``.
    """
    chapter = chapter_name_from_topic(topic_doc)
    if chapter:
        topic_doc["chapter_name"] = chapter
    topic_doc.pop("topic_name", None)

    normalized_sections: List[Dict[str, Any]] = []
    for sec in topic_doc.get("theory_sections") or []:
        if not isinstance(sec, dict):
            continue
        row = dict(sec)
        heading = theory_section_heading(row)
        row.pop("title", None)
        if heading:
            row["topics"] = plain_section_title(heading)
        normalized_sections.append(row)
    topic_doc["theory_sections"] = normalized_sections
    return topic_doc


def _theory_sections_combined_markdown(sections: Any) -> str:
    blocks: List[str] = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        md = (sec.get("markdown") or "").strip()
        if md:
            blocks.append(md)
            continue
        title = (sec.get("topics") or sec.get("title") or "").strip()
        if title:
            blocks.append(f"## {title}")
    return "\n\n".join(blocks)


def _book_name_from_topic_doc(topic_doc: Dict[str, Any]) -> str:
    src = str(topic_doc.get("source_topic_md") or "").replace("\\", "/")
    parts = [p for p in src.split("/") if p]
    if len(parts) >= 2 and parts[0] == "outputs":
        return parts[1]
    return str(topic_doc.get("book_slug") or "book")


def apply_labeled_topic_layout(topic_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reorganize a topic dict for labelled consumption:
    - theory → theory_sections[] (no monolithic theory_notes)
    - examples → illustrations / check_your_knowledge / textbook_exercises / exercises
    """
    theory_notes = topic_doc.get("theory_notes") or topic_doc.get("summary") or ""
    existing_sections = topic_doc.get("theory_sections")
    if existing_sections:
        combined = _theory_sections_combined_markdown(existing_sections)
        theory_sections, question_md = split_theory_and_question_bank_markdown(combined)
        topic_doc["theory_sections"] = _order_theory_sections_for_display(theory_sections)
    elif theory_notes.strip():
        theory_sections, question_md = split_theory_and_question_bank_markdown(theory_notes)
        topic_doc["theory_sections"] = _order_theory_sections_for_display(theory_sections)
    else:
        question_md = ""
    book_slug = str(topic_doc.get("book_slug") or "")
    topic_doc = merge_question_bank_examples_into_topic(
        topic_doc, question_md, book_slug=book_slug
    )

    examples = topic_doc.get("examples") or []
    buckets = split_examples_into_labeled_buckets(examples)
    topic_doc["illustrations"] = buckets["illustrations"]
    topic_doc["check_your_knowledge_items"] = buckets["check_your_knowledge"]
    topic_doc["textbook_exercises"] = buckets["textbook_exercises"]
    topic_doc["exercises"] = buckets["exercises"]

    book_name = _book_name_from_topic_doc(topic_doc)
    if not skip_images():
        topic_doc = attach_topic_images_from_source(topic_doc, book_name)

    skip_llm = os.environ.get("SKIP_LLM", "0").lower() in ("1", "true", "yes")
    topic_doc = _apply_topic_summary(topic_doc, skip_llm=skip_llm)

    preview = theory_notes[:THEORY_NOTES_PREVIEW_LEN] if theory_notes else ""
    if theory_notes and len(theory_notes) > THEORY_NOTES_PREVIEW_LEN:
        preview += f"\n\n… ({len(theory_notes):,} chars total — see theory_sections[])"
    topic_doc["theory_notes_preview"] = strip_markdown_images(preview) if skip_images() else preview
    topic_doc.pop("theory_notes", None)
    if skip_images():
        topic_doc.pop("image_assets", None)
        for key in ("examples", "case_studies", "illustrations", "check_your_knowledge_items",
                    "textbook_exercises", "exercises", "practice_exercises"):
            for item in topic_doc.get(key) or []:
                if isinstance(item, dict):
                    item.pop("images", None)
        sanitize_topic_text_fields(topic_doc)

    return apply_pedagogy_export_fields(topic_doc)


def final_json_path_for_book(book_output_dir: str, base_name: str) -> str:
    return os.path.join(book_output_dir, f"{base_name}_final.json")


def qa_table_json_path_for_book(book_output_dir: str, base_name: str) -> str:
    return os.path.join(book_output_dir, f"{base_name}_qa_table.json")


def qa_table_json_path_from_final(final_path: str) -> str:
    """Sibling *_qa_table.json next to *_final.json (same directory)."""
    if final_path.endswith("_final.json"):
        return final_path.replace("_final.json", "_qa_table.json")
    base, ext = os.path.splitext(final_path)
    return f"{base}_qa_table{ext or '.json'}"


def save_qa_table_json_sidecar(
    document: Dict[str, Any],
    book_slug: str,
    output_path: str,
    *,
    source_final_path: str = "",
) -> str:
    """Write *_qa_table.json after *_final.json (lazy import avoids circular deps)."""
    from final_to_qa_table import save_qa_table_json_from_document

    return save_qa_table_json_from_document(
        document,
        book_slug,
        output_path,
        source_final_path=source_final_path,
    )


def _example_to_illustration_problem_solution_rows(
    ex: Dict[str, Any],
    book_slug: str,
    topic_number: int,
    order: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    problem_id = ex.get("id") or make_db_id(book_slug, topic_number, "ill", order)
    return (
        {
            "id": problem_id,
            "topic_number": topic_number,
            "order": order,
            "title": ex.get("title", ""),
            "problem_markdown": ex.get("problem_markdown") or ex.get("problem", ""),
        },
        {
            "id": f"{problem_id}_sol",
            "illustration_problem_id": problem_id,
            "topic_number": topic_number,
            "order": order,
            "solution_markdown": ex.get("solution_markdown") or ex.get("solution", ""),
        },
    )


def _normalize_example_to_cyk_row(
    ex: Dict[str, Any],
    book_slug: str,
    topic_number: int,
    order: int,
) -> Dict[str, Any]:
    row_id = ex.get("id") or make_db_id(book_slug, topic_number, "cyk", order)
    return {
        "id": row_id,
        "topic_number": topic_number,
        "order": order,
        "prompt_markdown": ex.get("prompt_markdown") or ex.get("problem", ""),
        "solution_markdown": ex.get("solution_markdown") or ex.get("solution", ""),
    }


def _example_to_exercise_section_rows(
    ex: Dict[str, Any],
    book_slug: str,
    topic_number: int,
    order: int,
    kind: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    section_id = ex.get("id") or make_db_id(book_slug, topic_number, "ex", order)
    section = {
        "id": section_id,
        "topic_number": topic_number,
        "order": order,
        "title": ex.get("title", ""),
        "kind": kind,
        "instruction_markdown": "",
    }
    prompt = ex.get("problem_markdown") or ex.get("problem", "")
    questions = [{
        "id": f"{section_id}_q001",
        "exercise_section_id": section_id,
        "topic_number": topic_number,
        "order": 1,
        "number": "1",
        "prompt_markdown": prompt,
        "solution_markdown": ex.get("solution_markdown") or ex.get("solution", ""),
        "question_type": ex.get("question_type") or _guess_question_type(
            prompt, section_type=kind, subsection=ex.get("title", "")
        ),
        "subsection_title": ex.get("title", ""),
    }]
    return section, questions


def topic_to_relational_table_rows(
    topic: Dict[str, Any],
    book_slug: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """Flatten one topic into rows keyed by table name."""
    tn = topic.get("topic_number", 0)
    topic_id = make_db_id(book_slug, tn, "topic", 1)

    rows: Dict[str, List[Dict[str, Any]]] = {
        key: [] for key in RELATIONAL_TABLE_SCHEMA
    }

    rows["topics"].append({
        "id": topic_id,
        "topic_number": tn,
        "topic_name": chapter_name_from_topic(topic),
        "page_range": topic.get("page_range", ""),
        "summary": topic.get("summary", ""),
        "source_topic_md": topic.get("source_topic_md", ""),
    })

    for order, sec in enumerate(topic.get("theory_sections") or [], start=1):
        rows["theory_sections"].append({
            "id": sec.get("id") or make_db_id(book_slug, tn, "theory", order),
            "topic_number": tn,
            "order": sec.get("order", order),
            "title": theory_section_heading(sec),
            "markdown": sec.get("markdown", ""),
        })

    for order, ill in enumerate(topic.get("illustrations") or [], start=1):
        problem_row, solution_row = _example_to_illustration_problem_solution_rows(
            ill, book_slug, tn, order
        )
        rows["illustration_problems"].append(problem_row)
        rows["illustration_solutions"].append(solution_row)

    cyk_items = topic.get("check_your_knowledge") or topic.get("check_your_knowledge_items") or []
    for order, item in enumerate(cyk_items, start=1):
        if isinstance(item, dict) and (item.get("prompt_markdown") or item.get("problem")):
            rows["check_your_knowledge"].append(
                _normalize_example_to_cyk_row(item, book_slug, tn, order)
            )
        else:
            rows["check_your_knowledge"].append(
                _normalize_example_to_cyk_row(
                    {"problem": str(item), "solution": ""}, book_slug, tn, order
                )
            )

    for order, cs in enumerate(topic.get("case_studies") or [], start=1):
        cs_id = cs.get("id") or make_db_id(book_slug, tn, "cs", order)
        rows["case_studies"].append({
            "id": cs_id,
            "topic_number": tn,
            "order": cs.get("order", order),
            "title": cs.get("title", ""),
            "body_markdown": cs.get("body_markdown") or cs.get("description", ""),
        })
        prompts = cs.get("prompts") or []
        if not prompts and cs.get("questions"):
            for q_idx, q in enumerate(cs["questions"], start=1):
                text = q if isinstance(q, str) else str(q)
                prompts.append({"label": f"Q.{q_idx}", "text": text})
        for p_order, prompt in enumerate(prompts, start=1):
            label = prompt.get("label", "") if isinstance(prompt, dict) else ""
            text = prompt.get("text", prompt) if isinstance(prompt, dict) else str(prompt)
            rows["case_study_prompts"].append({
                "id": f"{cs_id}_p{p_order:03d}",
                "case_study_id": cs_id,
                "topic_number": tn,
                "order": p_order,
                "label": label,
                "prompt_markdown": text,
            })

    ex_order = 0
    if topic.get("exercise_sections"):
        for sec in topic.get("exercise_sections") or []:
            ex_order += 1
            section_id = sec.get("id") or make_db_id(book_slug, tn, "ex", ex_order)
            rows["exercise_sections"].append({
                "id": section_id,
                "topic_number": tn,
                "order": sec.get("order", ex_order),
                "title": sec.get("title", ""),
                "kind": sec.get("kind", "other"),
                "instruction_markdown": sec.get("instruction_markdown", ""),
            })
            for q_idx, q in enumerate(sec.get("questions") or [], start=1):
                rows["questions"].append({
                    "id": q.get("id") or f"{section_id}_q{q_idx:03d}",
                    "exercise_section_id": section_id,
                    "topic_number": tn,
                    "order": q_idx,
                    "number": q.get("number", str(q_idx)),
                    "prompt_markdown": q.get("prompt_markdown", ""),
                    "solution_markdown": q.get("solution_markdown", ""),
                    "question_type": q.get("question_type", "other"),
                    "subsection_title": q.get("subsection_title", ""),
                })
    else:
        for kind, bucket in (
            ("textbook_exercise", topic.get("textbook_exercises") or []),
            ("exercise", topic.get("exercises") or []),
        ):
            for ex in bucket:
                ex_order += 1
                section, questions = _example_to_exercise_section_rows(
                    ex, book_slug, tn, ex_order, kind
                )
                rows["exercise_sections"].append(section)
                rows["questions"].extend(questions)

    for order, kp in enumerate(topic.get("key_points") or [], start=1):
        text = kp.get("text", "") if isinstance(kp, dict) else str(kp)
        rows["key_points"].append({
            "id": make_db_id(book_slug, tn, "kp", order),
            "topic_number": tn,
            "order": order,
            "text": text,
        })

    if skip_images():
        return rows

    image_assets = topic.get("image_assets") or []
    if isinstance(image_assets, dict):
        asset_items = list(image_assets.items())
    else:
        asset_items = [
            (a.get("id", f"img_{i}"), a)
            for i, a in enumerate(image_assets, start=1)
            if isinstance(a, dict)
        ]
    for order, (asset_id, asset) in enumerate(asset_items, start=1):
        if not isinstance(asset, dict):
            continue
        rows["image_assets"].append({
            "id": asset_id or asset.get("id") or make_db_id(book_slug, tn, "img", order),
            "topic_number": tn,
            "caption": asset.get("caption", ""),
            "mime_type": asset.get("mime_type", "image/jpeg"),
            "base64": asset.get("base64", ""),
        })

    return rows


def build_relational_tables_document(
    document: Dict[str, Any],
    book_slug: str,
) -> Dict[str, Any]:
    """Build flat table rows from a nested topics[] document."""
    labeled = relabel_final_json_document(document)
    schema = dict(RELATIONAL_TABLE_SCHEMA)
    if skip_images():
        schema.pop("image_assets", None)
    merged: Dict[str, List[Dict[str, Any]]] = {
        key: [] for key in schema
    }
    for topic in labeled.get("topics") or []:
        clean_topic = sanitize_topic_text_fields(dict(topic))
        part = topic_to_relational_table_rows(clean_topic, book_slug)
        for key, rows in part.items():
            if key in merged:
                merged[key].extend(rows)

    meta = dict(labeled.get("metadata") or {})
    meta["layout"] = "relational_tables"
    meta["schema_version"] = RELATIONAL_SCHEMA_VERSION
    if skip_images():
        meta["images"] = "stripped"
        src = meta.get("source_markdown", "")
        if "mathpix" in src.lower():
            meta["source_markdown"] = "topics_md/ (per-topic files; see manifest)"

    return {
        "schema_version": RELATIONAL_SCHEMA_VERSION,
        "metadata": meta,
        "db_config": get_db_config(),
        "insertion": get_insertion_config(list(schema.keys())),
        "table_schema": schema,
        "tables": merged,
    }


def enrich_topic_exercises_from_md(
    topic_doc: Dict[str, Any],
    topic_md_path: str,
    book_slug: str,
) -> Dict[str, Any]:
    """
    Re-extract all textbook/exercise questions from topic markdown with solutions mapped.
    Keeps illustrations and check-your-knowledge from cached examples.
    """
    if not topic_md_path or not os.path.exists(topic_md_path):
        print(f"  Warning: topic MD missing for exercise extract: {topic_md_path}")
        return topic_doc

    with open(topic_md_path, "r", encoding="utf-8") as handle:
        md = handle.read()

    sections = extract_exercise_sections(md)
    answer_map = extract_solution_answer_map(md)
    attach_solutions_to_exercises(sections, answer_map)
    tn = int(topic_doc.get("topic_number", 0))
    exercise_examples = exercise_sections_to_examples(sections, tn, book_slug)

    kept_examples = [
        ex for ex in (topic_doc.get("examples") or [])
        if ex.get("source_type") in ("illustration", "check_your_knowledge")
    ]
    topic_doc["examples"] = dedupe_examples_by_id(kept_examples + exercise_examples)
    topic_doc["exercise_sections"] = sections

    q_total = len(exercise_examples)
    q_solved = sum(1 for ex in exercise_examples if (ex.get("solution") or "").strip())
    print(
        f"    Exercises from MD: {q_total} questions ({q_solved} with solutions), "
        f"{len(sections)} sections"
    )
    return topic_doc


def merge_final_from_cached_topics(
    book_paths: BookPaths,
    source_pdf: str = "",
    source_markdown: str = "",
) -> Dict[str, Any]:
    """
    Rebuild *_final.json from cached topics_json/*.json only.
    No Mathpix, no topic split, no Ollama.
    """
    manifest_path = book_paths.manifest_path
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    existing_by_topic: Dict[int, Dict[str, str]] = {}
    final_path = book_paths.output_json
    if os.path.exists(final_path):
        try:
            with open(final_path, "r", encoding="utf-8") as handle:
                existing_doc = json.load(handle)
            for topic in existing_doc.get("topics") or []:
                if not isinstance(topic, dict):
                    continue
                tn = topic.get("topic_number")
                if tn is None:
                    continue
                existing_by_topic[int(tn)] = {
                    "summary": str(topic.get("summary") or ""),
                    "summary_source": str(topic.get("summary_source") or ""),
                }
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass

    topics_out: List[Dict[str, Any]] = []
    for entry in sorted(manifest, key=lambda e: e.get("topic_number", 0)):
        tn = entry.get("topic_number")
        json_path = topic_json_path(book_paths, tn)
        if not os.path.exists(json_path):
            print(f"  Warning: missing {json_path}, skipping topic {tn}")
            continue
        with open(json_path, "r", encoding="utf-8") as handle:
            cached = json.load(handle)
        theory_rel = (
            entry.get("theory_md_path") or entry.get("md_path", "")
        ).replace("\\", "/")
        examples_rel = (
            entry.get("examples_md_path") or entry.get("md_path", "")
        ).replace("\\", "/")
        topic_doc = {
            "topic_number": tn,
            "topic_name": entry.get("topic_name", ""),
            "page_range": entry.get("page_range", ""),
            "lines": entry.get("lines", ""),
            "source_topic_md": theory_rel,
            "source_topic_examples_md": examples_rel,
            "summary": cached.get("summary", ""),
            "summary_source": cached.get("summary_source", ""),
            "theory_notes": cached.get("theory_notes", ""),
            "key_points": cached.get("key_points", []),
            "case_studies": cached.get("case_studies", []),
            "examples": cached.get("examples", []),
            "practice_exercises": cached.get("practice_exercises", []),
        }
        if not skip_images():
            topic_doc["image_assets"] = cached.get("image_assets", [])

        summarize_llm = os.environ.get("LLM_SUMMARY", "0").lower() in ("1", "true", "yes")
        force_summary = force_student_summary()
        prior = existing_by_topic.get(int(tn) or 0)
        if prior and prior.get("summary"):
            keep_prior = (
                not summarize_llm
                or (
                    not force_summary
                    and str(prior.get("summary_source") or "").lower()
                    in ("student_llm", "llm")
                )
            )
            if keep_prior:
                topic_doc["summary"] = prior["summary"]
                src = str(prior.get("summary_source") or "").lower()
                topic_doc["summary_source"] = "student_llm" if src == "llm" else prior.get("summary_source", "")

        examples_md_path = (
            examples_rel if os.path.isabs(examples_rel)
            else os.path.join(book_paths.topics_md_dir, os.path.basename(examples_rel))
        )
        topic_doc = enrich_topic_exercises_from_md(
            topic_doc, examples_md_path, book_paths.base_name
        )
        topics_out.append(topic_doc)
        print(f"  Loaded topic {tn}: {entry.get('topic_name', '')}")

    md_path = source_markdown or book_paths.mathpix_md
    document = relabel_final_json_document({
        "metadata": {
            "name": book_paths.base_name,
            "source_pdf": source_pdf,
            "source_markdown": (
                "topics_md/ (per-topic files; see manifest)"
                if skip_images() and "mathpix" in md_path.lower()
                else md_path.replace("\\", "/")
            ),
            "topics_md_dir": book_paths.topics_md_dir.replace("\\", "/"),
            "topics_json_dir": book_paths.topics_json_dir.replace("\\", "/"),
            "format_version": "3.1",
            "topic_count": len(topics_out),
            "merged_from_cache": True,
        },
        "topics": topics_out,
    })
    return document


def save_relational_tables_json(
    document: Dict[str, Any],
    book_slug: str,
    output_path: str,
) -> Dict[str, Any]:
    tables_doc = build_relational_tables_document(document, book_slug)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(tables_doc, handle, indent=2, ensure_ascii=False)
    counts = {k: len(v) for k, v in tables_doc["tables"].items()}
    print(f"Saved relational tables JSON: {output_path}")
    print(f"  Row counts: {counts}")
    return tables_doc



def relabel_final_json_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """Apply labelled layout + LaTeX→MathML on every topic in a *_final.json document."""
    topics = document.get("topics") or []
    math = MathConverter()
    relabeled: List[Dict[str, Any]] = []
    leak_paths: List[str] = []
    for t in topics:
        topic = apply_labeled_topic_layout(dict(t))
        topic = apply_mathml_conversion(topic, math)
        topic = apply_math_plain_conversion(topic)
        relabeled.append(topic)
        leak_paths.extend(MathConverter.scan_latex_leaks(topic)[:3])
    if leak_paths and not skip_mathml():
        print(f"  Warning: LaTeX may remain in fields: {', '.join(leak_paths[:8])}")
    document = dict(document)
    document["topics"] = relabeled
    meta = dict(document.get("metadata") or {})
    meta["layout"] = "labeled_v1"
    meta["theory_storage"] = "theory_sections"
    meta["pedagogy_fields"] = {
        "chapter_name": "formerly topic_name on each topics[] item",
        "theory_sections.topics": "formerly theory_sections[].title",
    }
    if not skip_mathml():
        meta["mathml"] = "plain_text"
    if str(meta.get("format_version", "")).startswith("3."):
        meta["format_version"] = "3.1"
    document["metadata"] = meta
    return document


def split_theory_and_question_bank_markdown(
    markdown: str,
) -> Tuple[List[Dict[str, str]], str]:
    """
    Split markdown into pedagogy ``theory_sections`` and a concatenated question-bank
    markdown blob (MCQs, assertion/reason, blanks, etc.) for ``extract_exercise_sections``.
    """
    if not isinstance(markdown, str) or not markdown.strip():
        return [], ""
    theory_sections: List[Dict[str, str]] = []
    question_blocks: List[str] = []
    for sec in _split_all_h2_sections(markdown):
        title = (sec.get("title") or "").strip()
        body = (sec.get("body") or "").strip()
        if not title:
            if body:
                theory_sections.append({
                    "topics": "Section",
                    "markdown": compact_markdown(body),
                })
            continue
        block = f"## {title}\n\n{body}".strip() if body else f"## {title}"
        if CONCEPT_MAP_HEADING_RE.search(title):
            continue
        if _is_non_theory_title(title):
            question_blocks.append(block)
            continue
        section_title = plain_section_title(title) or title[:500]
        md = compact_markdown(body) if body.strip() else ""
        if not md and block.strip():
            md = strip_duplicate_section_heading(compact_markdown(block), section_title)
        theory_sections.append({
            "topics": section_title,
            "markdown": md,
        })
    if not theory_sections and markdown.strip() and not question_blocks:
        theory_sections.append({
            "topics": "Theory",
            "markdown": compact_markdown(markdown.strip()),
        })
    return theory_sections, compact_markdown("\n\n".join(question_blocks))


def split_theory_notes_into_sections(theory_notes: str) -> List[Dict[str, str]]:
    """
    Convert the large `theory_notes` markdown string into labelled pedagogy sections only.

    Question-bank H2 blocks (MCQs, assertion/reason, etc.) are excluded; use
    ``split_theory_and_question_bank_markdown`` when you also need the exercise blob.
    """
    sections, _question_md = split_theory_and_question_bank_markdown(theory_notes)
    return sections


def merge_question_bank_examples_into_topic(
    topic_doc: Dict[str, Any],
    question_bank_md: str,
    *,
    book_slug: str,
) -> Dict[str, Any]:
    """Parse question-bank markdown into ``examples`` / exercise buckets on ``topic_doc``."""
    if not question_bank_md.strip():
        return topic_doc
    sections = extract_exercise_sections(question_bank_md)
    answer_map = extract_solution_answer_map(question_bank_md)
    attach_solutions_to_exercises(sections, answer_map)
    tn = int(topic_doc.get("topic_number") or 0)
    bank_examples = exercise_sections_to_examples(sections, tn, book_slug)
    kept = [
        ex for ex in (topic_doc.get("examples") or [])
        if ex.get("source_type") in ("illustration", "check_your_knowledge")
    ]
    topic_doc["examples"] = dedupe_examples_by_id(kept + bank_examples)
    return topic_doc


def extract_illustrations_from_md(markdown: str) -> List[Dict[str, str]]:
    illustrations: List[Dict[str, str]] = []
    current_ill: Optional[Dict[str, str]] = None
    for line in markdown.splitlines():
        stripped = line.strip()
        ill_match = ILLUSTRATION_RE.match(stripped)
        sol_match = SOLUTION_RE.match(stripped)
        if ill_match:
            if current_ill:
                illustrations.append(current_ill)
            ill_id = _normalize_illustration_id(ill_match.group(1))
            current_ill = {
                "id": f"illustration_{ill_id}",
                "title": stripped.lstrip("#").strip(),
                "problem": "",
                "solution": "",
            }
        elif sol_match and current_ill is not None:
            current_ill["_in_solution"] = True
        elif current_ill is not None:
            if current_ill.get("_in_solution"):
                if STOP_SOLUTION_RE.match(stripped) or ILLUSTRATION_RE.match(stripped):
                    current_ill.pop("_in_solution", None)
                    current_ill["problem"] = compact_markdown(current_ill.get("problem", ""))
                    current_ill["solution"] = compact_markdown(current_ill.get("solution", ""))
                    illustrations.append(current_ill)
                    ill_match2 = ILLUSTRATION_RE.match(stripped)
                    if ill_match2:
                        ill_id = _normalize_illustration_id(ill_match2.group(1))
                        current_ill = {
                            "id": f"illustration_{ill_id}",
                            "title": stripped.lstrip("#").strip(),
                            "problem": "",
                            "solution": "",
                        }
                    else:
                        current_ill = None
                else:
                    current_ill["solution"] += line + "\n"
            else:
                current_ill["problem"] += line + "\n"
    if current_ill:
        current_ill.pop("_in_solution", None)
        current_ill["problem"] = compact_markdown(current_ill.get("problem", ""))
        current_ill["solution"] = compact_markdown(current_ill.get("solution", ""))
        illustrations.append(current_ill)
    return illustrations


def extract_check_your_knowledge_pairs(markdown: str) -> List[Dict[str, str]]:
    """Extract inline Check Your Knowledge prompts paired with the next ## SOLUTION block."""
    pairs: List[Dict[str, str]] = []
    lines = markdown.splitlines()
    pending_prompt: List[str] = []
    capture_prompt = False
    idx = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if CHECK_KNOWLEDGE_RE.search(stripped):
            capture_prompt = True
            pending_prompt = [line]
            continue
        if capture_prompt:
            if SOLUTION_RE.match(stripped):
                problem = compact_markdown("\n".join(pending_prompt))
                solution_lines: List[str] = []
                j = i + 1
                while j < len(lines):
                    nxt = lines[j].strip()
                    if H2_RE.match(nxt) and not SOLUTION_RE.match(nxt):
                        break
                    if ILLUSTRATION_RE.match(nxt) or EXERCISE_HEADING_RE.match(nxt):
                        break
                    solution_lines.append(lines[j])
                    j += 1
                pairs.append({
                    "id": f"check_knowledge_{idx + 1}",
                    "title": "Check Your Knowledge",
                    "problem": problem,
                    "solution": compact_markdown("\n".join(solution_lines)),
                })
                idx += 1
                capture_prompt = False
                pending_prompt = []
                continue
            if H2_RE.match(stripped):
                capture_prompt = False
                pending_prompt = []
            else:
                pending_prompt.append(line)
    return pairs


def _source_type_for_exercise_question(
    section: Dict[str, Any],
    question: Dict[str, Any],
) -> str:
    sub = (question.get("subsection_title") or "").lower()
    if "text-book" in sub or "textbook" in sub or "text book" in sub:
        return "textbook_exercise"
    if "exemplar" in sub:
        return "textbook_exercise"
    return _classify_exercise_source(section.get("title", ""))


def exercise_sections_to_examples(
    sections: List[Dict[str, Any]],
    topic_number: int,
    book_slug: str = "",
) -> List[Dict[str, Any]]:
    """Flatten exercise_sections[] into per-question example dicts with solutions attached."""
    results: List[Dict[str, Any]] = []
    for sec_idx, section in enumerate(sections, start=1):
        section_title = section.get("title", f"Exercise {sec_idx}")
        for q in section.get("questions", []):
            num = str(q.get("number", ""))
            sub_title = (q.get("subsection_title") or "").strip()
            label = section_title
            if sub_title and sub_title.lower() not in section_title.lower():
                label = f"{section_title} — {sub_title}"
            row_id = make_db_id(
                book_slug or "book",
                topic_number,
                "q",
                len(results) + 1,
            ) if book_slug else f"ex{sec_idx}_q{num}"
            results.append({
                "id": row_id,
                "title": f"{label} — Q{num}",
                "problem": q.get("prompt_markdown", ""),
                "solution": q.get("solution_markdown", ""),
                "source_type": _source_type_for_exercise_question(section, q),
                "type": q.get("question_type") or _guess_question_type(
                    q.get("prompt_markdown", ""),
                    q.get("subsection_title", ""),
                    section_type=_source_type_for_exercise_question(section, q),
                ),
                "question_type": q.get("question_type") or _guess_question_type(
                    q.get("prompt_markdown", ""),
                    q.get("subsection_title", ""),
                    section_type=_source_type_for_exercise_question(section, q),
                ),
                "images": [],
                "question_number": num,
                "subsection_title": sub_title,
            })
    return dedupe_examples_by_id(results)


def extract_exercise_questions(markdown: str) -> List[Dict[str, Any]]:
    """Extract every numbered question in exercise blocks and attach solutions from SOLUTIONS."""
    sections = extract_exercise_sections(markdown)
    answer_map = extract_solution_answer_map(markdown)
    attach_solutions_to_exercises(sections, answer_map)
    return exercise_sections_to_examples(sections, topic_number=0, book_slug="")


def extract_key_points_from_pre(pre: Dict[str, Any]) -> List[Dict[str, str]]:
    key_points: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for kp in pre.get("key_points_candidates", []):
        body = kp.get("body", "")
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("-") or line.startswith("(") or re.match(r"^\d+\.", line):
                text = re.sub(r"^[-•]\s*", "", line)
                text = re.sub(r"^\(\w+\)\s*", "", text)
                text = re.sub(r"^\d+\.\s*", "", text).strip()
                if text and text not in seen:
                    seen.add(text)
                    key_points.append({"text": text})
    return key_points[:20]


def dedupe_examples_by_id(examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure every example has a unique id (renames duplicates in-place)."""
    seen: Set[str] = set()
    for ex in examples:
        eid = str(ex.get("id") or "")
        if not eid or eid not in seen:
            if eid:
                seen.add(eid)
            continue
        base = eid
        n = 2
        while f"{base}_{n}" in seen:
            n += 1
        new_id = f"{base}_{n}"
        ex["id"] = new_id
        seen.add(new_id)
    return examples


def extract_case_studies_structured(markdown: str) -> List[Dict[str, Any]]:
    case_studies: List[Dict[str, Any]] = []
    for i, cs in enumerate(
        s for s in _split_sections_by_heading(markdown, CASE_STUDY_RE)
        if "CASE STUDY" in s.get("title", "").upper()
    ):
        prompts = parse_case_study_prompts(cs.get("body", ""))
        case_studies.append({
            "id": f"case_study_{i + 1}",
            "title": cs.get("title", ""),
            "description": cs.get("body", ""),
            "questions": [p["text"] for p in prompts] if prompts else [],
            "images": [],
        })
    return case_studies


def build_structured_theory_from_md(md: str, pre: Dict[str, Any]) -> Dict[str, Any]:
    """Regex-first theory slice: summary, theory_notes, key_points."""
    theory = extract_theory_notes(md)
    key_points = extract_key_points_from_pre(pre)
    if len(key_points) < 3 and theory:
        key_points.append({
            "text": _truncate_text(theory.replace("\n", " "), 400),
        })
    summary = build_hierarchical_summary_from_theory_notes(theory)
    if not summary:
        summary = theory or f"Topic: {pre.get('topic_name', '')}"
    return {
        "summary": summary,
        "theory_notes": theory,
        "key_points": key_points or [{"text": f"Study {pre.get('topic_name', '')} concepts."}],
    }


def build_structured_examples_from_md(md: str, pre: Dict[str, Any]) -> Dict[str, Any]:
    """Regex-first examples slice: illustrations, CYK, exercises, case studies."""
    illustrations = extract_illustrations_from_md(md)
    check_pairs = extract_check_your_knowledge_pairs(md)
    exercise_items = extract_exercise_questions(md)

    examples: List[Dict[str, Any]] = []
    for ill in illustrations:
        examples.append({
            "id": ill["id"],
            "title": ill.get("title", ill["id"]),
            "problem": ill.get("problem", ""),
            "solution": ill.get("solution", ""),
            "source_type": "illustration",
            "type": "numeric",
            "images": [],
        })
    for pair in check_pairs:
        examples.append({
            "id": pair["id"],
            "title": pair.get("title", "Check Your Knowledge"),
            "problem": pair.get("problem", ""),
            "solution": pair.get("solution", ""),
            "source_type": "check_your_knowledge",
            "type": "short",
            "images": [],
        })
    for ex in exercise_items:
        examples.append({
            "id": ex["id"],
            "title": ex.get("title", ex["id"]),
            "problem": ex.get("problem", ""),
            "solution": ex.get("solution", ""),
            "source_type": ex.get("source_type", "exercise"),
            "type": ex.get("type", "short"),
            "images": [],
        })
    examples = dedupe_examples_by_id(examples)

    case_studies = extract_case_studies_structured(md)
    if not case_studies:
        for i, cs in enumerate(pre.get("case_studies", [])):
            case_studies.append({
                "id": cs.get("id", f"case_study_{i + 1}"),
                "title": cs.get("title", ""),
                "description": cs.get("body", ""),
                "questions": [],
                "images": [],
            })

    practice = [
        {
            "id": ex["id"],
            "question": ex["problem"],
            "type": ex.get("type", "short"),
            "source_type": ex.get("source_type", "exercise"),
            "images": [],
        }
        for ex in exercise_items
        if not ex.get("solution")
    ][:MAX_PRACTICE_EXERCISES]

    return {
        "case_studies": case_studies,
        "examples": examples,
        "practice_exercises": practice,
    }


def build_structured_topic_from_md(md: str, pre: Dict[str, Any]) -> Dict[str, Any]:
    """Regex-first structured topic: full theory notes + all questions from MD."""
    theory_part = build_structured_theory_from_md(md, pre)
    examples_part = build_structured_examples_from_md(md, pre)
    return {
        **theory_part,
        **examples_part,
    }


def merge_topic_theory_and_examples(
    theory: Dict[str, Any],
    examples: Dict[str, Any],
    pre: Dict[str, Any],
) -> Dict[str, Any]:
    summary = theory.get("summary") or ""
    if not summary:
        summary = f"Topic: {pre.get('topic_name', '')}"
    return {
        "summary": summary,
        "theory_notes": theory.get("theory_notes", ""),
        "key_points": theory.get("key_points") or [{"text": f"Study {pre.get('topic_name', '')} concepts."}],
        "case_studies": examples.get("case_studies", []),
        "examples": examples.get("examples", []),
        "practice_exercises": examples.get("practice_exercises", []),
    }


def _merge_key_points(
    regex_kps: List[Dict[str, str]],
    llm_kps: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = list(regex_kps)
    seen = {kp.get("text", "") for kp in merged}
    for kp in llm_kps:
        text = kp.get("text", "") if isinstance(kp, dict) else str(kp)
        if text and text not in seen:
            seen.add(text)
            merged.append({"text": text})
    return merged[:20]


def _llm_extract_key_points(
    client: OllamaClient,
    meta: TopicMeta,
    theory_excerpt: str,
) -> List[Dict[str, str]]:
    system = (
        "You are a physics study assistant. Return ONLY JSON: "
        '{"key_points": [{"text": "string"}]}. '
        "Extract 8-15 concise bullet key points from the theory excerpt. "
        "Do not invent facts not present in the excerpt."
    )
    user = json.dumps({
        "topic_number": meta.topic_number,
        "topic_name": meta.topic_name,
        "theory_excerpt": _truncate_text(theory_excerpt, 12000),
    }, ensure_ascii=False)
    raw = client.chat_json(system, user)
    kps = raw.get("key_points", [])
    return [kp for kp in kps if isinstance(kp, dict) and kp.get("text")]


def _split_sections_by_heading(markdown: str, heading_re: re.Pattern) -> List[Dict[str, str]]:
    sections: List[Dict[str, str]] = []
    current_title = ""
    current_body: List[str] = []

    for line in markdown.splitlines():
        stripped = line.strip()
        if heading_re.match(stripped):
            if current_title or current_body:
                sections.append({
                    "title": current_title,
                    "body": compact_markdown("\n".join(current_body)),
                })
            current_title = stripped.lstrip("#").strip()
            current_body = []
        else:
            current_body.append(line)

    if current_title or current_body:
        sections.append({
            "title": current_title,
            "body": compact_markdown("\n".join(current_body)),
        })
    return sections


def pre_extract_topic(chunk: TopicChunk) -> Dict[str, Any]:
    md = chunk.markdown
    case_studies = [
        s for s in _split_sections_by_heading(md, CASE_STUDY_RE)
        if "CASE STUDY" in s.get("title", "").upper()
    ]
    for i, cs in enumerate(case_studies):
        cs["id"] = f"case_study_{i + 1}"

    key_points_sections = _split_sections_by_heading(md, KEY_POINTS_RE)
    key_points_candidates = [
        {"title": s["title"], "body": s["body"]}
        for s in key_points_sections if s["body"]
    ]

    return {
        "topic_number": chunk.meta.topic_number,
        "topic_name": chunk.meta.topic_name,
        "page_range": chunk.meta.page_range,
        "theory_preview": extract_theory_notes(md)[:8000],
        "case_studies": case_studies,
        "examples": extract_illustrations_from_md(md),
        "key_points_candidates": key_points_candidates,
        "practice_questions": extract_exercise_questions(md),
        "headings": chunk.headings,
    }


class MathConverter:
    def __init__(self):
        self._warned = False

    def latex_to_mathml(self, latex: str) -> str:
        latex = latex.strip()
        if not latex:
            return ""
        if latex2mathml_converter is None:
            if not self._warned:
                print("Warning: latex2mathml not installed; wrapping LaTeX in mtext.")
                self._warned = True
            escaped = latex.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return f"<math xmlns='http://www.w3.org/1998/Math/MathML'><mtext>{escaped}</mtext></math>"
        try:
            return latex2mathml_converter.convert(latex)
        except Exception:
            escaped = latex.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return f"<math xmlns='http://www.w3.org/1998/Math/MathML'><mtext>{escaped}</mtext></math>"

    def convert_text(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return text

        def block_replace(match: re.Match) -> str:
            return self.latex_to_mathml(match.group(1))

        def inline_replace(match: re.Match) -> str:
            return self.latex_to_mathml(match.group(1))

        result = LATEX_BLOCK_RE.sub(block_replace, text)
        result = LATEX_INLINE_RE.sub(inline_replace, result)
        return result

    def convert_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.convert_text(value)
        if isinstance(value, list):
            return [self.convert_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self.convert_value(v) for k, v in value.items()}
        return value

    @staticmethod
    def scan_latex_leaks(obj: Any, path: str = "") -> List[str]:
        leaks: List[str] = []
        if isinstance(obj, str) and LATEX_LEAK_RE.search(obj):
            leaks.append(path or "root")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                leaks.extend(MathConverter.scan_latex_leaks(v, f"{path}.{k}" if path else k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                leaks.extend(MathConverter.scan_latex_leaks(v, f"{path}[{i}]"))
        return leaks


def apply_mathml_conversion(
    data: Any,
    math: Optional[MathConverter] = None,
) -> Any:
    """Convert $...$ and $$...$$ LaTeX to MathML in all string fields (recursive)."""
    if skip_mathml():
        return data
    converter = math or MathConverter()
    return converter.convert_value(data)


_SUPERSCRIPT_CHARS = str.maketrans({
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶",
    "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻", "−": "⁻", "=": "⁼",
    "(": "⁽", ")": "⁾", "n": "ⁿ", "i": "ⁱ",
})

_MO_TRIM_RE = re.compile(r"^[\s\u00A0]+|[\s\u00A0]+$")
_NO_SPACE_BEFORE = set(".,;:!?)]}°′″")
_NO_SPACE_AFTER = set("([{")


def _mathml_local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag.lstrip("/")


def _format_superscript(exp: str) -> str:
    exp = re.sub(r"\s+", "", exp.strip())
    if not exp:
        return ""
    if exp in ("circ", "°", "∘") or "°" in exp:
        return "°"
    return exp.translate(_SUPERSCRIPT_CHARS)


def _latex_to_readable_plain(latex: str) -> str:
    """Readable plain text from LaTeX (mirrors viewer ``latexToReadable``)."""
    s = str(latex or "").strip()
    if not s:
        return ""
    s = re.sub(r"\\text\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\mathrm\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\mathbf\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", s)
    s = re.sub(r"\\frac\{([^{}]+)\}", r"(\1)", s)

    def _sup_repl(match: re.Match) -> str:
        return _format_superscript(match.group(1))

    s = re.sub(r"\^\{([^{}]+)\}", _sup_repl, s)
    s = re.sub(r"_\{([^{}]+)\}", r"_\1", s)
    for pat, repl in (
        (r"\\circ", "°"), (r"\\theta", "θ"), (r"\\alpha", "α"), (r"\\beta", "β"),
        (r"\\pi", "π"), (r"\\mu", "μ"), (r"\\times", "×"), (r"\\cdot", "·"),
        (r"\\leq", "≤"), (r"\\geq", "≥"), (r"\\neq", "≠"), (r"\\infty", "∞"),
        (r"\\rightarrow", "→"), (r"\\leftarrow", "←"), (r"\\Rightarrow", "⇒"),
        (r"\\quad", " "),
    ):
        s = re.sub(pat, repl, s)
    s = s.replace(r"\left(", "(").replace(r"\right)", ")")
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    s = re.sub(r"[{}]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _mathml_leaf_text(elem: ET.Element) -> str:
    parts: List[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_mathml_element_to_plain(child))
        if child.tail:
            parts.append(child.tail)
    return html.unescape("".join(parts)).strip()


def _mathml_join_parts(parts: List[str]) -> str:
    out: List[str] = []
    for part in parts:
        piece = re.sub(r"\s+", " ", str(part or "").strip())
        if not piece:
            continue
        if out:
            prev = out[-1]
            if (
                piece[0] not in _NO_SPACE_BEFORE
                and prev[-1] not in _NO_SPACE_AFTER
                and not (prev[-1].isalnum() and piece[0] in "=<>±∓∴∵")
            ):
                out.append(" ")
        out.append(piece)
    return "".join(out)


def _mathml_element_to_plain(elem: ET.Element) -> str:
    tag = _mathml_local_tag(elem.tag)
    if tag in ("math", "mrow", "mstyle", "mpadded", "mphantom", "semantics"):
        return _mathml_join_parts([_mathml_element_to_plain(c) for c in elem])
    if tag in ("mn", "mi", "mtext", "ms"):
        return _mathml_leaf_text(elem)
    if tag == "mo":
        sym = _MO_TRIM_RE.sub("", _mathml_leaf_text(elem))
        if sym in ("", "\u200B"):
            return ""
        if sym in ("⁡",):
            return ""
        return sym
    if tag == "mspace":
        return " "
    if tag == "mfrac":
        kids = list(elem)
        if len(kids) >= 2:
            num = _mathml_element_to_plain(kids[0])
            den = _mathml_element_to_plain(kids[1])
            if re.fullmatch(r"[\w\d.]+", num) and re.fullmatch(r"[\w\d.]+", den):
                return f"{num}/{den}"
            return f"({num})/({den})"
        return _mathml_element_to_plain(kids[0]) if kids else ""
    if tag == "msup":
        kids = list(elem)
        if len(kids) >= 2:
            base = _mathml_element_to_plain(kids[0])
            exp = _mathml_element_to_plain(kids[1])
            return base + _format_superscript(exp)
        return _mathml_element_to_plain(kids[0]) if kids else ""
    if tag == "msub":
        kids = list(elem)
        if len(kids) >= 2:
            return _mathml_element_to_plain(kids[0]) + _mathml_element_to_plain(kids[1])
        return _mathml_element_to_plain(kids[0]) if kids else ""
    if tag == "msubsup":
        kids = list(elem)
        if len(kids) >= 3:
            base = _mathml_element_to_plain(kids[0])
            sub = _mathml_element_to_plain(kids[1])
            sup = _format_superscript(_mathml_element_to_plain(kids[2]))
            return f"{base}_{sub}{sup}"
        return _mathml_join_parts([_mathml_element_to_plain(c) for c in kids])
    if tag == "msqrt":
        inner = _mathml_join_parts([_mathml_element_to_plain(c) for c in elem])
        return f"√({inner})" if inner else "√"
    if tag == "mroot":
        kids = list(elem)
        if len(kids) >= 2:
            rad = _mathml_element_to_plain(kids[0])
            idx = _mathml_element_to_plain(kids[1])
            return f"{rad}^(1/{idx})"
        return _mathml_join_parts([_mathml_element_to_plain(c) for c in kids])
    if tag in ("mover", "munder", "munderover", "mtable", "mtr", "mtd"):
        return _mathml_join_parts([_mathml_element_to_plain(c) for c in elem])
    if tag == "mfenced":
        open_ch = elem.get("open") or "("
        close_ch = elem.get("close") or ")"
        inner = _mathml_join_parts([_mathml_element_to_plain(c) for c in elem])
        return f"{open_ch}{inner}{close_ch}"
    return _mathml_leaf_text(elem)


def _sanitize_mathml_for_xml(block: str) -> str:
    """Escape bare ``&`` so MathML with ``<mi>&</mi>`` parses."""
    return re.sub(
        r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)",
        "&amp;",
        block,
    )


def mathml_block_to_plain(block: str) -> str:
    """Convert one ``<math>...</math>`` fragment to readable plain text."""
    raw = str(block or "").strip()
    if not raw:
        return ""
    try:
        root = ET.fromstring(_sanitize_mathml_for_xml(raw))
    except ET.ParseError:
        return _mathml_block_to_plain_fallback(raw)
    plain = _mathml_element_to_plain(root).strip()
    return plain


def _mathml_block_to_plain_fallback(block: str) -> str:
    """Best-effort plain text when XML parsing fails."""
    text = re.sub(r"<mspace[^>]*/?>", " ", block, flags=re.IGNORECASE)
    text = re.sub(r"<mtext[^>]*>([\s\S]*?)</mtext>", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"<mn[^>]*>([\s\S]*?)</mn>", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"<mi[^>]*>([\s\S]*?)</mi>", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"<mo[^>]*>([\s\S]*?)</mo>", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def replace_mathml_with_plain_text(text: str) -> str:
    if not text or not isinstance(text, str) or "<math" not in text.lower():
        return text

    def _repl(match: re.Match) -> str:
        return mathml_block_to_plain(match.group(0))

    out = MATHML_BLOCK_RE.sub(_repl, text)
    if "$" in out:
        out = LATEX_BLOCK_RE.sub(
            lambda m: _latex_to_readable_plain(m.group(1)), out,
        )
        out = LATEX_INLINE_RE.sub(
            lambda m: _latex_to_readable_plain(m.group(1)), out,
        )
    return out


def apply_math_plain_conversion(data: Any) -> Any:
    """Replace MathML (and any leftover $...$ LaTeX) with readable plain text."""
    if isinstance(data, str):
        return replace_mathml_with_plain_text(data)
    if isinstance(data, list):
        return [apply_math_plain_conversion(v) for v in data]
    if isinstance(data, dict):
        return {k: apply_math_plain_conversion(v) for k, v in data.items()}
    return data


def fix_math_plain_in_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """Convert MathML/LaTeX in all topics[] strings to readable plain text."""
    document = dict(document)
    topics_out: List[Dict[str, Any]] = []
    for topic in document.get("topics") or []:
        if isinstance(topic, dict):
            topics_out.append(apply_math_plain_conversion(dict(topic)))
    document["topics"] = topics_out
    meta = dict(document.get("metadata") or {})
    meta["mathml"] = "plain_text"
    document["metadata"] = meta
    return document


class ImageResolver:
    def __init__(self, book_name: str, topic_number: Optional[int] = None):
        self.book_name = book_name
        self.topic_number = topic_number
        base = os.path.join(IMAGE_CACHE_DIR, book_name)
        if topic_number is not None:
            base = os.path.join(base, f"topic_{int(topic_number):02d}")
        self.cache_dir = base
        self.url_to_id: Dict[str, str] = {}
        self.assets: Dict[str, Dict[str, str]] = {}
        self._counter = 0
        os.makedirs(self.cache_dir, exist_ok=True)

    def register_markdown(self, markdown: str) -> None:
        for url in IMAGE_MD_RE.findall(markdown):
            if url not in self.url_to_id:
                self._counter += 1
                img_id = f"img_{self._counter:03d}"
                self.url_to_id[url] = img_id
                ext = ".jpg"
                if ".png" in url.lower():
                    ext = ".png"
                local_path = os.path.join(self.cache_dir, f"{img_id}{ext}")
                self.assets[img_id] = {
                    "source_url": url,
                    "file": local_path.replace("\\", "/"),
                }

    def _mathpix_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if MATHPIX_APP_ID and MATHPIX_APP_KEY:
            headers["app_id"] = MATHPIX_APP_ID
            headers["app_key"] = MATHPIX_APP_KEY
        return headers

    def _ensure_downloaded(self, url: str, local_path: str) -> None:
        if os.path.exists(local_path):
            return
        try:
            resp = requests.get(
                url,
                headers=self._mathpix_headers(),
                timeout=60,
            )
            if resp.ok:
                with open(local_path, "wb") as f:
                    f.write(resp.content)
                return
            print(f"Warning: download HTTP {resp.status_code} for {url[:80]}...")
        except Exception as exc:
            print(f"Warning: failed to download {url}: {exc}")

    def replace_urls_with_ids(self, text: str) -> str:
        def repl(match: re.Match) -> str:
            url = match.group(1)
            img_id = self.url_to_id.get(url, "")
            return f"[image:{img_id}]" if img_id else match.group(0)
        return IMAGE_MD_RE.sub(repl, text)

    def collect_referenced_ids(self, obj: Any) -> Set[str]:
        found: Set[str] = set()
        if isinstance(obj, str):
            found.update(re.findall(r"\[image:(img_\d+)\]", obj))
            for url, img_id in self.url_to_id.items():
                if url in obj:
                    found.add(img_id)
        elif isinstance(obj, dict):
            for v in obj.values():
                found.update(self.collect_referenced_ids(v))
        elif isinstance(obj, list):
            for v in obj:
                found.update(self.collect_referenced_ids(v))
        return found

    def build_image_list(self, referenced_ids: Set[str]) -> List[Dict[str, str]]:
        if skip_images():
            return []
        images: List[Dict[str, str]] = []
        for img_id in sorted(referenced_ids):
            asset = self.assets.get(img_id)
            if not asset:
                continue
            local_path = asset["file"]
            if not os.path.exists(local_path):
                self._ensure_downloaded(asset["source_url"], local_path)
            if not os.path.exists(local_path):
                continue
            with open(local_path, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
            mime = "image/png" if local_path.endswith(".png") else "image/jpeg"
            images.append({
                "id": img_id,
                "caption": "",
                "base64": data,
                "mime_type": mime,
            })
        return images

    def get_assets_dict(self) -> Dict[str, Dict[str, str]]:
        return dict(self.assets)


def embed_base64_in_assets(resolver: ImageResolver) -> Dict[str, Dict[str, str]]:
    """Embed base64 image data in all registered assets for the final JSON."""
    if skip_images():
        return {}
    assets_out: Dict[str, Dict[str, str]] = {}
    for img_id, asset in resolver.assets.items():
        entry = dict(asset)
        local_path = entry.get("file", "")
        if local_path and not os.path.isabs(local_path):
            local_path = os.path.normpath(local_path)
        if local_path and os.path.exists(local_path):
            with open(local_path, "rb") as handle:
                entry["base64"] = base64.b64encode(handle.read()).decode("ascii")
            entry["mime_type"] = (
                "image/png" if local_path.lower().endswith(".png") else "image/jpeg"
            )
        elif entry.get("source_url"):
            resolver._ensure_downloaded(entry["source_url"], local_path)
            if local_path and os.path.exists(local_path):
                with open(local_path, "rb") as handle:
                    entry["base64"] = base64.b64encode(handle.read()).decode("ascii")
                entry["mime_type"] = (
                    "image/png" if local_path.lower().endswith(".png") else "image/jpeg"
                )
        assets_out[img_id] = entry
    return assets_out


def _extract_json_from_llm_text(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise json.JSONDecodeError("Empty LLM response", "", 0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if fenced:
            return json.loads(fenced.group(1).strip())
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = OLLAMA_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def ensure_model(self) -> None:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            model_lower = self.model.lower()
            for available_name in models:
                if available_name.lower() == model_lower:
                    self.model = available_name
                    return
            model_base = self.model.split(":")[0].lower()
            for available_name in models:
                if available_name.split(":")[0].lower() == model_base:
                    self.model = available_name
                    return
            if self.model not in models:
                available = ", ".join(models[:5]) or "(none)"
                raise RuntimeError(
                    f"Ollama model '{self.model}' not found. Available: {available}. "
                    f"Run: ollama pull {self.model}"
                )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {self.base_url}. Start Ollama and pull {self.model}."
            ) from exc

    def chat_json(
        self,
        system: str,
        user: str,
        retries: int = OLLAMA_RETRIES,
    ) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2, "num_predict": 4096},
        }
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                resp = requests.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=OLLAMA_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                message = data.get("message", {})
                content = (message.get("content") or "").strip()
                if not content:
                    content = (message.get("thinking") or "").strip()
                if not content:
                    done_reason = data.get("done_reason", "unknown")
                    raise json.JSONDecodeError(
                        f"Empty Ollama message (done_reason={done_reason})",
                        "",
                        0,
                    )
                return _extract_json_from_llm_text(content)
            except (json.JSONDecodeError, requests.RequestException, KeyError) as exc:
                last_err = exc
                if attempt + 1 < retries:
                    print(
                        f"  Ollama attempt {attempt + 1}/{retries} failed "
                        f"({len(user)} char prompt): {exc}"
                    )
                time.sleep(2)
        raise RuntimeError(f"Ollama JSON call failed after {retries} attempts: {last_err}")

    def chat_markdown(
        self,
        system: str,
        user: str,
        retries: int = OLLAMA_RETRIES,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": OLLAMA_MD_NUM_PREDICT},
        }
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                resp = requests.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=OLLAMA_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                message = data.get("message", {})
                content = (message.get("content") or "").strip()
                if not content:
                    content = (message.get("thinking") or "").strip()
                if not content:
                    done_reason = data.get("done_reason", "unknown")
                    raise RuntimeError(
                        f"Empty Ollama markdown response (done_reason={done_reason})"
                    )
                return strip_llm_markdown_fences(content)
            except (requests.RequestException, RuntimeError) as exc:
                last_err = exc
                if attempt + 1 < retries:
                    print(
                        f"  Ollama MD attempt {attempt + 1}/{retries} failed "
                        f"({len(user)} char prompt): {exc}"
                    )
                time.sleep(2)
        raise RuntimeError(
            f"Ollama markdown call failed after {retries} attempts: {last_err}"
        )


def strip_llm_markdown_fences(text: str) -> str:
    cleaned = text.strip()
    fence_match = re.match(
        r"^```(?:markdown|md)?\s*\n(.*)\n```\s*$",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if fence_match:
        return fence_match.group(1).strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return cleaned


def _llm_schema_payload() -> Dict[str, Any]:
    return {
        "max_practice_exercises": MAX_PRACTICE_EXERCISES,
        "required_top_level_keys": [
            "summary", "key_points", "case_studies", "examples", "practice_exercises",
        ],
        "required_schema": {
            "summary": "string (2-4 paragraphs, no nested document/sections wrapper)",
            "key_points": [{"text": "string"}],
            "case_studies": [{
                "id": "string",
                "title": "string",
                "description": "string",
                "questions": ["string"],
            }],
            "examples": [{
                "id": "string",
                "title": "string",
                "problem": "string",
                "solution": "string",
            }],
            "practice_exercises": [{
                "id": "string",
                "question": "string",
                "type": "mcq|short|numeric",
            }],
        },
        "do_not_wrap_in": ["document", "sections", "data"],
    }


def _build_llm_prompt_from_markdown(
    meta: TopicMeta,
    markdown_text: str,
    section_title: Optional[str] = None,
) -> Tuple[str, str]:
    system = (
        "You are a physics textbook structuring assistant. "
        "Analyze the provided topic markdown and return ONLY valid JSON matching the schema. "
        "Preserve all physics facts and formulas from the source markdown. "
        "Do not invent new problems or examples. "
        "summary: for each theory heading, write easy revision notes for Class 10 students:\n"
        "## Topic heading\\n3-5 short sentences in plain English (concepts to remember, not copy-paste). "
        "If subtopics exist, add ### Subtopic heading\\n2-4 sentences each. "
        "Do not paste textbook paragraphs.\n"
        "key_points: bullet list from theory, 'Keep in Memory', 'Learn More', and major concepts. "
        "case_studies: include ONLY if ## CASE STUDY sections exist in the markdown; "
        "use title, full description, and any follow-up questions from the source. "
        "examples: extract EVERY ## ILLUSTRATION block with its paired ## SOLUTION; "
        "include the complete problem statement and full solution text for each. "
        "practice_exercises: from Exercise / Text-Book Exercise sections if present, else []. "
        "Reference images as [image:img_NNN] when URLs appear in markdown. "
        "Do NOT use LaTeX $ delimiters; keep formulas as plain text."
    )
    md_budget = max(4000, LLM_MAX_USER_CHARS - 6000)
    md_body = _truncate_text(markdown_text, md_budget)
    task = (
        f"Analyze section '{section_title}' of topic {meta.topic_number}: {meta.topic_name}. "
        "Extract content from this section only."
        if section_title
        else (
            f"Analyze the complete topic markdown for topic {meta.topic_number}: "
            f"{meta.topic_name}. Structure into summary, key_points, case_studies, "
            "examples, and practice_exercises."
        )
    )
    user_payload: Dict[str, Any] = {
        "task": task,
        "topic_number": meta.topic_number,
        "topic_name": meta.topic_name,
        "page_range": meta.page_range,
        **_llm_schema_payload(),
        "markdown": md_body,
    }
    if section_title:
        user_payload["section_title"] = section_title
    user = json.dumps(user_payload, ensure_ascii=False, indent=2)
    return system, user


def _build_llm_theory_prompt(
    meta: TopicMeta,
    markdown_text: str,
    section_title: Optional[str] = None,
) -> Tuple[str, str]:
    system = (
        "You are a physics textbook structuring assistant. "
        "Analyze the provided THEORY-ONLY topic markdown and return ONLY valid JSON with keys: "
        "summary, key_points, theory_notes. "
        "summary: for each theory heading, write ## Heading then 1-2 summary paragraphs; "
        "use ### Subheading blocks for nested subtopics. Do not paste raw theory text. "
        "key_points: 8-15 bullets from theory, 'Keep in Memory', 'Learn More', and major concepts. "
        "theory_notes: condensed markdown of core theory (optional; may mirror source headings). "
        "Do not invent illustrations, exercises, or case studies. "
        "Do NOT use LaTeX $ delimiters; keep formulas as plain text."
    )
    md_budget = max(4000, LLM_MAX_USER_CHARS - 6000)
    md_body = _truncate_text(markdown_text, md_budget)
    task = (
        f"Analyze theory section '{section_title}' of topic {meta.topic_number}: {meta.topic_name}."
        if section_title
        else (
            f"Analyze theory markdown for topic {meta.topic_number}: {meta.topic_name}. "
            "Extract summary, key_points, and theory_notes only."
        )
    )
    user_payload: Dict[str, Any] = {
        "task": task,
        "topic_number": meta.topic_number,
        "topic_name": meta.topic_name,
        "page_range": meta.page_range,
        "required_top_level_keys": ["summary", "key_points", "theory_notes"],
        "markdown": md_body,
    }
    if section_title:
        user_payload["section_title"] = section_title
    return system, json.dumps(user_payload, ensure_ascii=False, indent=2)


def _build_llm_examples_prompt(
    meta: TopicMeta,
    markdown_text: str,
    section_title: Optional[str] = None,
) -> Tuple[str, str]:
    system = (
        "You are a physics textbook structuring assistant. "
        "Analyze the provided EXAMPLES topic markdown (illustrations, solutions, exercises, "
        "case studies, Check Your Knowledge) and return ONLY valid JSON with keys: "
        "case_studies, examples, practice_exercises. "
        "case_studies: include ONLY if ## CASE STUDY sections exist. "
        "examples: extract EVERY ## ILLUSTRATION with paired ## SOLUTION, Check Your Knowledge blocks, "
        "and numbered exercise questions with solutions when present. "
        "Each example needs id, title, problem, solution. "
        f"practice_exercises: unsolved questions only, max {MAX_PRACTICE_EXERCISES}. "
        "Do not invent new problems. Reference images as [image:img_NNN]. "
        "Do NOT use LaTeX $ delimiters."
    )
    md_budget = max(4000, LLM_MAX_USER_CHARS - 6000)
    md_body = _truncate_text(markdown_text, md_budget)
    task = (
        f"Analyze examples section '{section_title}' of topic {meta.topic_number}: {meta.topic_name}."
        if section_title
        else (
            f"Analyze examples markdown for topic {meta.topic_number}: {meta.topic_name}. "
            "Extract case_studies, examples, and practice_exercises."
        )
    )
    user_payload: Dict[str, Any] = {
        "task": task,
        "topic_number": meta.topic_number,
        "topic_name": meta.topic_name,
        "page_range": meta.page_range,
        "max_practice_exercises": MAX_PRACTICE_EXERCISES,
        "required_top_level_keys": ["case_studies", "examples", "practice_exercises"],
        "markdown": md_body,
    }
    if section_title:
        user_payload["section_title"] = section_title
    return system, json.dumps(user_payload, ensure_ascii=False, indent=2)


def _normalize_llm_theory_response(
    result: Dict[str, Any],
    regex_fallback: Dict[str, Any],
) -> Dict[str, Any]:
    if isinstance(result.get("topic"), dict):
        result = result["topic"]
    out = {
        "summary": str(result.get("summary") or regex_fallback.get("summary", "")),
        "theory_notes": str(result.get("theory_notes") or regex_fallback.get("theory_notes", "")),
        "key_points": result.get("key_points") if isinstance(result.get("key_points"), list) else [],
    }
    if not out["key_points"]:
        out["key_points"] = regex_fallback.get("key_points", [])
    if not out["summary"] and out["theory_notes"]:
        out["summary"] = build_hierarchical_summary_from_theory_notes(out["theory_notes"])
    if not out["summary"] and out["theory_notes"]:
        out["summary"] = _truncate_text(out["theory_notes"].replace("\n", " "), 800)
    return out


def _normalize_llm_examples_response(
    result: Dict[str, Any],
    regex_fallback: Dict[str, Any],
) -> Dict[str, Any]:
    if isinstance(result.get("topic"), dict):
        result = result["topic"]
    out = {
        "case_studies": result.get("case_studies") if isinstance(result.get("case_studies"), list) else [],
        "examples": result.get("examples") if isinstance(result.get("examples"), list) else [],
        "practice_exercises": (
            result.get("practice_exercises")
            if isinstance(result.get("practice_exercises"), list)
            else []
        ),
    }
    if not out["case_studies"]:
        out["case_studies"] = regex_fallback.get("case_studies", [])
    if not out["examples"]:
        out["examples"] = regex_fallback.get("examples", [])
    if not out["practice_exercises"]:
        out["practice_exercises"] = regex_fallback.get("practice_exercises", [])
    out["examples"] = dedupe_examples_by_id(out["examples"])
    out["practice_exercises"] = out["practice_exercises"][:MAX_PRACTICE_EXERCISES]
    return out


def _call_llm_on_focused_markdown(
    client: OllamaClient,
    meta: TopicMeta,
    markdown_body: str,
    build_prompt: Any,
    normalize: Any,
    regex_fallback: Dict[str, Any],
    label: str,
) -> Dict[str, Any]:
    _, probe_user = build_prompt(meta, markdown_body)
    if len(probe_user) <= LLM_MAX_USER_CHARS:
        print(
            f"  Calling Ollama ({OLLAMA_MODEL}) — {label} single pass "
            f"({len(markdown_body):,} chars MD)..."
        )
        system, user = build_prompt(meta, markdown_body)
        raw = client.chat_json(system, user)
        return normalize(raw, regex_fallback)

    sections = split_markdown_by_h2_sections(markdown_body)
    print(
        f"  Topic {meta.topic_number} {label}: {len(markdown_body):,} chars "
        f"→ {len(sections)} section LLM calls"
    )
    merged_parts: List[Dict[str, Any]] = []
    for idx, (title, sec_md) in enumerate(sections, 1):
        print(f"    {label} section {idx}/{len(sections)}: {title[:70]}")
        system, user = build_prompt(meta, sec_md, section_title=title)
        try:
            raw = client.chat_json(system, user)
            merged_parts.append(normalize(raw, regex_fallback))
        except RuntimeError as exc:
            print(f"    Warning: {label} section LLM failed ({exc}), skipping.")
    if not merged_parts:
        print(f"  Warning: all {label} LLM calls failed; using regex fallback.")
        return regex_fallback
    if label == "theory":
        summary_blocks: List[str] = []
        key_points: List[Dict[str, str]] = []
        seen_kp: Set[str] = set()
        for idx, part in enumerate(merged_parts):
            sec_summary = str(part.get("summary") or "").strip()
            if not sec_summary:
                continue
            if sec_summary.startswith("##"):
                summary_blocks.append(sec_summary)
                continue
            title = sections[idx][0] if idx < len(sections) else f"Section {idx + 1}"
            heading = plain_section_title(title) or f"Section {idx + 1}"
            summary_blocks.append(f"## {heading}\n{sec_summary}")
        for part in merged_parts:
            for kp in part.get("key_points", []):
                text = kp.get("text", "") if isinstance(kp, dict) else str(kp)
                if text and text not in seen_kp:
                    seen_kp.add(text)
                    key_points.append({"text": text})
        theory_notes = "\n\n".join(
            p.get("theory_notes", "") for p in merged_parts if p.get("theory_notes")
        )
        merged_summary = compact_markdown("\n\n".join(summary_blocks))
        if not merged_summary and theory_notes:
            merged_summary = build_hierarchical_summary_from_theory_notes(theory_notes)
        return {
            "summary": merged_summary or regex_fallback.get("summary", ""),
            "theory_notes": theory_notes or regex_fallback.get("theory_notes", ""),
            "key_points": key_points[:20] or regex_fallback.get("key_points", []),
        }
    case_studies: List[Dict[str, Any]] = []
    examples: List[Dict[str, Any]] = []
    practice: List[Dict[str, Any]] = []
    seen_cs: Set[str] = set()
    seen_ex: Set[str] = set()
    seen_pe: Set[str] = set()
    for part in merged_parts:
        for cs in part.get("case_studies", []):
            cid = str(cs.get("id") or cs.get("title") or len(case_studies))
            if cid not in seen_cs:
                seen_cs.add(cid)
                case_studies.append(cs)
        for ex in part.get("examples", []):
            eid = str(ex.get("id") or ex.get("title") or len(examples))
            if eid not in seen_ex:
                seen_ex.add(eid)
                examples.append(ex)
        for pe in part.get("practice_exercises", []):
            pid = str(pe.get("id") or pe.get("question", "")[:80] or len(practice))
            if pid not in seen_pe:
                seen_pe.add(pid)
                practice.append(pe)
    return {
        "case_studies": case_studies or regex_fallback.get("case_studies", []),
        "examples": dedupe_examples_by_id(examples or regex_fallback.get("examples", [])),
        "practice_exercises": (practice or regex_fallback.get("practice_exercises", []))[
            :MAX_PRACTICE_EXERCISES
        ],
    }


def split_markdown_by_h2_sections(
    markdown: str,
    max_chars: int = LLM_MAX_USER_CHARS,
) -> List[Tuple[str, str]]:
    lines = markdown.splitlines()
    raw_sections: List[Tuple[str, List[str]]] = []
    current_title = "Introduction"
    current_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if H2_RE.match(stripped):
            if current_lines:
                raw_sections.append((current_title, current_lines))
            current_title = stripped.lstrip("#").strip() or current_title
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        raw_sections.append((current_title, current_lines))

    if not raw_sections:
        return [("Full topic", markdown)]

    batches: List[Tuple[str, str]] = []
    batch_title = ""
    batch_lines: List[str] = []
    batch_len = 0

    for title, sec_lines in raw_sections:
        sec_text = "\n".join(sec_lines)
        sec_len = len(sec_text)
        if batch_len + sec_len > max_chars and batch_lines:
            batches.append((batch_title, "\n".join(batch_lines)))
            batch_title = title
            batch_lines = list(sec_lines)
            batch_len = sec_len
        else:
            if not batch_title:
                batch_title = title
            elif title not in batch_title:
                batch_title = f"{batch_title}; {title}"
            batch_lines.extend(sec_lines)
            batch_len += sec_len + 1

    if batch_lines:
        batches.append((batch_title, "\n".join(batch_lines)))
    return batches


def _merge_section_llm_results(parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    summaries: List[str] = []
    key_points: List[Dict[str, str]] = []
    case_studies: List[Dict[str, Any]] = []
    examples: List[Dict[str, Any]] = []
    practice: List[Dict[str, Any]] = []
    seen_kp: Set[str] = set()
    seen_cs: Set[str] = set()
    seen_ex: Set[str] = set()
    seen_pe: Set[str] = set()

    for part in parts:
        if part.get("summary"):
            summaries.append(str(part["summary"]))
        for kp in part.get("key_points", []):
            text = kp.get("text", "") if isinstance(kp, dict) else str(kp)
            if text and text not in seen_kp:
                seen_kp.add(text)
                key_points.append({"text": text})
        for cs in part.get("case_studies", []):
            cid = str(cs.get("id") or cs.get("title") or len(case_studies))
            if cid not in seen_cs:
                seen_cs.add(cid)
                case_studies.append(cs)
        for ex in part.get("examples", []):
            eid = str(ex.get("id") or ex.get("title") or len(examples))
            if eid not in seen_ex:
                seen_ex.add(eid)
                examples.append(ex)
        for pe in part.get("practice_exercises", []):
            pid = str(pe.get("id") or pe.get("question", "")[:80] or len(practice))
            if pid not in seen_pe:
                seen_pe.add(pid)
                practice.append(pe)

    return {
        "summary": "\n\n".join(summaries[:4]) if summaries else "",
        "key_points": key_points[:12],
        "case_studies": case_studies,
        "examples": examples,
        "practice_exercises": practice[:MAX_PRACTICE_EXERCISES],
    }


def _call_llm_on_topic_markdown(
    client: OllamaClient,
    meta: TopicMeta,
    markdown_body: str,
    pre: Dict[str, Any],
) -> Dict[str, Any]:
    _, probe_user = _build_llm_prompt_from_markdown(meta, markdown_body)
    if len(probe_user) <= LLM_MAX_USER_CHARS:
        print(
            f"  Calling Ollama ({OLLAMA_MODEL}) — single pass "
            f"({len(markdown_body):,} chars MD)..."
        )
        system, user = _build_llm_prompt_from_markdown(meta, markdown_body)
        raw = client.chat_json(system, user)
        return _normalize_llm_response(raw, pre)

    sections = split_markdown_by_h2_sections(markdown_body)
    print(
        f"  Topic {meta.topic_number}: {len(markdown_body):,} chars "
        f"→ {len(sections)} section LLM calls"
    )
    parts: List[Dict[str, Any]] = []
    for idx, (title, sec_md) in enumerate(sections, 1):
        print(f"    Section {idx}/{len(sections)}: {title[:70]}")
        system, user = _build_llm_prompt_from_markdown(meta, sec_md, section_title=title)
        try:
            raw = client.chat_json(system, user)
            parts.append(_normalize_llm_response(raw, pre))
        except RuntimeError as exc:
            print(f"    Warning: section LLM failed ({exc}), skipping.")
    if parts:
        return _merge_section_llm_results(parts)
    raise RuntimeError("All section LLM calls failed")


def enrich_theory_from_markdown(
    theory_md_path: str,
    chunk: TopicChunk,
    pre: Dict[str, Any],
    skip_llm: bool = False,
) -> Dict[str, Any]:
    markdown_body = read_topic_markdown_body(theory_md_path)
    regex_result = build_structured_theory_from_md(markdown_body, pre)
    print(
        f"  Regex theory: {len(regex_result.get('theory_notes', '')):,} chars, "
        f"{len(regex_result.get('key_points', []))} key_points"
    )
    if skip_llm or not markdown_body.strip():
        return regex_result

    client = OllamaClient()
    try:
        client.ensure_model()
        return _call_llm_on_focused_markdown(
            client,
            chunk.meta,
            markdown_body,
            _build_llm_theory_prompt,
            _normalize_llm_theory_response,
            regex_result,
            "theory",
        )
    except RuntimeError as exc:
        print(f"  Warning: theory LLM failed ({exc}); using regex theory only.")
        return regex_result


def enrich_examples_from_markdown(
    examples_md_path: str,
    chunk: TopicChunk,
    pre: Dict[str, Any],
    skip_llm: bool = False,
) -> Dict[str, Any]:
    markdown_body = read_topic_markdown_body(examples_md_path)
    regex_result = build_structured_examples_from_md(markdown_body, pre)
    print(
        f"  Regex examples: {len(regex_result.get('examples', []))} examples, "
        f"{len(regex_result.get('case_studies', []))} case studies"
    )
    if skip_llm or not markdown_body.strip():
        return regex_result

    client = OllamaClient()
    try:
        client.ensure_model()
        return _call_llm_on_focused_markdown(
            client,
            chunk.meta,
            markdown_body,
            _build_llm_examples_prompt,
            _normalize_llm_examples_response,
            regex_result,
            "examples",
        )
    except RuntimeError as exc:
        print(f"  Warning: examples LLM failed ({exc}); using regex examples only.")
        return regex_result


def enrich_topic_from_markdown(
    topic_md_path: str,
    chunk: TopicChunk,
    pre: Dict[str, Any],
    json_path: str,
    skip_llm: bool = False,
    force_llm: bool = False,
    examples_md_path: Optional[str] = None,
) -> Dict[str, Any]:
    if os.path.exists(json_path) and not force_llm:
        try:
            with open(json_path, "r", encoding="utf-8") as handle:
                cached = json.load(handle)
            if cached.get("examples") and (
                cached.get("theory_sections") or cached.get("theory_notes")
            ):
                print(f"  Loading cached topic JSON: {json_path}")
                return cached
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  Warning: invalid topic JSON cache ({exc}), regenerating.")

    if examples_md_path:
        theory_part = enrich_theory_from_markdown(
            topic_md_path, chunk, pre, skip_llm=skip_llm
        )
        examples_part = enrich_examples_from_markdown(
            examples_md_path, chunk, pre, skip_llm=skip_llm
        )
        result = merge_topic_theory_and_examples(theory_part, examples_part, pre)
        print(
            f"  Merged topic: theory {len(result.get('theory_notes', '')):,} chars, "
            f"{len(result.get('examples', []))} examples"
        )
    else:
        markdown_body = read_topic_markdown_body(topic_md_path)
        result = build_structured_topic_from_md(markdown_body, pre)
        print(
            f"  Regex extract: theory {len(result.get('theory_notes', '')):,} chars, "
            f"{len(result.get('examples', []))} examples"
        )
        if not skip_llm:
            client = OllamaClient()
            try:
                client.ensure_model()
                if os.environ.get("LLM_SUMMARY", "0").lower() in ("1", "true", "yes"):
                    sections, _qb = split_theory_and_question_bank_markdown(
                        result.get("theory_notes", "") or ""
                    )
                    llm_summary = _llm_extract_hierarchical_summary(
                        client, chunk.meta, sections
                    )
                    if llm_summary:
                        result["summary"] = llm_summary
                        result["summary_source"] = "llm"
                print(f"  Calling Ollama ({OLLAMA_MODEL}) for key_points only...")
                llm_kps = _llm_extract_key_points(
                    client,
                    chunk.meta,
                    result.get("theory_notes", "") or result.get("summary", ""),
                )
                if llm_kps:
                    result["key_points"] = _merge_key_points(result["key_points"], llm_kps)
            except RuntimeError as exc:
                print(f"  Warning: key_points LLM failed ({exc}); using regex key points only.")

    if skip_images():
        result = sanitize_topic_text_fields(result)

    os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    print(f"  Saved topic JSON: {json_path} (LaTeX; MathML only in *_final.json)")
    return result


def _normalize_llm_response(result: Dict[str, Any], pre: Dict[str, Any]) -> Dict[str, Any]:
    expected_keys = {"summary", "key_points", "case_studies", "examples", "practice_exercises"}
    if expected_keys.issubset(result.keys()):
        return result

    if "topic" in result and isinstance(result["topic"], dict):
        return _normalize_llm_response(result["topic"], pre)

    doc = result.get("document") or result.get("data") or {}
    if isinstance(doc, dict):
        sections = doc.get("sections") or doc.get("topics") or []
        summaries = []
        key_points: List[Dict[str, str]] = []
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            heading = sec.get("heading") or sec.get("title") or ""
            summary = sec.get("summary") or ""
            if summary:
                if heading and not str(summary).lstrip().startswith("##"):
                    summaries.append(f"## {heading}\n{summary}")
                else:
                    summaries.append(summary)
            for item in sec.get("content") or sec.get("key_points") or []:
                if isinstance(item, dict) and item.get("text"):
                    key_points.append({"text": item["text"]})
                elif isinstance(item, str):
                    key_points.append({"text": item})
        if summaries or key_points:
            normalized = _fallback_topic_from_pre(pre)
            if summaries:
                normalized["summary"] = "\n\n".join(summaries[:4])
            if key_points:
                normalized["key_points"] = (key_points + normalized["key_points"])[:12]
            return normalized

    print("  Warning: LLM JSON did not match schema; using pre-extracted fallback.")
    return _fallback_topic_from_pre(pre)


def _fallback_topic_from_pre(pre: Dict[str, Any]) -> Dict[str, Any]:
    key_points = []
    for kp in pre.get("key_points_candidates", [])[:8]:
        body = kp.get("body", "")
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("-") or line.startswith("("):
                key_points.append({"text": line.lstrip("- ").strip()})
    if len(key_points) < 3 and pre.get("key_points_candidates"):
        key_points.append({"text": pre["key_points_candidates"][0].get("body", "")[:500]})

    case_studies = []
    for cs in pre.get("case_studies", []):
        case_studies.append({
            "id": cs.get("id", "case_study"),
            "title": cs.get("title", ""),
            "description": cs.get("body", "")[:2000],
            "questions": [],
            "images": [],
        })

    examples = []
    for ex in pre.get("examples", [])[:10]:
        examples.append({
            "id": ex.get("id", "example"),
            "title": ex.get("title", ""),
            "problem": ex.get("problem", ""),
            "solution": ex.get("solution", ""),
            "images": [],
        })

    practice = []
    for q in pre.get("practice_questions", [])[:MAX_PRACTICE_EXERCISES]:
        practice.append({
            "id": q.get("id", "ex"),
            "question": q.get("prompt", ""),
            "type": "short",
            "images": [],
        })

    preview = pre.get("theory_preview", "")
    summary = build_hierarchical_summary_from_theory_notes(preview)
    if not summary:
        summary_parts: List[str] = []
        for para in preview.split("\n\n"):
            para = para.strip()
            if not para or para.startswith("![]") or para.startswith("##"):
                continue
            if para.startswith("[image:"):
                continue
            summary_parts.append(para)
            if len(summary_parts) >= 3:
                break
        summary = "\n\n".join(summary_parts) if summary_parts else f"Topic: {pre.get('topic_name', '')}"

    return {
        "summary": summary,
        "key_points": key_points[:12] or [{"text": f"Study {pre.get('topic_name', '')} concepts."}],
        "case_studies": case_studies,
        "examples": examples,
        "practice_exercises": practice,
    }


def _postprocess_topic_enriched(
    chunk: TopicChunk,
    topic_md_path: str,
    enriched: Dict[str, Any],
    pre: Dict[str, Any],
    book_name: str,
    math: MathConverter,
    examples_md_path: Optional[str] = None,
    skip_llm: bool = False,
) -> Tuple[Dict[str, Any], List[str]]:
    for field in ("summary", "theory_notes", "key_points", "case_studies", "examples", "practice_exercises"):
        if field not in enriched:
            fb = _fallback_topic_from_pre(pre)
            enriched[field] = fb.get(field, [] if field not in ("summary", "theory_notes") else "")
    if not enriched.get("theory_notes"):
        enriched["theory_notes"] = enriched.get("summary", "")

    # MathML is applied only when merging into *_final.json (relabel_final_json_document).

    image_assets: Dict[str, Any] = {}
    if not skip_images():
        topic_body = read_topic_markdown_body(topic_md_path)
        if examples_md_path:
            topic_body = topic_body + "\n\n" + read_topic_markdown_body(examples_md_path)
        resolver = ImageResolver(book_name, chunk.topic_number)
        resolver.register_markdown(topic_body)

        for key in ("summary", "theory_notes"):
            if isinstance(enriched.get(key), str):
                enriched[key] = resolver.replace_urls_with_ids(enriched[key])
        for key in ("key_points", "case_studies", "examples", "practice_exercises"):
            if isinstance(enriched.get(key), list):
                for item in enriched[key]:
                    for sub in ("text", "description", "problem", "solution", "question", "title"):
                        if sub in item and isinstance(item[sub], str):
                            item[sub] = resolver.replace_urls_with_ids(item[sub])
                    if "questions" in item and isinstance(item["questions"], list):
                        item["questions"] = [
                            resolver.replace_urls_with_ids(q) if isinstance(q, str) else q
                            for q in item["questions"]
                        ]

        for cs in enriched.get("case_studies", []):
            cs["images"] = resolver.build_image_list(resolver.collect_referenced_ids(cs))
        for ex in enriched.get("examples", []):
            ex["images"] = resolver.build_image_list(resolver.collect_referenced_ids(ex))
        for pe in enriched.get("practice_exercises", []):
            pe["images"] = resolver.build_image_list(resolver.collect_referenced_ids(pe))

        image_assets = embed_base64_in_assets(resolver)

    theory_notes = enriched.get("theory_notes", enriched.get("summary", "")) or ""
    theory_sections, question_bank_md = split_theory_and_question_bank_markdown(theory_notes)
    example_buckets = split_examples_into_labeled_buckets(enriched.get("examples", []))

    topic_doc = {
        "topic_number": chunk.meta.topic_number,
        "topic_name": chunk.meta.topic_name,
        "page_range": chunk.meta.page_range,
        "summary": enriched.get("summary", ""),
        "summary_source": enriched.get("summary_source", ""),
        "theory_sections": theory_sections,
        "illustrations": example_buckets["illustrations"],
        "check_your_knowledge_items": example_buckets["check_your_knowledge"],
        "textbook_exercises": example_buckets["textbook_exercises"],
        "exercises": example_buckets["exercises"],
        "key_points": enriched.get("key_points", []),
        "case_studies": enriched.get("case_studies", []),
        "examples": enriched.get("examples", []),
        "practice_exercises": enriched.get("practice_exercises", []),
        "image_assets": image_assets,
        "source_topic_md": topic_md_path.replace("\\", "/"),
    }
    if examples_md_path:
        topic_doc["source_topic_examples_md"] = examples_md_path.replace("\\", "/")
    topic_doc = merge_question_bank_examples_into_topic(
        topic_doc, question_bank_md, book_slug=book_name
    )
    if not skip_images() and not image_assets:
        topic_doc = attach_topic_images_from_source(topic_doc, book_name)
    elif image_assets:
        topic_doc["image_assets"] = image_assets
    topic_doc = apply_labeled_topic_layout(topic_doc)

    leaks = MathConverter.scan_latex_leaks(topic_doc)
    return topic_doc, leaks


def parse_questions(raw_markdown: str) -> Dict[str, object]:
    instruction_lines: List[str] = []
    question_blocks: List[Dict[str, str]] = []
    current_question: Optional[Dict[str, str]] = None
    solution_lines: List[str] = []
    in_solution = False

    def flush_question() -> None:
        nonlocal current_question, solution_lines, in_solution
        if not current_question:
            return
        current_question["prompt"] = compact_markdown(current_question["prompt"])
        if solution_lines:
            current_question["solution"] = compact_markdown("\n".join(solution_lines))
        question_blocks.append(current_question)
        current_question = None
        solution_lines = []
        in_solution = False

    for line in raw_markdown.splitlines():
        stripped = line.strip()
        question_match = QUESTION_RE.match(stripped)

        if question_match and not in_solution:
            flush_question()
            current_question = {
                "question_number": question_match.group(1),
                "prompt": question_match.group(2).strip(),
            }
            continue

        if INLINE_SOL_RE.match(stripped) and current_question:
            in_solution = True
            continue

        if in_solution and current_question:
            solution_lines.append(line)
            continue

        if question_match and in_solution:
            flush_question()
            current_question = {
                "question_number": question_match.group(1),
                "prompt": question_match.group(2).strip(),
            }
            continue

        if current_question is None:
            instruction_lines.append(line)
        else:
            current_question["prompt"] += f"\n{line}"

    flush_question()

    instruction = compact_markdown("\n".join(instruction_lines))
    return {"instruction": instruction, "questions": question_blocks}


class TopicWiseExporter:
    def __init__(
        self,
        markdown_path: str,
        source_pdf_path: str,
        book_paths: BookPaths,
        topic_filter: Optional[List[int]] = None,
        skip_llm: bool = False,
        force_llm: bool = False,
        force_topics: bool = False,
    ):
        self.markdown_path = markdown_path
        self.source_pdf_path = source_pdf_path
        self.book_paths = book_paths
        self.output_path = book_paths.output_json
        self.book_name = book_paths.base_name
        self.topic_filter = topic_filter
        self.skip_llm = skip_llm
        self.force_llm = force_llm
        self.force_topics = force_topics
        self.raw_markdown = ""
        self.document: Dict[str, Any] = {}
        self.math = MathConverter()

    def load_markdown(self) -> bool:
        if not os.path.exists(self.markdown_path):
            print(f"Missing markdown cache: {self.markdown_path}")
            return False
        with open(self.markdown_path, "r", encoding="utf-8") as handle:
            self.raw_markdown = handle.read()
        return True

    def build_document(self) -> None:
        title = self.book_name
        for line in self.raw_markdown.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break

        print("=== Step 3/6: Write per-topic Markdown files ===")
        os.makedirs(self.book_paths.topics_json_dir, exist_ok=True)
        topic_entries = write_topic_markdown_files(
            self.raw_markdown,
            self.book_paths,
            self.markdown_path,
            self.topic_filter,
            self.force_topics,
        )

        print("=== Step 4-5/6: LLM enrichment per topic ===")
        topics_out: List[Dict[str, Any]] = []
        all_leaks: List[str] = []

        for chunk, topic_md_path, _examples_md in topic_entries:
            print(
                f"Processing topic {chunk.meta.topic_number}: {chunk.meta.topic_name} "
                f"(lines {chunk.start_line}-{chunk.end_line})"
            )
            pre = pre_extract_topic(chunk)
            json_path = topic_json_path(self.book_paths, chunk.meta.topic_number)
            enriched = enrich_topic_from_markdown(
                topic_md_path,
                chunk,
                pre,
                json_path,
                skip_llm=self.skip_llm,
                force_llm=self.force_llm,
            )
            topic_doc, leaks = _postprocess_topic_enriched(
                chunk,
                topic_md_path,
                enriched,
                pre,
                self.book_name,
                self.math,
                skip_llm=self.skip_llm,
            )
            if leaks:
                all_leaks.extend(
                    [f"topic_{chunk.meta.topic_number}:{p}" for p in leaks[:5]]
                )
            topics_out.append(topic_doc)

        print("=== Step 6/6: Merge topic JSONs into final document ===")
        if all_leaks and not skip_mathml():
            print(
                "  Note: LaTeX in per-topic cache is expected; "
                "MathML is applied in this merge step."
            )
        elif all_leaks:
            print(f"Warning: LaTeX delimiters remain in: {', '.join(all_leaks[:10])}")

        topics_out.sort(key=lambda t: t.get("topic_number", 0))
        if not skip_mathml():
            print("  MathML: converting LaTeX in merged *_final.json only")
        self.document = relabel_final_json_document({
            "metadata": {
                "name": title,
                "source_pdf": self.source_pdf_path,
                "source_markdown": self.markdown_path,
                "topics_md_dir": self.book_paths.topics_md_dir.replace("\\", "/"),
                "topics_json_dir": self.book_paths.topics_json_dir.replace("\\", "/"),
                "format_version": "3.1",
                "topic_count": len(topics_out),
                "llm_model": OLLAMA_MODEL if not self.skip_llm else "none",
                "ollama_base_url": OLLAMA_BASE_URL,
            },
            "topics": topics_out,
        })

    def save_json(self) -> None:
        os.makedirs(os.path.dirname(self.output_path) or ".", exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as handle:
            json.dump(self.document, handle, indent=2, ensure_ascii=False)
        print(f"Saved topic-wise JSON: {self.output_path}")
        print("=== Step 6/6: QA table JSON ===")
        save_qa_table_json_sidecar(
            self.document,
            self.book_name,
            self.book_paths.qa_table_output_json,
            source_final_path=self.output_path,
        )



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Topic-wise textbook extraction (format v3): PDF -> Mathpix MD -> topic JSON",
    )
    parser.add_argument("pdf_path", nargs="?", default=None, help="Path to source PDF")
    parser.add_argument("markdown_path", nargs="?", default=None, help="Path to Mathpix markdown cache")
    parser.add_argument(
        "--topics",
        default=None,
        help="Comma-separated topic numbers to process (e.g. 1,2,3)",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip Ollama; build topics from pre-extracted content only",
    )
    parser.add_argument(
        "--force-llm",
        action="store_true",
        help="Ignore cached per-topic JSON and re-call Ollama",
    )
    parser.add_argument(
        "--force-topics",
        action="store_true",
        help="Regenerate per-topic Markdown files from the Mathpix cache",
    )
    parser.add_argument(
        "--relabel-final",
        metavar="JSON_PATH",
        default=None,
        help="Reorganize an existing *_final.json into labelled sections (no LLM re-run)",
    )
    parser.add_argument(
        "--export-qa-table",
        metavar="JSON_PATH",
        default=None,
        help="Export *_qa_table.json from *_final.json",
    )
    parser.add_argument(
        "--export-tables",
        metavar="JSON_PATH",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--merge-final",
        action="store_true",
        help="Rebuild *_final.json from cached topics_json/ (use --summarize-llm --with-images to enrich)",
    )
    parser.add_argument(
        "--summarize-llm",
        action="store_true",
        help="Generate student-friendly topic summaries with Ollama (revision notes per heading)",
    )
    parser.add_argument(
        "--force-summarize",
        action="store_true",
        help="Replace existing summaries (including regex excerpts) with new student LLM summaries",
    )
    parser.add_argument(
        "--summarize-only",
        metavar="JSON_PATH",
        default=None,
        help="Regenerate student summaries in an existing *_final.json (use with --topics)",
    )
    parser.add_argument(
        "--with-images",
        action="store_true",
        help="Download Mathpix figures/tables as base64 in JSON and theory_sections",
    )
    parser.add_argument(
        "--attach-images-only",
        metavar="JSON_PATH",
        default=None,
        help="Attach Mathpix figures/tables to existing *_final.json (implies --with-images)",
    )
    parser.add_argument(
        "--fix-mathml",
        metavar="JSON_PATH",
        default=None,
        help="Convert remaining $...$ LaTeX to readable plain text in an existing *_final.json",
    )
    parser.add_argument(
        "--math-to-plain",
        metavar="JSON_PATH",
        default=None,
        help="Replace MathML/LaTeX with readable plain text in an existing *_final.json",
    )
    parser.add_argument(
        "--skip-mathml",
        action="store_true",
        help="Do not convert LaTeX ($...$, $$...$$) to MathML in merge/export",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.with_images:
        os.environ["SKIP_IMAGES"] = "0"
    else:
        os.environ["SKIP_IMAGES"] = "1"

    if args.skip_llm:
        os.environ["SKIP_LLM"] = "1"
    else:
        os.environ["SKIP_LLM"] = "0"

    if getattr(args, "summarize_llm", False) or getattr(args, "summarize_only", None):
        os.environ["LLM_SUMMARY"] = "1"
    elif os.environ.get("LLM_SUMMARY") is None:
        os.environ["LLM_SUMMARY"] = "0"

    if getattr(args, "force_summarize", False) or getattr(args, "summarize_only", None):
        os.environ["FORCE_SUMMARY"] = "1"
    elif os.environ.get("FORCE_SUMMARY") is None:
        os.environ["FORCE_SUMMARY"] = "0"

    if getattr(args, "skip_mathml", False):
        os.environ["SKIP_MATHML"] = "1"
    elif os.environ.get("SKIP_MATHML") is None:
        os.environ["SKIP_MATHML"] = "0"

    if getattr(args, "math_to_plain", None):
        json_path = args.math_to_plain
        if not os.path.exists(json_path):
            print(f"File not found: {json_path}")
            raise SystemExit(1)
        print("=== Convert MathML/LaTeX to readable plain text ===")
        with open(json_path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
        document = fix_math_plain_in_document(document)
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
        print(f"Saved: {json_path}")
        return

    if getattr(args, "fix_mathml", None):
        json_path = args.fix_mathml
        if not os.path.exists(json_path):
            print(f"File not found: {json_path}")
            raise SystemExit(1)
        os.environ["SKIP_MATHML"] = "0"
        print("=== Convert LaTeX to readable plain text in final JSON ===")
        with open(json_path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
        document = fix_mathml_in_document(document)
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
        print(f"Saved: {json_path}")
        return

    if getattr(args, "attach_images_only", None):
        json_path = args.attach_images_only
        if not os.path.exists(json_path):
            print(f"File not found: {json_path}")
            raise SystemExit(1)
        os.environ["SKIP_IMAGES"] = "0"
        topic_filter = parse_topic_number_filter(args.topics)
        print("=== Attach Mathpix images + concept maps to final JSON ===")
        with open(json_path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
        topics_in = document.get("topics") or []
        topics_out: List[Dict[str, Any]] = []
        for topic in topics_in:
            if not isinstance(topic, dict):
                continue
            tn = int(topic.get("topic_number") or 0)
            if topic_filter and tn not in topic_filter:
                topics_out.append(topic)
                continue
            book_name = str((document.get("metadata") or {}).get("name") or "")
            topics_out.append(attach_topic_images_from_source(dict(topic), book_name))
        document = dict(document)
        document["topics"] = topics_out
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
        print(f"Saved: {json_path}")
        book_slug = os.path.basename(json_path).replace("_final.json", "")
        save_qa_table_json_sidecar(
            document,
            book_slug,
            qa_table_json_path_from_final(json_path),
            source_final_path=json_path,
        )
        print("Re-load into MySQL with: python insert_qa_table.py <book>_qa_table.json")
        return

    if getattr(args, "summarize_only", None):
        json_path = args.summarize_only
        if not os.path.exists(json_path):
            print(f"File not found: {json_path}")
            raise SystemExit(1)
        topic_filter = parse_topic_number_filter(args.topics)
        print(f"=== Student summaries (Ollama {OLLAMA_MODEL}) ===")
        if topic_filter:
            print(f"  Topics filter: {sorted(topic_filter)}")
        with open(json_path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
        document = regenerate_student_summaries_in_document(
            document, topic_filter=topic_filter
        )
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
        print(f"Saved: {json_path}")
        book_slug = os.path.basename(json_path).replace("_final.json", "")
        save_qa_table_json_sidecar(
            document,
            book_slug,
            qa_table_json_path_from_final(json_path),
            source_final_path=json_path,
        )
        print("Re-load into MySQL with: python insert_qa_table.py <book>_qa_table.json")
        return

    if args.relabel_final:
        json_path = args.relabel_final
        if not os.path.exists(json_path):
            print(f"File not found: {json_path}")
            raise SystemExit(1)
        print(f"Relabelling final JSON: {json_path}")
        with open(json_path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
        document = relabel_final_json_document(document)
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
        book_slug = os.path.basename(json_path).replace("_final.json", "")
        save_qa_table_json_sidecar(
            document,
            book_slug,
            qa_table_json_path_from_final(json_path),
            source_final_path=json_path,
        )
        t0 = (document.get("topics") or [{}])[0]
        print(
            f"Done. Topic 1: {len(t0.get('theory_sections', []))} theory sections, "
            f"{len(t0.get('illustrations', []))} illustrations, "
            f"{len(t0.get('textbook_exercises', []))} textbook exercises."
        )
        return

    export_qa_path = args.export_qa_table or args.export_tables
    if export_qa_path:
        json_path = export_qa_path
        if not os.path.exists(json_path):
            print(f"File not found: {json_path}")
            raise SystemExit(1)
        with open(json_path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
        book_slug = os.path.basename(json_path).replace("_final.json", "").replace("_qa_table.json", "")
        out_path = qa_table_json_path_from_final(json_path)
        save_qa_table_json_sidecar(document, book_slug, out_path, source_final_path=json_path)
        return

    pdf_path = args.pdf_path or os.environ.get("PDF_PATH") or DEFAULT_PDF_PATH
    book_paths = derive_book_paths(pdf_path)

    if skip_images() and not args.with_images:
        print("  Images: skipped (use --with-images to download/embed)")

    if args.merge_final:
        print("=== Merge final JSON from cached topics_json/ ===")
        if os.environ.get("LLM_SUMMARY", "0").lower() in ("1", "true", "yes"):
            print(f"  Summaries: student revision notes via Ollama ({OLLAMA_MODEL})")
        if args.merge_final and os.environ.get("FORCE_SUMMARY", "0").lower() in ("1", "true", "yes"):
            print("  Summaries: force replace existing")
        if not skip_mathml():
            print("  MathML: converting LaTeX in theory, exercises, key points, …")
        else:
            print("  MathML: skipped (--skip-mathml)")
        cached_md = find_existing_markdown_cache(book_paths.base_name) or book_paths.mathpix_md
        document = merge_final_from_cached_topics(
            book_paths,
            source_pdf=pdf_path if os.path.exists(pdf_path) else "",
            source_markdown=cached_md,
        )
        os.makedirs(os.path.dirname(book_paths.output_json) or ".", exist_ok=True)
        with open(book_paths.output_json, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
        print(f"Saved: {book_paths.output_json}")
        print("=== Step 6/6: QA table JSON ===")
        save_qa_table_json_sidecar(
            document,
            book_paths.base_name,
            book_paths.qa_table_output_json,
            source_final_path=book_paths.output_json,
        )
        return

    cache_path = book_paths.mathpix_md

    print("=== Step 1/6: Resolve PDF ===")
    explicit_md_path = (
        args.markdown_path
        or os.environ.get("MARKDOWN_PATH")
        or ""
    )
    cached_md = (
        explicit_md_path
        if explicit_md_path and os.path.exists(explicit_md_path)
        else find_existing_markdown_cache(book_paths.base_name)
    )

    if not os.path.exists(pdf_path):
        if cached_md:
            print(f"  PDF not found (continuing with Markdown cache): {pdf_path}")
        else:
            print(f"PDF not found: {pdf_path}")
            raise SystemExit(1)
    else:
        print(f"  PDF: {pdf_path}")

    if explicit_md_path and os.path.exists(explicit_md_path):
        cache_path = explicit_md_path
        print(f"Using provided Markdown: {cache_path}")
    elif cached_md:
        cache_path = cached_md
        print(f"Found existing Markdown cache: {cache_path}")
    else:
        print("=== Step 2/6: Mathpix Markdown ===")
        if not ensure_mathpix_markdown(pdf_path, cache_path):
            raise SystemExit(1)

    if os.path.exists(cache_path) and not explicit_md_path:
        print("=== Step 2/6: Mathpix Markdown (cached) ===")
        print(f"  Using: {cache_path}")

    topic_filter: Optional[List[int]] = None
    if args.topics:
        topic_filter = [int(t.strip()) for t in args.topics.split(",") if t.strip()]

    exporter = TopicWiseExporter(
        cache_path,
        pdf_path,
        book_paths,
        topic_filter=topic_filter,
        skip_llm=args.skip_llm,
        force_llm=args.force_llm,
        force_topics=args.force_topics,
    )
    if exporter.load_markdown():
        exporter.build_document()
        exporter.save_json()


if __name__ == "__main__":
    main()
