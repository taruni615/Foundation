"""Compatibility shim: classifier logic has moved to edu_pipeline.extraction.question_bank."""

from edu_pipeline.extraction.question_bank import (
    QUESTION_TYPES,
    SECTION_DEFAULT_TYPE,
    classify_question,
    parse_correct_index,
    parse_options,
)

__all__ = [
    "QUESTION_TYPES",
    "SECTION_DEFAULT_TYPE",
    "classify_question",
    "parse_options",
    "parse_correct_index",
]
