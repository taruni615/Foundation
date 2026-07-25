#!/usr/bin/env python3
"""Thin workflow orchestrator coordinating pipeline stages via RepositoryService.

Conceptual Flow:
    Materials -> Extraction -> *_final.json -> Repository -> Generators (Notes / MCQs) -> Persistence -> Web / Assessment
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from edu_pipeline.extraction.pipeline import main as run_extraction_pipeline
from edu_pipeline.extraction.topic_extractor import main as run_topic_extractor
from edu_pipeline.generators.notes.generator import generate_short_notes, main as run_notes_generator
from edu_pipeline.generators.questions.mcq_generator import convert_repository_questions, main as run_mcq_generator
from edu_pipeline.repository import BookRepository, RepositoryService
from edu_pipeline.storage.export_qa import build_qa_table_export, main as run_export_qa
from edu_pipeline.storage.store_questions import insert_qa_table, main as run_store_questions

__all__ = [
    "run_extraction_pipeline",
    "run_topic_extractor",
    "run_notes_generator",
    "run_mcq_generator",
    "run_export_qa",
    "run_store_questions",
    "build_qa_table_export",
    "insert_qa_table",
    "generate_short_notes",
    "convert_repository_questions",
    "execute_workflow",
]


def execute_workflow(
    pdf_path_or_slug: str,
    *,
    generate_notes: bool = False,
    store_db: bool = False,
) -> BookRepository:
    """Coordinate pipeline execution through clean stage delegation.

    1. Run extraction pipeline (produces *_final.json).
    2. Load output into BookRepository via RepositoryService.
    3. Run derivative generators on BookRepository if requested.
    4. Persist to storage if requested.
    """
    # Stage 1: Extraction (produces canonical *_final.json)
    if pdf_path_or_slug.endswith(".pdf"):
        run_topic_extractor([pdf_path_or_slug])

    # Stage 2: Load into canonical BookRepository wrapper
    repo = RepositoryService.load(pdf_path_or_slug)

    # Stage 3: Generators (optional notes)
    if generate_notes:
        generate_short_notes(repo)

    # Stage 4: Storage Persistence (optional DB load)
    if store_db:
        qa_data = build_qa_table_export(repo.raw_json)
        insert_qa_table(qa_data)

    return repo
