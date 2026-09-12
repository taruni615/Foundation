"""Backward-compatibility contract for input extraction and output.

The root / scripts/*.py files are the documented CLI entry points and the public import
surface for extraction, viewers, and sidecar exports.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Extraction and viewer entry points in scripts/
WRAPPERS = [
    "app_server",
    "topicwise_pipeline",
    "viewer_api",
    "textbook_extract_pipeline",
    "run_ingestion_pipeline",
    "batch_extract_no_ollama",
    "build_standalone_viewer",
    "check_extraction_quality",
    "pack_offline_json",
    "rebuild_sidecars",
]

CLI_HELP = [
    "textbook_extract_pipeline.py",
    "topicwise_pipeline.py",
    "run_ingestion_pipeline.py",
    "batch_extract_no_ollama.py",
    "build_standalone_viewer.py",
    "check_extraction_quality.py",
    "pack_offline_json.py",
    "rebuild_sidecars.py",
]


@pytest.mark.parametrize("name", WRAPPERS)
def test_every_entry_point_exists_in_scripts(name):
    assert (PROJECT_ROOT / "scripts" / f"{name}.py").is_file()


@pytest.mark.parametrize("script", CLI_HELP)
def test_every_cli_responds_to_help(script):
    result = subprocess.run(
        [sys.executable, f"scripts/{script}", "--help"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-800:]
    assert "usage" in result.stdout.lower()


class TestReExportedNames:
    """Constants moved into shared/ must stay reachable from their old homes."""

    @pytest.mark.parametrize("name", [
        "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME",
        "OUTPUT_DIR", "MATHPIX_CACHE_DIR",
    ])
    def test_extraction_module_still_exports_moved_constants(self, name):
        assert hasattr(importlib.import_module("edu_pipeline.extraction.topic_extractor"), name)

    def test_storage_still_exposes_its_helpers(self):
        export_qa = importlib.import_module("edu_pipeline.storage.export_qa")
        for name in ("derive_attributes", "build_qa_table_export", "build_structured_questions_json"):
            assert hasattr(export_qa, name)


class TestPublicApiSurface:
    def test_repository_package_exports_its_types(self):
        import edu_pipeline.repository as repo

        assert hasattr(repo, "BookRepository") and hasattr(repo, "RepositoryService")

    def test_workflow_orchestrator_surface_is_intact(self):
        import edu_pipeline.workflow as wf

        for name in ("execute_workflow", "build_qa_table_export", "run_ingestion_pipeline",
                     "run_extraction_pipeline", "run_topic_extractor"):
            assert name in wf.__all__


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
