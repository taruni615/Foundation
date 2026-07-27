"""Educational content quality: cleaning, validation, metrics."""

from __future__ import annotations

import pytest

from edu_pipeline.ai.services.content_quality import (
    contamination_ratio,
    detect_duplicate_concepts,
    infer_subject,
    strip_question_bank,
    validate_mcq_quality,
    validate_notes,
)
from edu_pipeline.ai.services.educational_metrics import (
    mcq_bank_metrics,
    notes_metrics,
    question_metrics,
    summarise,
)

THEORY = """Light is a form of energy that produces the sensation of vision.
It travels in straight lines and reflects off smooth surfaces.
The angle of incidence equals the angle of reflection.
"""

QUESTION_BANK = """DIRECTIONS (Qs. 20-23) : This section contains multiple choice questions.
20. A thin concavo-convex lens has focal length f.
(a) 10 cm
(b) 20 cm
(c) 30 cm
(d) 40 cm
21. Two mirrors form a triangle.
(a) 45
(b) 60
(c) 90
(d) 120
"""


class TestQuestionBankStripping:
    def test_removes_exam_directions_and_option_blocks(self):
        cleaned = strip_question_bank(THEORY * 12 + QUESTION_BANK)
        assert "DIRECTIONS" not in cleaned
        assert "(a) 10 cm" not in cleaned
        assert "angle of incidence" in cleaned

    def test_keeps_theory_when_it_is_interleaved_with_questions(self):
        """Question blocks sit between theory, so truncation loses chapters."""
        source = THEORY * 6 + QUESTION_BANK + THEORY * 6
        cleaned = strip_question_bank(source)
        assert cleaned.count("angle of incidence") >= 10
        assert "DIRECTIONS" not in cleaned

    def test_reduces_measured_contamination(self):
        source = THEORY * 8 + QUESTION_BANK
        assert contamination_ratio(strip_question_bank(source)) < contamination_ratio(source)

    def test_pure_theory_is_left_alone(self):
        assert strip_question_bank(THEORY).strip() == THEORY.strip()

    def test_never_returns_almost_nothing(self):
        """A false positive must not starve the notes model."""
        assert len(strip_question_bank(QUESTION_BANK)) > 0

    def test_empty_input(self):
        assert strip_question_bank("") == ""


class TestSubjectInference:
    @pytest.mark.parametrize("topic,expected", [
        ("Light - Reflection and Refraction", "Physics"),
        ("Magnetic Effects of Electric Current", "Physics"),
        ("Acids, Bases and Salts", "Chemistry"),
        ("Metals and Non-Metals", "Chemistry"),
        ("Life Process", "Biology"),
        ("How Do Organisms Reproduce", "Biology"),
        ("Real Numbers", "Mathematics"),
        ("Polynomials", "Mathematics"),
    ])
    def test_infers_real_chapter_titles(self, topic, expected):
        assert infer_subject(topic) == expected

    def test_unknown_topic_falls_back_to_general_science(self):
        assert infer_subject("Chapter One") == "General Science"


class TestNotesValidation:
    def _notes(self, extra: str = "") -> str:
        return (
            "# Reflection\n### Quick Summary\nLight bounces off surfaces.\n"
            "### Detailed Explanation\n" + "Detail. " * 40 +
            "\n### Points to Remember\n- Angle i equals angle r\n" + extra
        )

    def test_accepts_well_formed_notes(self):
        assert validate_notes(self._notes(), {}).ok is True

    def test_flags_missing_required_sections(self):
        report = validate_notes("# Title\nSome text only." + "x" * 300, {})
        assert report.ok is False
        assert any("Quick Summary" in e for e in report.errors)

    def test_flags_notes_that_are_too_short(self):
        assert validate_notes("# Tiny", {}).ok is False

    def test_flags_dropped_source_formulae(self):
        report = validate_notes(self._notes(), {"formulae": ["1/v + 1/u = 1/f"]})
        assert report.ok is False
        assert any("formula" in e.lower() for e in report.errors)

    def test_accepts_notes_that_carry_the_formula(self):
        notes = self._notes(extra="\n### Formula Section\n- **Formula:** 1/v + 1/u = 1/f\n")
        assert validate_notes(notes, {"formulae": ["1/v + 1/u = 1/f"]}).ok is True

    def test_warns_when_derivations_are_dropped(self):
        report = validate_notes(self._notes(), {"derivations": ["mirror formula"]})
        assert any("Derivation" in w for w in report.warnings)

    def test_warns_on_difficulty_contradiction(self):
        notes = self._notes() + "\n**Difficulty Level:** 🟢 Easy\n"
        report = validate_notes(notes, {"enrichment": {"difficulty": "🔴 Advanced"}})
        assert any("difficulty" in w.lower() for w in report.warnings)

    def test_rejects_notes_containing_question_paper_material(self):
        report = validate_notes(self._notes() + "\n" + QUESTION_BANK * 4, {})
        assert report.ok is False
        assert any("question-bank" in e for e in report.errors)


