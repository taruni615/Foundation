#!/usr/bin/env python3
"""Workflow orchestrator coordinating two decoupled pipeline stages.

1. Ingestion Pipeline:
   PDF -> Mathpix OCR -> Topic Extractor -> *_final.json -> MySQL Load -> Metadata Tagging

2. Generation Pipeline:
   MySQL / Repository -> Theory-to-MCQ Conversion -> MCQ Similarity -> Short Revision Notes
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from edu_pipeline.extraction.pipeline import main as run_extraction_pipeline
from edu_pipeline.extraction.topic_extractor import main as run_topic_extractor
from edu_pipeline.generators.notes.generator import generate_short_notes, main as run_notes_generator
from edu_pipeline.generators.questions import mcq_generator, similarity
from edu_pipeline.generators.questions.mcq_generator import convert_repository_questions, main as run_mcq_generator
from edu_pipeline.repository import BookRepository, RepositoryService
from edu_pipeline.storage import db_repository, tagging
from edu_pipeline.storage.export_qa import build_qa_table_export, main as run_export_qa
from edu_pipeline.storage.store_questions import insert_qa_table, insert_repository, main as run_store_questions

logger = logging.getLogger(__name__)

__all__ = [
    "run_extraction_pipeline",
    "run_topic_extractor",
    "run_notes_generator",
    "run_mcq_generator",
    "run_export_qa",
    "run_store_questions",
    "build_qa_table_export",
    "insert_qa_table",
    "insert_repository",
    "generate_short_notes",
    "convert_repository_questions",
    "execute_workflow",
    "run_ingestion_pipeline",
    "run_generation_pipeline",
]


def run_ingestion_pipeline(
    pdf_path_or_slug: str,
    *,
    extract_mode: str = "all",
    store_db: bool = True,
    tag_questions: bool = True,
    with_images: bool = True,
    replace_book: bool = False,
) -> Dict[str, Any]:
    """Execute Pipeline 1: Extraction & Ingestion.

    PDF -> OCR / Topic Extractor -> JSON -> MySQL Storage -> Question Tagging

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

    # Step 1: Extraction (produces canonical *_final.json)
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

    # Step 3: MySQL Ingestion
    if store_db:
        qa_data = build_qa_table_export(repo.raw_json)
        insert_stats = insert_qa_table(qa_data, replace_book=replace_book)
        results["db_stored"] = True
        results["insert_stats"] = insert_stats

        # Step 4: Metadata Tagging (skip if theory-only, as theory carries no questions)
        if tag_questions and extract_mode != "theory_only":
            tag_stats = tagging.backfill(book_slug=repo.metadata.book_slug, only_untagged=not replace_book)
            results["tagged"] = True
            results["tag_stats"] = tag_stats

    return results


def run_generation_pipeline(
    book_slug_or_name: str,
    *,
    modes: Optional[List[str]] = None,
    mcq_limit: int = 20,
    similar_limit: int = 20,
    out_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute Pipeline 2: Generation & Conversion.

    MySQL / BookRepository -> MCQ Conversion -> MCQ Similarity -> Short Notes
    No PDF or OCR required.
    """
    modes = modes or ["convert_mcqs", "similar_mcqs", "notes"]
    results: Dict[str, Any] = {"book_slug": book_slug_or_name, "outputs": {}}

    resolved_slug = db_repository.resolve_book(book_slug_or_name) or book_slug_or_name

    # Mode A: Short Revision Notes Generation
    if "notes" in modes:
        repo = db_repository.load_book(resolved_slug, output_root=out_dir)
        notes_written = generate_short_notes(repo)
        results["outputs"]["notes"] = {"written_count": len(notes_written), "paths": notes_written}

    # Mode B: Convert open-ended theory to MCQs
    if "convert_mcqs" in modes:
        try:
            filters = {"book": [resolved_slug]}
            candidates = mcq_generator._iter_theory_bank_items(filters, mcq_limit)
            if candidates:
                items = []
                for c in candidates:
                    items.append({
                        "id": c["id"],
                        "question": c.get("stem", ""),
                        "answer": c.get("answer", ""),
                        "subject": c.get("subject", ""),
                        "chapter_name": c.get("chapter_name", ""),
                        "question_type": c.get("question_type", ""),
                    })
                converted = mcq_generator.convert_items(items)
                results["outputs"]["convert_mcqs"] = converted
        except Exception as exc:
            logger.warning("Convert MCQs failed: %s", exc)
            results["outputs"]["convert_mcqs"] = {"error": str(exc)}

    # Mode C: Generate similar MCQs
    if "similar_mcqs" in modes:
        try:
            filters = {"book": [resolved_slug], "type": ["MCQ"]}
            sources = similarity._fetch_source_mcqs(filters, similar_limit)
            if sources:
                sim_result = similarity.generate_from_sources(sources, per_item=2)
                results["outputs"]["similar_mcqs"] = sim_result
        except Exception as exc:
            logger.warning("Similar MCQs failed: %s", exc)
            results["outputs"]["similar_mcqs"] = {"error": str(exc)}

    return results


def execute_workflow(
    pdf_path_or_slug: str,
    *,
    generate_notes: bool = False,
    store_db: bool = False,
) -> BookRepository:
    """Coordinate pipeline execution through clean stage delegation (legacy wrapper)."""
    ingest_res = run_ingestion_pipeline(pdf_path_or_slug, store_db=store_db, tag_questions=store_db)
    repo = ingest_res["repo"]

    if generate_notes:
        generate_short_notes(repo)

    return repo

