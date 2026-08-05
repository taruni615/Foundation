"""DB-sourced repository adapter: MySQL rows -> in-memory v3.1 document.

These tests exercise the pure construction layer only, so they need no MySQL --
the module reaches for ``storage.database`` lazily, inside the functions that
actually query.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from edu_pipeline.repository import RepositoryService
from edu_pipeline.storage import db_repository as dbrepo

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CHAPTER_ROW = {
    "chapter_id": 666,
    "chapter_number": 1,
    "chapter_name": "Light-Reflection and Refraction",
    "page_range": "1-76",
    "summary": "## Chapter Introduction\nExisting summary.",
    "key_points": "Light travels in a straight line.",
}

THEORY_ROWS = [
    {"chapter_id": 666, "section_order": 1, "topic_name": "Section",
     "topic_explanation": "Light is a form of energy."},
    {"chapter_id": 666, "section_order": 2, "topic_name": "Reflection",
     "topic_explanation": "The angle of incidence equals the angle of reflection."},
]


class TestBuildTopic:
    def test_maps_chapter_columns_onto_v31_topic_fields(self):
        topic = dbrepo.build_topic(CHAPTER_ROW, THEORY_ROWS)
        assert topic["topic_number"] == 1
        assert topic["chapter_name"] == "Light-Reflection and Refraction"
        assert topic["page_range"] == "1-76"
        assert topic["db_chapter_id"] == 666

    def test_theory_sections_use_heading_and_markdown_keys(self):
        # get_topic_theory_text reads "heading"/"markdown" on v3.1 documents;
        # any other key names would yield empty source text for the notes model.
        sections = dbrepo.build_topic(CHAPTER_ROW, THEORY_ROWS)["theory_sections"]
        assert [s["heading"] for s in sections] == ["Section", "Reflection"]
        assert sections[0]["markdown"] == "Light is a form of energy."

    def test_sections_without_body_text_are_dropped(self):
        rows = THEORY_ROWS + [
            {"chapter_id": 666, "section_order": 3, "topic_name": "Empty",
             "topic_explanation": "   "},
            {"chapter_id": 666, "section_order": 4, "topic_name": "Null",
             "topic_explanation": None},
        ]
        assert len(dbrepo.build_topic(CHAPTER_ROW, rows)["theory_sections"]) == 2

    def test_chapter_with_no_theory_yields_an_empty_section_list(self):
        assert dbrepo.build_topic(CHAPTER_ROW, [])["theory_sections"] == []

    def test_missing_columns_degrade_to_empty_values(self):
        topic = dbrepo.build_topic({"chapter_id": 1}, [])
        assert topic["topic_number"] == 0
        assert topic["chapter_name"] == ""
        assert topic["page_range"] == ""

    def test_existing_summary_and_key_points_are_carried_through(self):
        topic = dbrepo.build_topic(CHAPTER_ROW, THEORY_ROWS)
        assert topic["summary"].startswith("## Chapter Introduction")
        assert topic["key_points_text"] == "Light travels in a straight line."


class TestBuildDocument:
    def test_document_is_readable_by_the_repository_service(self):
        doc = dbrepo.build_document("10 TEST FOUNDATION", [CHAPTER_ROW],
                                    {666: THEORY_ROWS})
        text = RepositoryService.get_topic_theory_text(doc["topics"][0])
        assert "Light is a form of energy." in text
        assert "angle of incidence" in text
        assert "## Section" in text  # headings survive into the notes prompt

    def test_metadata_marks_the_document_as_db_sourced(self):
        doc = dbrepo.build_document("10 TEST FOUNDATION", [CHAPTER_ROW],
                                    {666: THEORY_ROWS})
        assert doc["metadata"]["name"] == "10 TEST FOUNDATION"
        assert doc["metadata"]["format_version"] == "3.1"
        assert doc["metadata"]["source"] == dbrepo.DB_DOCUMENT_SOURCE
        assert doc["metadata"]["topic_count"] == 1

    def test_chapters_without_matching_theory_still_produce_a_topic(self):
        doc = dbrepo.build_document("BOOK", [CHAPTER_ROW], {})
        assert len(doc["topics"]) == 1
        assert doc["topics"][0]["theory_sections"] == []

    def test_topic_order_follows_the_chapter_row_order(self):
        second = dict(CHAPTER_ROW, chapter_id=667, chapter_number=2)
        doc = dbrepo.build_document("BOOK", [CHAPTER_ROW, second], {})
        assert [t["topic_number"] for t in doc["topics"]] == [1, 2]


class TestSyntheticPath:
    def test_output_lands_under_the_given_root_not_the_pipeline_workspace(self):
        path = dbrepo.synthetic_final_path("10 TEST FOUNDATION", "out_root")
        assert path == os.path.join("out_root", "10 TEST FOUNDATION",
                                    "10 TEST FOUNDATION_final.json")

    def test_default_root_is_separate_from_the_extraction_workspace(self):
        # A DB-sourced run must never be able to overwrite extraction output.
        root = dbrepo.default_output_root()
        assert dbrepo.DB_OUTPUT_DIRNAME in root
        assert root != os.path.join("edu_pipeline", "workspace")

    def test_default_root_is_absolute_so_the_cwd_cannot_scatter_output(self):
        # The CLI is run from the repo root and from scripts/; both must write
        # to the same place.
        assert os.path.isabs(dbrepo.default_output_root())

    def test_sidecar_helpers_derive_notes_paths_from_the_synthetic_path(self):
        from edu_pipeline.extraction.topic_extractor import (
            _study_notes_topics_dir_from_final,
            study_notes_json_path_from_final,
        )

        path = dbrepo.synthetic_final_path("BOOK", "root")
        assert study_notes_json_path_from_final(path) == os.path.join(
            "root", "BOOK", "BOOK_study_notes.json")
        assert _study_notes_topics_dir_from_final(path) == os.path.join(
            "root", "BOOK", "topics_study_notes")


class TestWorkbenchCLI:
    """The CLI must be usable from any directory and must not answer a
    misconfigured DB with a pymysql traceback."""

    def _run(self, *argv, cwd):
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "db_workbench.py"), *argv],
            cwd=str(cwd), capture_output=True, text=True, timeout=120,
        )

    @pytest.mark.parametrize("sub", ["health", "books", "notes", "convert", "similar"])
    def test_every_subcommand_responds_to_help(self, sub):
        result = self._run(sub, "--help", cwd=PROJECT_ROOT)
        assert result.returncode == 0, result.stderr[-800:]
        assert "usage" in result.stdout.lower()

    def test_bare_invocation_names_the_available_subcommands(self):
        result = self._run(cwd=PROJECT_ROOT)
        assert result.returncode != 0
        assert "health" in result.stderr and "notes" in result.stderr

    def test_a_missing_socket_reports_the_cause_not_a_traceback(self, tmp_path):
        # Reproduces the Linux failure: DB_SOCKET set, no socket file there.
        # pymysql blames 'localhost', which reads as a network fault; the CLI
        # has to say it is a socket problem and how to fix it.
        if not hasattr(socket, "AF_UNIX"):
            pytest.skip("DB_SOCKET is ignored on platforms without AF_UNIX")
        env = dict(os.environ, DB_SOCKET=str(tmp_path / "absent.sock"))
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "db_workbench.py"),
             "notes", "ANY BOOK"],
            cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 2
        assert "Traceback" not in result.stderr
        assert "Cannot reach MySQL" in result.stderr
        assert "DB_SOCKET" in result.stderr


class TestConnectionTarget:
    """pymysql reports the host even for socket failures, so a missing socket
    reads as "Can't connect ... on 'localhost' ([Errno 2] ...)". These assert the
    transport is reported separately, which is what makes that legible."""

    def test_reports_the_socket_and_whether_it_exists(self, monkeypatch, tmp_path):
        from edu_pipeline.storage import database as bank_read

        missing = str(tmp_path / "absent.sock")
        monkeypatch.setattr(bank_read, "DB_SOCKET", missing)
        info = dbrepo.connection_target()
        assert info["transport"] == "unix_socket"
        assert info["target"] == missing
        assert info["socket_exists"] is False

    def test_existing_socket_is_reported_as_present(self, monkeypatch, tmp_path):
        from edu_pipeline.storage import database as bank_read

        present = tmp_path / "mysql.sock"
        present.write_text("", encoding="utf-8")
        monkeypatch.setattr(bank_read, "DB_SOCKET", str(present))
        assert dbrepo.connection_target()["socket_exists"] is True

    def test_reports_host_and_port_when_no_socket_is_configured(self, monkeypatch):
        from edu_pipeline.storage import database as bank_read

        monkeypatch.setattr(bank_read, "DB_SOCKET", "")
        info = dbrepo.connection_target()
        assert info["transport"] == "tcp"
        assert ":" in info["target"]

    def test_never_exposes_the_password(self, monkeypatch):
        from edu_pipeline.storage import database as bank_read

        monkeypatch.setattr(bank_read, "DB_SOCKET", "")
        assert "password" not in dbrepo.connection_target()


class TestWorkbenchNotesCommand:
    @pytest.fixture
    def db_workbench(self):
        import importlib.util
        from edu_pipeline.shared.paths import PROJECT_ROOT
        spec = importlib.util.spec_from_file_location("db_workbench", str(PROJECT_ROOT / "scripts" / "db_workbench.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_cmd_notes_success(self, monkeypatch, db_workbench):
        from edu_pipeline.repository import BookRepository

        # Mock resolve book
        monkeypatch.setattr(db_workbench, "_resolve_book_or_exit", lambda name: "10_physics_foundation")

        # Mock load_book
        dummy_repo = BookRepository({
            "metadata": {"name": "10_physics_foundation"},
            "topics": [
                {"topic_number": 1, "chapter_name": "Introduction", "theory_sections": [{"heading": "Intro", "markdown": "Some theory text"}]}
            ]
        }, "synthetic_path.json")
        from edu_pipeline.storage import db_repository as dbrepo
        monkeypatch.setattr(dbrepo, "load_book", lambda slug, topic_filter=None, output_root=None: dummy_repo)

        # Mock ollama check
        monkeypatch.setattr(db_workbench, "_require_ollama", lambda: True)

        # Mock generate_short_notes
        import edu_pipeline.generators.notes.generator as generator_mod
        monkeypatch.setattr(generator_mod, "generate_short_notes", lambda repo: "written_path.json")

        ret = db_workbench.main(["notes", "10 PHYSICS FOUNDATION"])
        assert ret == 0

    def test_cmd_notes_no_chapters(self, monkeypatch, db_workbench):
        from edu_pipeline.repository import BookRepository
        monkeypatch.setattr(db_workbench, "_resolve_book_or_exit", lambda name: "10_physics_foundation")
        dummy_repo = BookRepository({
            "metadata": {"name": "10_physics_foundation"},
            "topics": []
        }, "synthetic_path.json")
        from edu_pipeline.storage import db_repository as dbrepo
        monkeypatch.setattr(dbrepo, "load_book", lambda slug, topic_filter=None, output_root=None: dummy_repo)

        ret = db_workbench.main(["notes", "10 PHYSICS FOUNDATION"])
        assert ret == 1

    def test_cmd_notes_no_theory_sections(self, monkeypatch, db_workbench):
        from edu_pipeline.repository import BookRepository
        monkeypatch.setattr(db_workbench, "_resolve_book_or_exit", lambda name: "10_physics_foundation")
        dummy_repo = BookRepository({
            "metadata": {"name": "10_physics_foundation"},
            "topics": [
                {"topic_number": 1, "chapter_name": "Introduction", "theory_sections": []}
            ]
        }, "synthetic_path.json")
        from edu_pipeline.storage import db_repository as dbrepo
        monkeypatch.setattr(dbrepo, "load_book", lambda slug, topic_filter=None, output_root=None: dummy_repo)

        ret = db_workbench.main(["notes", "10 PHYSICS FOUNDATION"])
        assert ret == 1

    def test_cmd_notes_no_ollama(self, monkeypatch, db_workbench):
        from edu_pipeline.repository import BookRepository
        monkeypatch.setattr(db_workbench, "_resolve_book_or_exit", lambda name: "10_physics_foundation")
        dummy_repo = BookRepository({
            "metadata": {"name": "10_physics_foundation"},
            "topics": [
                {"topic_number": 1, "chapter_name": "Introduction", "theory_sections": [{"heading": "Intro", "markdown": "Some theory text"}]}
            ]
        }, "synthetic_path.json")
        from edu_pipeline.storage import db_repository as dbrepo
        monkeypatch.setattr(dbrepo, "load_book", lambda slug, topic_filter=None, output_root=None: dummy_repo)
        monkeypatch.setattr(db_workbench, "_require_ollama", lambda: False)

        ret = db_workbench.main(["notes", "10 PHYSICS FOUNDATION"])
        assert ret == 2
