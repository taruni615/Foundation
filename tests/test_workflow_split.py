"""Tests for workflow orchestrator: extraction pipeline and QA export."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from edu_pipeline.workflow import execute_workflow, run_ingestion_pipeline


def test_run_ingestion_pipeline_structure():
    mock_repo = MagicMock()
    mock_repo.metadata.book_slug = "10 PHYSICS FOUNDATION"
    mock_repo.raw_json = {"topics": []}

    with patch("edu_pipeline.workflow.run_topic_extractor") as mock_extractor, \
         patch("edu_pipeline.workflow.RepositoryService.load", return_value=mock_repo), \
         patch("edu_pipeline.workflow.build_qa_table_export", return_value={"topics": [], "rows": []}) as mock_qa:

        res = run_ingestion_pipeline("test.pdf")

        assert mock_extractor.called
        assert res["book_slug"] == "10 PHYSICS FOUNDATION"
        assert "qa_table" in res
        assert mock_qa.called


def test_run_ingestion_pipeline_extract_modes():
    mock_repo = MagicMock()
    mock_repo.metadata.book_slug = "10 PHYSICS FOUNDATION"
    mock_repo.raw_json = {"topics": []}

    with patch("edu_pipeline.workflow.run_topic_extractor") as mock_extractor, \
         patch("edu_pipeline.workflow.RepositoryService.load", return_value=mock_repo), \
         patch("edu_pipeline.workflow.build_qa_table_export", return_value={"topics": [], "rows": []}):

        res_theory = run_ingestion_pipeline("test.pdf", extract_mode="theory_only")
        assert res_theory["extract_mode"] == "theory_only"
        mock_extractor.assert_called_with(["test.pdf", "--with-images", "--theory-only"])

        res_questions = run_ingestion_pipeline("test.pdf", extract_mode="questions_only")
        assert res_questions["extract_mode"] == "questions_only"
        mock_extractor.assert_called_with(["test.pdf", "--with-images", "--questions-only"])


def test_execute_workflow():
    mock_repo = MagicMock()
    mock_repo.metadata.book_slug = "10 PHYSICS FOUNDATION"
    mock_repo.raw_json = {"topics": []}

    with patch("edu_pipeline.workflow.run_topic_extractor"), \
         patch("edu_pipeline.workflow.RepositoryService.load", return_value=mock_repo), \
         patch("edu_pipeline.workflow.build_qa_table_export", return_value={"topics": [], "rows": []}):

        repo = execute_workflow("test.pdf")
        assert repo is mock_repo
