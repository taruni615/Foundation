"""Notes generation: the two-stage pipeline and its model-fallback behaviour."""

from __future__ import annotations

import json

from edu_pipeline.ai.services.notes_service import NotesService
from edu_pipeline.shared.config import ConfigService


class TestTwoStagePipeline:
    def test_runs_exactly_two_model_calls(self, fake_llm, analysis_payload):
        llm = fake_llm(json_reply=analysis_payload)
        NotesService.generate_notes("Reflection of Light", "raw theory")
        assert len(llm.calls) == 2, "expected one analysis call and one synthesis call"

    def test_stage_one_requests_json_and_stage_two_requests_prose(self, fake_llm, analysis_payload):
        llm = fake_llm(json_reply=analysis_payload)
        NotesService.generate_notes("Reflection of Light", "raw theory")
        assert llm.calls[0]["json_format"] is True
        assert llm.calls[1]["json_format"] is False

    def test_stage_one_sees_the_raw_theory(self, fake_llm, analysis_payload):
        llm = fake_llm(json_reply=analysis_payload)
        NotesService.generate_notes("Reflection of Light", "UNIQUE-THEORY-MARKER")
        assert "UNIQUE-THEORY-MARKER" in llm.calls[0]["user_prompt"]

    def test_stage_two_receives_the_enriched_analysis(self, fake_llm, analysis_payload):
        """Knowledge enrichment sits between the stages and must reach the prompt."""
        llm = fake_llm(json_reply=analysis_payload)
        NotesService.generate_notes("Reflection of Light", "raw theory")
        stage2 = llm.calls[1]["user_prompt"]
        assert "enrichment" in stage2
        assert "estimated_study_time" in stage2
        assert "1/v + 1/u = 1/f" in stage2, "extracted formulae must survive into stage 2"

    def test_returns_notes_markdown_on_success(self, fake_llm, analysis_payload):
        fake_llm(json_reply=analysis_payload, text_reply="# Reflection\n\nNotes body.")
        result = NotesService.generate_notes("Reflection of Light", "raw theory")
        assert result["ok"] is True
        assert result["notes_markdown"] == "# Reflection\n\nNotes body."
        assert result["topic_title"] == "Reflection of Light"

    def test_uses_the_configured_notes_model(self, fake_llm, analysis_payload):
        llm = fake_llm(json_reply=analysis_payload)
        NotesService.generate_notes("T", "theory")
        expected = ConfigService.get().llm.notes_model
        assert llm.models_used == [expected, expected]

    def test_model_override_is_honoured(self, fake_llm, analysis_payload):
        llm = fake_llm(json_reply=analysis_payload)
        NotesService.generate_notes("T", "theory", model_override="custom:1b")
        assert llm.models_used[0] == "custom:1b"


class TestFallbackBehaviour:
    def test_falls_back_to_the_secondary_model_when_primary_fails(self, fake_llm, analysis_payload):
        cfg = ConfigService.get().llm
        llm = fake_llm(json_reply=analysis_payload, fail_models=(cfg.notes_model,))
        result = NotesService.generate_notes("T", "theory")
        assert cfg.notes_fallback_model in llm.models_used
        assert result["ok"] is True
        assert result["fallback_used"] is True

    def test_falls_back_when_stage_two_returns_empty_output(self, fake_llm, analysis_payload):
        cfg = ConfigService.get().llm
        llm = fake_llm(json_reply=analysis_payload, empty_models=(cfg.notes_model,))
        result = NotesService.generate_notes("T", "theory")
        assert result["ok"] is True
        assert llm.models_used.count(cfg.notes_fallback_model) >= 1

    def test_reports_failure_when_every_model_fails(self, fake_llm, analysis_payload):
        cfg = ConfigService.get().llm
        fake_llm(json_reply=analysis_payload,
                 fail_models=(cfg.notes_model, cfg.notes_fallback_model))
        result = NotesService.generate_notes("T", "theory")
        assert result["ok"] is False
        assert "error" in result

    def test_unparsable_analysis_still_produces_notes(self, fake_llm):
        """Stage 1 returning junk must degrade, not crash."""
        llm = fake_llm(json_reply={})
        import edu_pipeline.ai.providers.llm as llm_mod
        from edu_pipeline.ai.response import LLMResponse

        def junk(self, system_prompt, user_prompt, temperature=0.4,
                 max_tokens=None, json_format=False):
            llm.calls.append({"model": self._model, "json_format": json_format,
                              "temperature": temperature, "system_prompt": system_prompt,
                              "user_prompt": user_prompt})
            return LLMResponse(text="not json at all" if json_format else "# Notes", model=self._model)

        llm_mod.OllamaLLMProvider.generate = junk
        result = NotesService.generate_notes("T", "some theory text")
        assert result["ok"] is True


class TestPromptIntegrity:
    def test_notes_prompts_are_not_modified_by_the_service(self, fake_llm, analysis_payload):
        """The service must send the shipped prompt text verbatim."""
        from edu_pipeline.ai.prompts.service import PromptService

        llm = fake_llm(json_reply=analysis_payload)
        NotesService.generate_notes("T", "theory")
        assert llm.calls[0]["system_prompt"] == PromptService.notes_analysis_system_prompt().text
        assert llm.calls[1]["system_prompt"] == PromptService.notes_system_prompt().text


class TestNotesGeneratorOrchestration:
    def test_generator_writes_only_study_notes_sidecars(self, workspace, fake_llm,
                                                        analysis_payload, monkeypatch):
        """The notes CLI must never rewrite *_final.json (documented guarantee)."""
        from edu_pipeline.generators.notes import generator
        from edu_pipeline.repository import RepositoryService

        fake_llm(json_reply=analysis_payload, text_reply="# Notes body")
        final_path = workspace / "10 TEST FOUNDATION" / "10 TEST FOUNDATION_final.json"
        before = final_path.read_text(encoding="utf-8")

        repo = RepositoryService.load("10 TEST FOUNDATION", str(workspace))
        generator.generate_short_notes(repo)

        assert final_path.read_text(encoding="utf-8") == before, "*_final.json was modified"
        assert (workspace / "10 TEST FOUNDATION" / "10 TEST FOUNDATION_study_notes.json").is_file()

    def test_generated_sidecar_contains_the_model_notes(self, workspace, fake_llm, analysis_payload):
        from edu_pipeline.generators.notes import generator
        from edu_pipeline.repository import RepositoryService

        fake_llm(json_reply=analysis_payload, text_reply="# Notes body MARKER")
        repo = RepositoryService.load("10 TEST FOUNDATION", str(workspace))
        generator.generate_short_notes(repo)

        sidecar = workspace / "10 TEST FOUNDATION" / "10 TEST FOUNDATION_study_notes.json"
        assert "MARKER" in json.dumps(json.loads(sidecar.read_text(encoding="utf-8")))
