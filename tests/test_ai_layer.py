"""AI infrastructure: provider registry, prompt service, response contract."""

from __future__ import annotations

import pytest

from edu_pipeline.ai.prompts.service import PromptService, PromptTemplate
from edu_pipeline.ai.providers.llm import LLMProvider, OllamaLLMProvider
from edu_pipeline.ai.providers.registry import ProviderRegistry
from edu_pipeline.ai.response import LLMResponse
from edu_pipeline.exceptions import PromptError, ProviderError


class TestProviderRegistry:
    def test_ollama_is_registered_by_default(self):
        assert "ollama" in ProviderRegistry.list_llm_providers()
        assert "ollama" in ProviderRegistry.list_embedding_providers()

    def test_get_llm_builds_the_registered_class(self):
        provider = ProviderRegistry.get_llm("ollama", base_url="http://x:1", model="m", timeout=5)
        assert isinstance(provider, OllamaLLMProvider)
        assert provider.model_name() == "m"

    def test_lookup_is_case_insensitive(self):
        assert isinstance(ProviderRegistry.get_llm("OLLAMA", model="m"), OllamaLLMProvider)

    def test_unknown_provider_raises_with_available_options(self):
        with pytest.raises(ProviderError) as exc:
            ProviderRegistry.get_llm("does-not-exist")
        assert "does-not-exist" in str(exc.value)
        assert "ollama" in str(exc.value)

    def test_custom_provider_can_be_registered(self):
        class Dummy(LLMProvider):
            def generate(self, system_prompt, user_prompt, temperature=0.4,
                         max_tokens=None, json_format=False):
                return LLMResponse(text="ok")

            def supports_json(self):
                return False

            def supports_streaming(self):
                return False

            def model_name(self):
                return "dummy"

        try:
            ProviderRegistry.register_llm("dummy", Dummy)
            assert ProviderRegistry.get_llm("dummy").model_name() == "dummy"
        finally:
            ProviderRegistry._llm_providers.pop("dummy", None)


class TestLLMResponse:
    def test_has_sensible_defaults(self):
        r = LLMResponse(text="hello")
        assert (r.text, r.tokens, r.finish_reason, r.model) == ("hello", 0, "stop", "")

    def test_is_immutable(self):
        with pytest.raises(Exception):
            LLMResponse(text="x").text = "y"


class TestPromptService:
    @pytest.mark.parametrize("name", [
        "mcq_system", "mcq_user", "notes_system", "notes_user",
        "notes_analysis_system", "notes_analysis_user",
    ])
    def test_every_shipped_template_loads(self, name):
        tmpl = PromptService.get_template(name)
        assert isinstance(tmpl, PromptTemplate)
        assert tmpl.text.strip()
        assert tmpl.version == "v1"

    def test_templates_are_cached(self):
        assert PromptService.get_template("mcq_system") is PromptService.get_template("mcq_system")

    def test_missing_template_raises_prompt_error(self):
        with pytest.raises(PromptError):
            PromptService.get_template("no_such_prompt")

    def test_missing_version_raises_prompt_error(self):
        with pytest.raises(PromptError):
            PromptService.get_template("mcq_system", version="v99")

    def test_mcq_user_prompt_injects_every_variable(self):
        out = PromptService.mcq_user_prompt(
            question="Q?", answer="A.", subject="Physics",
            chapter="Light", question_type="Short Answer",
        )
        for expected in ("Q?", "A.", "Physics", "Light", "Short Answer"):
            assert expected in out

    def test_notes_user_prompt_injects_analysis_json(self):
        out = PromptService.notes_user_prompt(topic_title="Reflection",
                                              structured_analysis_json='{"k": 1}')
        assert "Reflection" in out and '{"k": 1}' in out

    def test_prompt_variables_accept_braces_in_values(self):
        """Injected JSON contains braces; formatting must not re-interpret them."""
        out = PromptService.notes_user_prompt(topic_title="T",
                                              structured_analysis_json='{"a": {"b": 1}}')
        assert '{"a": {"b": 1}}' in out

    def test_none_values_become_empty_strings(self):
        out = PromptService.mcq_user_prompt(question=None, answer=None)
        assert isinstance(out, str)

    def test_format_reports_the_missing_key(self):
        tmpl = PromptTemplate(name="t", version="v1", text="{present} {absent}")
        with pytest.raises(PromptError) as exc:
            tmpl.format(present="x")
        assert "absent" in str(exc.value)


class TestOllamaProviderContract:
    def test_declares_capabilities(self):
        p = OllamaLLMProvider(model="qwen3:8b")
        assert p.supports_json() is True
        assert p.supports_streaming() is True
        assert p.model_name() == "qwen3:8b"

    def test_base_url_trailing_slash_is_normalised(self):
        assert OllamaLLMProvider(base_url="http://localhost:11434/").base_url == "http://localhost:11434"

    def test_transport_failure_is_wrapped_in_provider_error(self, monkeypatch):
        import edu_pipeline.ai.providers.llm as llm_mod

        def boom(*a, **k):
            raise OSError("connection refused")

        monkeypatch.setattr(llm_mod.requests, "post", boom)
        with pytest.raises(ProviderError) as exc:
            OllamaLLMProvider(model="m").generate("sys", "user")
        assert "m" in str(exc.value)

    def test_successful_response_is_normalised(self, monkeypatch):
        import edu_pipeline.ai.providers.llm as llm_mod

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"message": {"content": "hi"}, "eval_count": 7, "done_reason": "stop"}

        monkeypatch.setattr(llm_mod.requests, "post", lambda *a, **k: Resp())
        out = OllamaLLMProvider(model="m").generate("sys", "user")
        assert (out.text, out.tokens, out.model) == ("hi", 7, "m")
        assert out.duration >= 0


class TestModelManagerHealth:
    def test_health_reports_unavailable_when_provider_is_down(self, monkeypatch):
        import edu_pipeline.ai.model_manager as mm

        def boom(*a, **k):
            raise OSError("no route to host")

        monkeypatch.setattr(mm.requests, "get", boom)
        status = mm.ModelManager.health()
        assert status.available is False
        assert status.error

    def test_health_flags_a_missing_model(self, monkeypatch):
        import edu_pipeline.ai.model_manager as mm

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"models": [{"name": "some-other-model"}]}

        monkeypatch.setattr(mm.requests, "get", lambda *a, **k: Resp())
        status = mm.ModelManager.health()
        assert status.available is False
        assert "not found" in status.error.lower()
