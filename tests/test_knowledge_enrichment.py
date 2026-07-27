"""Knowledge enrichment: deterministic educational metadata, no model calls."""

from __future__ import annotations

import copy

import pytest

from edu_pipeline.ai.services.knowledge_enrichment import (
    KnowledgeEnrichmentService,
    calculate_difficulty,
    calculate_exam_importance,
    calculate_study_time,
    enrich_topic_analysis,
)

ENRICHMENT_FIELDS = {
    "subject", "difficulty", "exam_importance", "estimated_study_time",
    "learning_objectives", "formula_index", "prerequisite_graph",
    "concept_dependency_graph", "revision_keywords", "ranked_misconceptions",
    "selected_memory_hook",
}


class TestDeterminism:
    def test_same_input_yields_same_output(self, analysis_payload):
        assert enrich_topic_analysis(analysis_payload) == enrich_topic_analysis(analysis_payload)

    def test_does_not_mutate_its_input(self, analysis_payload):
        original = copy.deepcopy(analysis_payload)
        enrich_topic_analysis(analysis_payload)
        assert analysis_payload == original

    def test_service_and_function_agree(self, analysis_payload):
        assert KnowledgeEnrichmentService.enrich(analysis_payload) == enrich_topic_analysis(
            analysis_payload
        )

    def test_makes_no_network_calls(self, analysis_payload, monkeypatch):
        import requests

        def fail(*a, **k):
            raise AssertionError("enrichment must not perform network I/O")

        monkeypatch.setattr(requests, "post", fail)
        monkeypatch.setattr(requests, "get", fail)
        enrich_topic_analysis(analysis_payload)


class TestOutputShape:
    def test_emits_every_enrichment_field(self, analysis_payload):
        assert set(enrich_topic_analysis(analysis_payload)["enrichment"]) == ENRICHMENT_FIELDS

    def test_preserves_the_original_analysis_keys(self, analysis_payload):
        enriched = enrich_topic_analysis(analysis_payload)
        for key, value in analysis_payload.items():
            assert enriched[key] == value

    def test_handles_a_completely_empty_analysis(self):
        enriched = enrich_topic_analysis({})
        assert set(enriched["enrichment"]) == ENRICHMENT_FIELDS
        assert enriched["enrichment"]["estimated_study_time"].endswith("Minutes")

    def test_formula_index_reuses_the_extracted_formulae_verbatim(self, analysis_payload):
        index = enrich_topic_analysis(analysis_payload)["enrichment"]["formula_index"]
        assert [f["formula"] for f in index] == analysis_payload["formulae"]
        assert all(f["status"] == "extracted" for f in index)

    def test_misconceptions_are_ranked_in_order(self):
        ranked = enrich_topic_analysis({"common_mistakes": ["a", "b"]})["enrichment"][
            "ranked_misconceptions"
        ]
        assert [r["misconception"] for r in ranked] == ["a", "b"]
        assert ranked[0]["priority"].endswith("#1")

    def test_memory_hook_uses_the_first_candidate(self):
        out = enrich_topic_analysis({"memory_candidates": ["VIBGYOR", "other"]})
        assert out["enrichment"]["selected_memory_hook"] == "VIBGYOR"


