"""MCQ engine: validation rules, question planning, bank assembly, conversion."""

from __future__ import annotations

import pytest

from edu_pipeline.ai.services.mcq_builder import QuestionBankBuilder
from edu_pipeline.ai.services.mcq_planner import QuestionPlanItem, QuestionPlanner
from edu_pipeline.ai.services.mcq_service import MCQService
from edu_pipeline.ai.services.mcq_validator import MCQValidator


def good_mcq(**overrides):
    base = {
        "stem": "Which law relates V, I and R?",
        "options": ["Ohm's law", "Newton's law", "Hooke's law", "Snell's law"],
        "correct_index": 0,
        "explanation": "V = IR is Ohm's law.",
    }
    base.update(overrides)
    return base


class TestValidatorAcceptsGoodQuestions:
    def test_accepts_a_well_formed_mcq(self):
        ok, errors, clean = MCQValidator.validate(good_mcq())
        assert ok is True and errors == []
        assert clean["stem"] and len(clean["options"]) == 4

    def test_normalises_output_shape(self):
        _, _, clean = MCQValidator.validate(good_mcq())
        assert set(clean) == {"stem", "options", "correct_index", "explanation", "metadata"}

    def test_attaches_plan_metadata(self):
        _, _, clean = MCQValidator.validate(
            good_mcq(), origin="generated", plan_concept="Ohm's Law",
            plan_difficulty="Hard", plan_blooms="Analyze", plan_type="Numerical",
        )
        meta = clean["metadata"]
        assert meta["concept"] == "Ohm's Law"
        assert meta["difficulty"] == "Hard"
        assert meta["blooms"] == "Analyze"
        assert meta["origin"] == "generated"

    def test_accepts_alternative_field_names(self):
        ok, _, clean = MCQValidator.validate({
            "question": "Stem via 'question' key?",
            "options": ["a", "b", "c", "d"],
            "correct_option_index": 2,
            "answer": "because",
        })
        assert ok is True
        assert clean["correct_index"] == 2

    def test_supplies_a_default_explanation(self):
        _, _, clean = MCQValidator.validate(good_mcq(explanation=""))
        assert clean["explanation"].strip()


class TestValidatorRejectsBadQuestions:
    @pytest.mark.parametrize("payload,reason", [
        (good_mcq(stem=""), "missing stem"),
        (good_mcq(options=["a", "b", "c"]), "too few options"),
        (good_mcq(options=["a", "b", "c", "d", "e"]), "too many options"),
        (good_mcq(options=["a", "a", "b", "c"]), "duplicate options"),
        (good_mcq(correct_index=9), "index out of range"),
        (good_mcq(correct_index=None), "missing index"),
        (good_mcq(correct_index="x"), "non-integer index"),
    ])
    def test_rejects_malformed_payloads(self, payload, reason):
        ok, errors, clean = MCQValidator.validate(payload)
        assert ok is False, reason
        assert errors and clean == {}

    @pytest.mark.parametrize("bad_option", [
        "All of the above", "all of the ABOVE", "None of the above", "none of these",
    ])
    def test_rejects_forbidden_option_patterns(self, bad_option):
        ok, errors, _ = MCQValidator.validate(good_mcq(options=["a", "b", "c", bad_option]))
        assert ok is False
        assert any("forbidden" in e.lower() for e in errors)

    def test_rejects_a_non_dict_payload(self):
        ok, errors, _ = MCQValidator.validate("not a dict")
        assert ok is False and errors


class TestQuestionPlanner:
    def test_produces_the_requested_number_of_questions(self):
        for n in (1, 4, 5, 10, 20):
            assert len(QuestionPlanner.generate_plan("T", {"core_concepts": ["a"]}, n)) == n

    def test_uses_the_documented_difficulty_mix_at_scale(self):
        plan = QuestionPlanner.generate_plan("T", {"core_concepts": ["a", "b"]}, 10)
        counts = {d: sum(1 for i in plan if i.difficulty == d) for d in ("Easy", "Medium", "Hard")}
        assert counts == {"Easy": 3, "Medium": 5, "Hard": 2}

    def test_cycles_through_every_concept(self):
        plan = QuestionPlanner.generate_plan("T", {"core_concepts": ["A", "B", "C"]}, 9)
        assert {i.concept for i in plan} == {"A", "B", "C"}

    def test_falls_back_to_the_topic_when_no_concepts_exist(self):
        plan = QuestionPlanner.generate_plan("Electricity", {}, 3)
        assert all(i.concept == "Electricity" for i in plan)

    def test_every_item_is_fully_specified(self):
        for item in QuestionPlanner.generate_plan("T", {"core_concepts": ["a"]}, 10):
            assert isinstance(item, QuestionPlanItem)
            assert item.concept and item.difficulty and item.question_type and item.blooms

    def test_plans_formula_questions_when_formulae_exist(self):
        plan = QuestionPlanner.generate_plan("T", {"core_concepts": ["a"], "formulae": ["E=mc^2"]}, 10)
        assert any(i.question_type == "Formula-Based" for i in plan)


