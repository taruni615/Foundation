#!/usr/bin/env python3
"""Workflow orchestrator for input extraction and structured output generation.

Pipeline:
    PDF -> Mathpix OCR -> Topic Extractor -> *_final.json -> Sidecars & Structured QA Export
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from edu_pipeline.extraction.pipeline import main as run_extraction_pipeline
from edu_pipeline.extraction.topic_extractor import main as run_topic_extractor
from edu_pipeline.repository import BookRepository, RepositoryService
from edu_pipeline.export import (
    build_qa_table_export,
    build_structured_questions_json,
    build_structured_theory_json,
    main as run_export_qa,
)

logger = logging.getLogger(__name__)

__all__ = [
    "run_extraction_pipeline",
    "run_topic_extractor",
    "run_export_qa",
    "build_qa_table_export",
    "build_structured_questions_json",
    "build_structured_theory_json",
    "execute_workflow",
    "run_ingestion_pipeline",
]


def run_ingestion_pipeline(
    pdf_path_or_slug: str,
    *,
    extract_mode: str = "all",
    with_images: bool = True,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Execute Extraction Pipeline: PDF -> OCR / Topic Extractor -> JSON -> Structured Output Exports.

    extract_mode options:
        - "all"            : Extract theory notes + questions + QA table (default)
        - "theory_only"    : Extract theory notes, summaries, key points, and image figures
        - "questions_only" : Extract questions, exercises, solutions, and QA table only
    """
    results: Dict[str, Any] = {
        "pdf_or_slug": pdf_path_or_slug,
        "extract_mode": extract_mode,
        "db_stored": False,
        "tagged": False,
    }

    # Step 1: Extraction (produces canonical *_final.json and sidecars)
    if pdf_path_or_slug.endswith(".pdf"):
        extractor_args = [pdf_path_or_slug]
        if with_images:
            extractor_args.append("--with-images")
        if extract_mode == "theory_only":
            extractor_args.append("--theory-only")
        elif extract_mode == "questions_only":
            extractor_args.append("--questions-only")

        run_topic_extractor(extractor_args)

    # Step 2: Load into canonical BookRepository
    repo = RepositoryService.load(pdf_path_or_slug)
    results["repo"] = repo
    results["book_slug"] = repo.metadata.book_slug

    # Step 3: Export QA table
    qa_data = build_qa_table_export(repo.raw_json)
    results["qa_table"] = qa_data

    return results


def execute_workflow(
    pdf_path_or_slug: str,
    **kwargs: Any,
) -> BookRepository:
    """Coordinate extraction pipeline execution through clean stage delegation."""
    ingest_res = run_ingestion_pipeline(pdf_path_or_slug, **kwargs)
    return ingest_res["repo"]