class TestMcqQualityValidation:
    def _mcq(self, **kw):
        base = {
            "stem": "Which quantity is measured in ohms?",
            "options": ["Resistance", "Current", "Voltage", "Power"],
            "correct_index": 0,
            "explanation": "Resistance is measured in ohms; current is in amperes.",
        }
        base.update(kw)
        return base

    def test_accepts_a_sound_question(self):
        assert validate_mcq_quality(self._mcq()).ok is True

    def test_flags_a_length_cue(self):
        mcq = self._mcq(options=[
            "Resistance, which opposes the flow of charge and is measured in ohms in SI units",
            "Current", "Voltage", "Power",
        ])
        assert any("longer" in w for w in validate_mcq_quality(mcq).warnings)

    def test_flags_a_thin_explanation(self):
        assert any("brief" in w for w in validate_mcq_quality(self._mcq(explanation="Yes.")).warnings)

    def test_flags_hedging_language(self):
        mcq = self._mcq(explanation="This might be resistance, but it possibly could be current.")
        assert any("hedge" in w.lower() for w in validate_mcq_quality(mcq).warnings)

    def test_rejects_a_trivial_stem(self):
        assert validate_mcq_quality(self._mcq(stem="Why?")).ok is False

    def test_rejects_indistinct_options(self):
        mcq = self._mcq(options=["Resistance", "resistance ", "Voltage", "Power"])
        assert validate_mcq_quality(mcq).ok is False


class TestDuplicateConceptDetection:
    def test_finds_near_duplicate_stems(self):
        mcqs = [
            {"stem": "What is the SI unit of electrical resistance?"},
            {"stem": "The SI unit of electrical resistance is what?"},
            {"stem": "Define photosynthesis in green plants."},
        ]
        flagged = detect_duplicate_concepts(mcqs)
        assert len(flagged) == 1
        assert flagged[0]["duplicate_of"] == 0

    def test_distinct_questions_are_not_flagged(self):
        mcqs = [{"stem": "What is Ohm's law?"}, {"stem": "Define photosynthesis."}]
        assert detect_duplicate_concepts(mcqs) == []


class TestEducationalMetrics:
    def test_notes_metrics_report_coverage(self, sample_document):
        metrics = notes_metrics(sample_document)
        assert metrics["topics"] == 2
        assert metrics["theory_coverage_pct"] == 100.0
        assert "subject_distribution" in metrics

    def test_question_metrics_detect_duplicates(self):
        questions = [{"question": "Same question?", "answer": "A" * 50}] * 4
        metrics = question_metrics(questions)
        assert metrics["questions"] == 4
        assert metrics["duplicate_pct"] == 75.0

    def test_question_metrics_read_json_field_names(self):
        """Documents use problem/solution; the database uses question/answer."""
        metrics = question_metrics([{"problem": "A real stem here", "solution": "x" * 60}])
        assert metrics["unique_stem_pct"] == 100.0
        assert metrics["explanation_adequate_pct"] == 100.0

    def test_mcq_bank_metrics_summarise_blooms_and_balance(self):
        mcqs = [
            {"correct_index": i % 4,
             "stem": f"Question {i}?",
             "metadata": {"blooms": "Apply", "difficulty": "Medium", "concept": f"C{i%2}"}}
            for i in range(8)
        ]
        metrics = mcq_bank_metrics(mcqs)
        assert metrics["mcqs"] == 8
        assert metrics["answer_position_balance"] == 1.0
        assert metrics["distinct_concepts"] == 2
        assert metrics["blooms_coverage"] == 1

    def test_summarise_turns_metrics_into_findings(self):
        findings = summarise({"duplicate_pct": 55.0, "explanation_adequate_pct": 20.0})
        assert len(findings) == 2

    def test_summarise_is_quiet_on_healthy_metrics(self):
        assert summarise({"duplicate_pct": 2.0, "explanation_adequate_pct": 95.0}) == []
