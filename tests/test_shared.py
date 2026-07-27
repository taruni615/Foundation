"""Shared infrastructure: JSON extraction, paths, constants, config, logging."""

from __future__ import annotations

import logging
from pathlib import Path

from edu_pipeline.shared.constants import QA_SECTION_KEYS
from edu_pipeline.shared.json_utils import extract_json_object
from edu_pipeline.shared.logger import PipelineLogger
from edu_pipeline.shared.paths import PACKAGE_ROOT, PROJECT_ROOT, load_dotenv


class TestExtractJsonObject:
    """LLM replies are rarely clean JSON; the extractor must cope."""

    def test_parses_plain_json(self):
        assert extract_json_object('{"a": 1}') == {"a": 1}

    def test_parses_json_with_surrounding_prose(self):
        assert extract_json_object('Here you go:\n{"a": 1}\nHope that helps') == {"a": 1}

    def test_parses_json_in_markdown_fence(self):
        assert extract_json_object('```json\n{"a": 1, "b": [2]}\n```') == {"a": 1, "b": [2]}

    def test_parses_multiline_nested_json(self):
        text = 'noise\n{\n  "x": {"y": [1, 2]},\n  "z": "s"\n}\ntrailing'
        assert extract_json_object(text) == {"x": {"y": [1, 2]}, "z": "s"}

    def test_returns_none_for_unparsable(self):
        assert extract_json_object("no json at all") is None
        assert extract_json_object("{not: valid}") is None
        assert extract_json_object("") is None

    def test_tolerates_leading_trailing_whitespace(self):
        assert extract_json_object('   \n {"a": 1} \n  ') == {"a": 1}


class TestPaths:
    def test_roots_point_at_the_repository(self):
        assert (PROJECT_ROOT / "edu_pipeline").is_dir()
        assert PACKAGE_ROOT == PROJECT_ROOT / "edu_pipeline"

    def test_load_dotenv_missing_file_is_not_an_error(self, tmp_path):
        load_dotenv(tmp_path / "nope.env")  # must not raise

    def test_load_dotenv_does_not_override_real_environment(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("SAMPLE_KEY=from_file\nOTHER_KEY=other\n", encoding="utf-8")
        monkeypatch.setenv("SAMPLE_KEY", "from_environment")
        monkeypatch.delenv("OTHER_KEY", raising=False)
        load_dotenv(env)
        import os
        assert os.environ["SAMPLE_KEY"] == "from_environment"  # real env wins
        assert os.environ["OTHER_KEY"] == "other"              # file fills the gap

    def test_load_dotenv_ignores_comments_and_blanks(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text('\n# comment\nQUOTED="quoted value"\nNO_EQUALS_LINE\n', encoding="utf-8")
        monkeypatch.delenv("QUOTED", raising=False)
        load_dotenv(env)
        import os
        assert os.environ["QUOTED"] == "quoted value"


class TestConstants:
    def test_qa_section_keys_shared_by_every_consumer(self):
        """All layers must agree on which arrays hold questions."""
        from edu_pipeline.ai.services.mcq_service import QA_SECTION_KEYS as mcq_keys
        from edu_pipeline.repository.service import QA_SECTION_KEYS as repo_keys
        from edu_pipeline.storage.export_qa import QA_SECTION_KEYS as export_keys

        assert repo_keys is QA_SECTION_KEYS
        assert export_keys is QA_SECTION_KEYS
        assert mcq_keys is QA_SECTION_KEYS
        assert "illustrations" in QA_SECTION_KEYS


class TestDbConfig:
    def test_extraction_reexports_the_canonical_values(self):
        """topic_extractor must keep re-exporting DB_* for the wrappers."""
        import edu_pipeline.extraction.topic_extractor as extraction
        import edu_pipeline.shared.db_config as db_config

        for name in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
            assert getattr(extraction, name) == getattr(db_config, name)

    def test_storage_uses_the_same_settings_as_extraction(self):
        import edu_pipeline.extraction.topic_extractor as extraction
        import edu_pipeline.storage.database as database

        assert database.DB_NAME == extraction.DB_NAME
        assert database.DB_HOST == extraction.DB_HOST


class TestPipelineLogger:
    def test_returns_distinct_loggers_per_name(self):
        a = PipelineLogger.get_logger("component.a")
        b = PipelineLogger.get_logger("component.b")
        assert a.name == "component.a"
        assert b.name == "component.b"
        assert a is not b

    def test_same_name_returns_cached_logger(self):
        assert PipelineLogger.get_logger("component.a") is PipelineLogger.get_logger("component.a")

    def test_emits_severity_and_component(self, caplog):
        with caplog.at_level(logging.INFO, logger="edu_pipeline"):
            PipelineLogger.info("hello %s", "world")
        assert any(r.levelname == "INFO" and "hello world" in r.getMessage() for r in caplog.records)

    def test_handler_formats_with_timestamp_severity_component(self):
        logger = PipelineLogger.get_logger("fmt.check")
        fmt = logger.handlers[0].formatter._fmt
        assert "%(asctime)s" in fmt
        assert "%(levelname)s" in fmt
        assert "%(name)s" in fmt


class TestSecretsAreNotHardcoded:
    """Regression guard for the credentials that were committed in source."""

    def test_mathpix_credentials_have_no_source_defaults(self):
        src = (PROJECT_ROOT / "edu_pipeline" / "extraction" / "topic_extractor.py").read_text(
            encoding="utf-8"
        )
        assert 'os.environ.get("MATHPIX_APP_ID", "")' in src
        assert 'os.environ.get("MATHPIX_APP_KEY", "")' in src
        assert "mylp_936a22" not in src

    def test_env_example_exists_and_holds_no_values(self):
        example = PROJECT_ROOT / ".env.example"
        assert example.is_file()
        for line in example.read_text(encoding="utf-8").splitlines():
            if line.startswith(("MATHPIX_APP_KEY", "DB_PASSWORD", "ASSESS_SECRET")):
                assert line.split("=", 1)[1] == "", f"{line!r} must ship empty"