class TestHeuristics:
    def test_difficulty_rises_with_derivations_and_formulae(self):
        """Weighted load, so a single derivation no longer forces 'Advanced'."""
        assert "Easy" in calculate_difficulty(0, 0, 1)
        assert "Medium" in calculate_difficulty(1, 0, 1)
        assert "Medium" in calculate_difficulty(0, 1, 1)
        assert "Advanced" in calculate_difficulty(3, 1, 4)

    def test_difficulty_is_monotonic_in_load(self):
        order = {"🟢": 0, "🟡": 1, "🔴": 2}
        scores = [order[calculate_difficulty(f, d, c)[0]]
                  for f, d, c in [(0, 0, 0), (1, 0, 2), (2, 1, 4), (4, 3, 8)]]
        assert scores == sorted(scores)

    def test_difficulty_spreads_across_buckets_on_realistic_input(self):
        """The old rule collapsed almost every science topic into 'Advanced'."""
        realistic = [(0, 0, 2), (1, 0, 3), (2, 0, 4), (1, 1, 5), (3, 1, 6), (4, 2, 8)]
        buckets = {calculate_difficulty(*args)[0] for args in realistic}
        assert len(buckets) >= 3

    def test_exam_importance_is_a_five_star_scale(self):
        for args in [(0, 0, 0), (1, 0, 0), (2, 1, 1), (5, 5, 5)]:
            rating = calculate_exam_importance(*args)
            assert len(rating) == 5
            assert set(rating) <= {"★", "☆"}

    def test_exam_importance_is_monotonic(self):
        low = calculate_exam_importance(0, 0, 0).count("★")
        high = calculate_exam_importance(4, 3, 2).count("★")
        assert high > low

    def test_study_time_is_clamped_to_a_sane_range(self):
        for length, formulae, derivations in [(0, 0, 0), (1_000_000, 50, 50), (2_000, 3, 1)]:
            minutes = int(calculate_study_time(length, formulae, derivations).split()[0])
            assert 5 <= minutes <= 90

    def test_study_time_scales_with_source_length(self):
        """Grounded in the source text, so a long chapter no longer reads as 10 min."""
        short = int(calculate_study_time(2_000, 0, 0).split()[0])
        long = int(calculate_study_time(120_000, 0, 0).split()[0])
        assert long > short * 3

    def test_study_time_uses_source_length_when_supplied(self):
        small = enrich_topic_analysis({"topic": "T"}, source_char_count=1_500)
        large = enrich_topic_analysis({"topic": "T"}, source_char_count=150_000)
        minutes = lambda e: int(e["enrichment"]["estimated_study_time"].split()[0])
        assert minutes(large) > minutes(small)

    def test_learning_objectives_reflect_available_material(self, analysis_payload):
        objectives = enrich_topic_analysis(analysis_payload)["enrichment"]["learning_objectives"]
        assert objectives
        assert any("formula" in o.lower() for o in objectives)
        assert any("deriv" in o.lower() for o in objectives)

    def test_objectives_still_produced_without_formulae_or_derivations(self):
        objectives = enrich_topic_analysis({"topic": "T", "core_concepts": ["c"]})["enrichment"][
            "learning_objectives"
        ]
        assert objectives
        assert not any("formula" in o.lower() for o in objectives)


class TestSubjectAwareness:
    """Fallback wording previously said "Physical" for every subject."""

    @pytest.mark.parametrize("topic,expected", [
        ("Light - Reflection and Refraction", "Physics"),
        ("Acids, Bases and Salts", "Chemistry"),
        ("Life Processes", "Biology"),
        ("Real Numbers", "Mathematics"),
    ])
    def test_infers_the_subject_from_the_topic(self, topic, expected):
        assert enrich_topic_analysis({"topic": topic})["enrichment"]["subject"] == expected

    def test_prerequisite_fallback_matches_the_subject(self):
        bio = enrich_topic_analysis({"topic": "Life Processes"})["enrichment"]
        assert "Physical" not in bio["prerequisite_graph"][0]
        assert "Cell" in bio["prerequisite_graph"][0]

    def test_dependency_graph_matches_the_subject(self):
        maths = enrich_topic_analysis({"topic": "Polynomials", "core_concepts": ["Degree"]})
        depends = maths["enrichment"]["concept_dependency_graph"][0]["depends_on"]
        assert "Mathematical" in depends

    def test_explicit_subject_overrides_inference(self):
        out = enrich_topic_analysis({"topic": "Real Numbers"}, subject="Chemistry")
        assert out["enrichment"]["subject"] == "Chemistry"


class TestRobustness:
    def test_tolerates_non_string_list_entries(self):
        payload = {"topic": 1, "definitions": [None, 2], "core_concepts": [{"a": 1}],
                   "formulae": [3.5], "common_mistakes": [True]}
        assert set(enrich_topic_analysis(payload)["enrichment"]) == ENRICHMENT_FIELDS

    def test_tolerates_null_valued_keys(self):
        payload = {"topic": None, "definitions": None, "core_concepts": None, "formulae": None}
        assert set(enrich_topic_analysis(payload)["enrichment"]) == ENRICHMENT_FIELDS
