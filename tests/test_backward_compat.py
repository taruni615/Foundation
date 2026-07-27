"""Backward-compatibility contract.

The root *.py files are the documented CLI entry points and the public import
surface. Three cleanup levels have moved code beneath them; these tests pin the
guarantees that must survive any future refactor.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

WRAPPERS = [
    "app_server", "topicwise_pipeline", "viewer_api", "assessment_store", "bank_read",
    "final_to_qa_table", "insert_qa_table", "mcq_generator", "mcq_similar",
    "question_type_classifier", "refresh_qa_question_types", "short_notes_pipeline",
    "textbook_extract_pipeline",
]

CLI_HELP = [
    "textbook_extract_pipeline.py", "topicwise_pipeline.py", "mcq_generator.py",
    "mcq_similar.py", "final_to_qa_table.py", "insert_qa_table.py",
    "question_type_classifier.py", "refresh_qa_question_types.py",
]


@pytest.mark.parametrize("name", WRAPPERS)
def test_every_wrapper_still_imports(name):
    assert importlib.import_module(name) is not None


@pytest.mark.parametrize("script", CLI_HELP)
def test_every_cli_responds_to_help(script):
    result = subprocess.run(
        [sys.executable, script, "--help"], cwd=str(PROJECT_ROOT),
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-800:]
    assert "usage" in result.stdout.lower()


def test_short_notes_cli_lists_books():
    result = subprocess.run(
        [sys.executable, "short_notes_pipeline.py", "--list"], cwd=str(PROJECT_ROOT),
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-800:]


class TestReExportedNames:
    """Constants moved into shared/ must stay reachable from their old homes."""

    @pytest.mark.parametrize("name", [
        "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME",
        "OUTPUT_DIR", "MATHPIX_CACHE_DIR",
    ])
    def test_topicwise_pipeline_still_exports(self, name):
        assert hasattr(importlib.import_module("topicwise_pipeline"), name)

    def test_bank_read_still_exposes_its_query_helpers(self):
        bank_read = importlib.import_module("bank_read")
        for name in ("derive_attributes", "estimate_difficulty", "search_items"):
            assert hasattr(bank_read, name)

    def test_wrapper_and_package_share_one_implementation(self):
        import bank_read

        from edu_pipeline.storage import database
        assert bank_read.derive_attributes is database.derive_attributes


class TestPublicApiSurface:
    def test_ai_package_exports_the_documented_services(self):
        import edu_pipeline.ai as ai

        for name in ("AIService", "MCQService", "NotesService", "KnowledgeEnrichmentService",
                     "ModelManager", "PromptService", "ProviderRegistry", "LLMResponse"):
            assert hasattr(ai, name), name

    def test_repository_package_exports_its_types(self):
        import edu_pipeline.repository as repo

        assert hasattr(repo, "BookRepository") and hasattr(repo, "RepositoryService")

    def test_workflow_orchestrator_surface_is_intact(self):
        import edu_pipeline.workflow as wf

        for name in ("execute_workflow", "build_qa_table_export", "insert_qa_table",
                     "generate_short_notes"):
            assert name in wf.__all__

    def test_legacy_enrichment_function_is_still_public(self):
        """The class wrapper added in Level 3 must not displace the function."""
        from edu_pipeline.ai.services import enrich_topic_analysis

        assert callable(enrich_topic_analysis)


class TestNoInternalDependencyOnWrappers:
    def test_package_never_imports_its_own_compatibility_shims(self):
        """Wrappers are for CLI users; importing them from inside inverts the
        dependency and only works when the repo root is on sys.path."""
        offenders = []
        for path in (PROJECT_ROOT / "edu_pipeline").rglob("*.py"):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                for wrapper in WRAPPERS:
                    if stripped.startswith((f"import {wrapper}", f"from {wrapper} import")):
                        offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {stripped}")
        assert not offenders, "package imports its own wrappers:\n" + "\n".join(offenders)