class TestQuestionBankBuilder:
    def test_removes_duplicate_stems(self):
        items = [good_mcq(), good_mcq(), good_mcq(stem="A different stem entirely?")]
        assert len(QuestionBankBuilder.deduplicate(items)) == 2

    def test_deduplication_ignores_case_and_punctuation(self):
        items = [good_mcq(stem="What is force?"), good_mcq(stem="WHAT IS FORCE!!!")]
        assert len(QuestionBankBuilder.deduplicate(items)) == 1

    def test_drops_items_without_a_stem(self):
        assert QuestionBankBuilder.deduplicate([{"stem": ""}, {"stem": "   "}]) == []

    def test_balances_the_correct_answer_across_positions(self):
        items = [good_mcq(stem=f"Question number {i}?") for i in range(8)]
        balanced = QuestionBankBuilder.balance_answer_distribution(items)
        assert sorted({i["correct_index"] for i in balanced}) == [0, 1, 2, 3]

    def test_balancing_keeps_the_correct_option_text(self):
        items = [good_mcq(stem=f"Q{i}?") for i in range(4)]
        for original, balanced in zip(items, QuestionBankBuilder.balance_answer_distribution(items)):
            assert balanced["options"][balanced["correct_index"]] == \
                original["options"][original["correct_index"]]

    def test_balancing_preserves_the_option_set(self):
        items = [good_mcq(stem=f"Q{i}?") for i in range(4)]
        for original, balanced in zip(items, QuestionBankBuilder.balance_answer_distribution(items)):
            assert sorted(balanced["options"]) == sorted(original["options"])

    def test_build_bank_returns_validated_items_only(self):
        bank = QuestionBankBuilder.build_bank(
            converted_mcqs=[good_mcq(stem="Converted one?"), good_mcq(options=["a", "a", "b", "c"])],
            generated_mcqs=[good_mcq(stem="Generated one?")],
            target_count=4,
        )
        assert all(len(item["options"]) == 4 for item in bank)
        assert all("metadata" in item for item in bank)

    def test_build_bank_never_exceeds_the_target(self):
        converted = [good_mcq(stem=f"C{i}?") for i in range(10)]
        generated = [good_mcq(stem=f"G{i}?") for i in range(10)]
        bank = QuestionBankBuilder.build_bank(converted, generated, target_count=6)
        assert len(bank) <= 6

    def test_build_bank_handles_empty_inputs(self):
        assert QuestionBankBuilder.build_bank([], [], target_count=5) == []


class TestConversionService:
    def test_converts_a_theory_question(self, fake_llm):
        fake_llm(json_reply=good_mcq())
        result = MCQService.generate_mcq("State Ohm's law.", "V = IR", subject="Physics")
        assert result["ok"] is True
        assert result["mcq"]["stem"]

    def test_uses_the_shipped_mcq_prompt_verbatim(self, fake_llm):
        from edu_pipeline.ai.prompts.service import PromptService

        llm = fake_llm(json_reply=good_mcq())
        MCQService.generate_mcq("Q", "A")
        assert llm.calls[0]["system_prompt"] == PromptService.mcq_system_prompt().text

    def test_requests_json_mode(self, fake_llm):
        llm = fake_llm(json_reply=good_mcq())
        MCQService.generate_mcq("Q", "A")
        assert llm.calls[0]["json_format"] is True

    def test_reports_failure_for_unparsable_output(self, fake_llm, monkeypatch):
        import edu_pipeline.ai.providers.llm as llm_mod
        from edu_pipeline.ai.response import LLMResponse

        monkeypatch.setattr(
            llm_mod.OllamaLLMProvider, "generate",
            lambda self, *a, **k: LLMResponse(text="definitely not json", model=self._model),
        )
        result = MCQService.generate_mcq("Q", "A")
        assert result["ok"] is False and "error" in result

    def test_reports_failure_when_the_model_returns_an_invalid_mcq(self, fake_llm):
        fake_llm(json_reply=good_mcq(options=["only", "three", "here"]))
        result = MCQService.generate_mcq("Q", "A")
        assert result["ok"] is False
        assert "validation" in result["error"].lower()

    def test_facade_delegates_to_the_service(self, fake_llm):
        from edu_pipeline.ai import AIService

        fake_llm(json_reply=good_mcq())
        assert AIService.generate_mcq("Q", "A")["ok"] is True


class TestConversionHeuristics:
    """The generator layer decides which rows are worth converting."""

    def test_identifies_theory_types(self):
        from edu_pipeline.generators.questions import mcq_generator as mg

        assert mg.is_theory_type("Short Answer") is True
        assert mg.is_theory_type("MCQ") is False

    def test_detects_questions_that_already_embed_options(self):
        from edu_pipeline.generators.questions import mcq_generator as mg

        assert mg.looks_like_mcq("Pick one:\n(a) first\n(b) second\n(c) third") is True
        assert mg.looks_like_mcq("Define refraction.") is False

    def test_skips_rows_that_are_already_mcq_shaped(self):
        from edu_pipeline.generators.questions import mcq_generator as mg

        assert mg.needs_conversion("Short Answer", "Define force.") is True
        assert mg.needs_conversion("Short Answer", "Pick:\n(a) one\n(b) two") is False
        assert mg.needs_conversion("MCQ", "Define force.") is False
