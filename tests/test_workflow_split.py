"""Tests for split workflow orchestrators: Ingestion Pipeline and Generation Pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from edu_pipeline.workflow import run_generation_pipeline, run_ingestion_pipeline


def test_run_ingestion_pipeline_structure():
    mock_repo = MagicMock()
    mock_repo.metadata.book_slug = "10 PHYSICS FOUNDATION"
    mock_repo.raw_json = {"topics": []}

    with patch("edu_pipeline.workflow.run_topic_extractor") as mock_extractor, \
         patch("edu_pipeline.workflow.RepositoryService.load", return_value=mock_repo), \
         patch("edu_pipeline.workflow.build_qa_table_export", return_value={"topics": [], "rows": []}), \
         patch("edu_pipeline.workflow.insert_qa_table", return_value={"chapters": 1}) as mock_insert, \
         patch("edu_pipeline.workflow.tagging.backfill", return_value={"chapters": 1}) as mock_tag:

        res = run_ingestion_pipeline("test.pdf", store_db=True, tag_questions=True)

        assert mock_extractor.called
        assert res["book_slug"] == "10 PHYSICS FOUNDATION"
        assert res["db_stored"] is True
        assert res["tagged"] is True
        assert mock_insert.called
        assert mock_tag.called


def test_run_ingestion_pipeline_extract_modes():
    mock_repo = MagicMock()
    mock_repo.metadata.book_slug = "10 PHYSICS FOUNDATION"
    mock_repo.raw_json = {"topics": []}

    with patch("edu_pipeline.workflow.run_topic_extractor") as mock_extractor, \
         patch("edu_pipeline.workflow.RepositoryService.load", return_value=mock_repo), \
         patch("edu_pipeline.workflow.build_qa_table_export", return_value={"topics": [], "rows": []}), \
         patch("edu_pipeline.workflow.insert_qa_table", return_value={"chapters": 1}), \
         patch("edu_pipeline.workflow.tagging.backfill", return_value={"chapters": 1}) as mock_tag:

        res_theory = run_ingestion_pipeline("test.pdf", extract_mode="theory_only")
        assert res_theory["extract_mode"] == "theory_only"
        mock_extractor.assert_called_with(["test.pdf", "--with-images", "--theory-only"])
        assert not mock_tag.called

        res_questions = run_ingestion_pipeline("test.pdf", extract_mode="questions_only")
        assert res_questions["extract_mode"] == "questions_only"
        mock_extractor.assert_called_with(["test.pdf", "--with-images", "--questions-only"])
        assert mock_tag.called


def test_run_generation_pipeline_modes():
    mock_repo = MagicMock()

    with patch("edu_pipeline.workflow.db_repository.resolve_book", return_value="10 PHYSICS FOUNDATION"), \
         patch("edu_pipeline.workflow.db_repository.load_book", return_value=mock_repo), \
         patch("edu_pipeline.workflow.generate_short_notes", return_value=["note1.pdf"]) as mock_notes, \
         patch("edu_pipeline.workflow.mcq_generator._iter_theory_bank_items", return_value=[]), \
         patch("edu_pipeline.workflow.similarity._fetch_source_mcqs", return_value=[]):

        res = run_generation_pipeline("10 PHYSICS FOUNDATION", modes=["notes"])

        assert res["book_slug"] == "10 PHYSICS FOUNDATION"
        assert "notes" in res["outputs"]
        assert res["outputs"]["notes"]["written_count"] == 1
        assert mock_notes.called
