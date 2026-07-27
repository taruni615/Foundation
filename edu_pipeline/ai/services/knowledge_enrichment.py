#!/usr/bin/env python3
"""Knowledge Enrichment Stage providing deterministic educational metadata heuristics for Study Notes.

Computes difficulty, exam importance, estimated study time, learning objectives,
formula index, prerequisite graph, concept dependency graph, revision keywords,
and misconception rankings without additional LLM calls.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


def calculate_difficulty(formula_count: int, derivation_count: int, concept_count: int) -> str:
    """Rule-based difficulty heuristic.

    Weighted rather than "any derivation => Advanced", which previously pushed
    almost every science topic into a single bucket and made the label useless
    for planning revision order.
    """
    load = (derivation_count * 2.5) + (formula_count * 1.5) + (concept_count * 0.5)
    if load >= 7:
        return "🔴 Advanced"
    if load >= 2:
        return "🟡 Medium"
    return "🟢 Easy"


def calculate_exam_importance(formula_count: int, derivation_count: int, exam_points_count: int) -> str:
    """Rule-based exam importance star rating heuristic."""
    score = (derivation_count * 2) + (formula_count * 1.5) + (exam_points_count * 1)
    if score >= 5:
        return "★★★★★"
    elif score >= 3:
        return "★★★★☆"
    elif score >= 1.5:
        return "★★★☆☆"
    return "★★☆☆☆"


def calculate_study_time(text_length: int, formula_count: int, derivation_count: int) -> str:
    """Estimated focused-study time in minutes.

    ``text_length`` should be the length of the SOURCE theory, not of the
    extracted analysis strings. Measuring the analysis made every chapter land
    on the 10-minute floor regardless of size. 180 wpm x ~5.5 chars/word is a
    typical silent-reading rate for this age group; formulae and derivations add
    working time on top.
    """
    reading_minutes = text_length / (180 * 5.5)
    base_minutes = reading_minutes + (formula_count * 2.5) + (derivation_count * 4.0)
    rounded = max(5, min(90, round(base_minutes / 5) * 5))
    return f"{rounded} Minutes"


def generate_learning_objectives(
    topic: str,
    definitions: List[str],
    formulae: List[str],
    derivations: List[str],
    core_concepts: List[str],
) -> List[str]:
    """Derive measurable learning outcomes deterministically."""
    objectives: List[str] = []
    topic_name = topic or "this topic"

    if definitions:
        def_term = re.sub(r"[:\-].*$", "", str(definitions[0])).strip()
        objectives.append(f"✓ Define and explain the fundamental concept of {def_term or topic_name}.")
    else:
        objectives.append(f"✓ Explain the core principles of {topic_name}.")

    if core_concepts:
        objectives.append(f"✓ Understand the key mechanisms and characteristics of {topic_name}.")

    if formulae:
        objectives.append(f"✓ Solve numerical problems using key formulas ({len(formulae)} formula(s) identified).")

    if derivations:
        objectives.append(f"✓ Derive and verify fundamental mathematical equations for {topic_name}.")

    objectives.append(f"✓ Identify common exam misconceptions and practical applications of {topic_name}.")
    return objectives


def build_formula_index(formulae: List[str], variables: List[str]) -> List[Dict[str, Any]]:
    """Build structured formula index reusing exact extracted formulas."""
    index: List[Dict[str, Any]] = []
    for i, formula in enumerate(formulae, 1):
        index.append({
            "formula_number": i,
            "formula": str(formula).strip(),
            "variables": variables if i == 1 else [],
            "status": "extracted",
        })
    return index


# Subject-appropriate wording for the fallback prerequisite / dependency nodes.
# These strings previously said "Physical" for every book, so Biology and
# Mathematics chapters were told they depended on physics fundamentals.
_SUBJECT_FOUNDATIONS = {
    "Physics": ("Basic Physical Quantities & Units", "Fundamental Physical Principles & Definitions",
                "Core Definitions & Sign Conventions"),
    "Chemistry": ("Atomic Structure & Chemical Symbols", "Fundamental Chemical Principles & Definitions",
                  "Nomenclature & Balancing Conventions"),
    "Biology": ("Cell Structure & Basic Life Processes", "Fundamental Biological Principles & Definitions",
                "Biological Terminology & Classification"),
    "Mathematics": ("Number Systems & Basic Operations", "Fundamental Mathematical Definitions & Axioms",
                    "Notation & Algebraic Conventions"),
    "General Science": ("Basic Scientific Concepts", "Fundamental Principles & Definitions",
                        "Core Definitions & Conventions"),
}


def _foundations(subject: str) -> tuple:
    return _SUBJECT_FOUNDATIONS.get(subject, _SUBJECT_FOUNDATIONS["General Science"])


def build_prerequisite_graph(topic: str, prerequisites: List[str],
                             subject: str = "General Science") -> List[str]:
    """Generate prerequisite progression graph."""
    graph: List[str] = []
    if prerequisites:
        for p in prerequisites[:4]:
            graph.append(f"{p} ➔ {topic}")
    else:
        graph.append(f"{_foundations(subject)[0]} ➔ {topic}")
    return graph


def build_concept_dependency_graph(core_concepts: List[str], formulae: List[str],
                                   subject: str = "General Science") -> List[Dict[str, str]]:
    """Generate concept dependency relationships."""
    _, principles, conventions = _foundations(subject)
    deps: List[Dict[str, str]] = []
    for c in core_concepts[:3]:
        c_title = str(c)[:40].strip()
        deps.append({"concept": c_title, "depends_on": principles})
    for f in formulae[:2]:
        deps.append({"concept": f"Formula ({str(f)[:25]}...)", "depends_on": conventions})
    return deps


def extract_revision_keywords(definitions: List[str], core_concepts: List[str], formulae: List[str]) -> List[str]:
    """Extract revision keywords from definitions and concepts."""
    keywords: List[str] = []
    for d in definitions:
        first_word = str(d).split(":")[0].strip()
        if len(first_word) < 30 and first_word not in keywords:
            keywords.append(first_word)
    for c in core_concepts:
        short_c = str(c).split(".")[0].strip()
        if len(short_c) < 35 and short_c not in keywords:
            keywords.append(short_c)
    return keywords[:8]


def rank_misconceptions(misconceptions: List[str]) -> List[Dict[str, str]]:
    """Rank student misconceptions by priority."""
    ranked: List[Dict[str, str]] = []
    for i, m in enumerate(misconceptions, 1):
        ranked.append({
            "priority": f"High Priority #{i}",
            "misconception": str(m).strip(),
        })
    return ranked


def enrich_topic_analysis(
    analysis_data: Dict[str, Any],
    subject: str = "",
    source_char_count: int = 0,
) -> Dict[str, Any]:
    """Main entry point for Stage 2 Knowledge Enrichment.

    Enriches Stage 1 analysis with deterministic educational metadata.

    Args:
        analysis_data: the Stage 1 content analysis.
        subject: Physics/Chemistry/Biology/Mathematics. Inferred from the topic
            when omitted, so fallback wording matches the discipline.
        source_char_count: length of the SOURCE theory. Study-time estimates use
            this when supplied; without it the estimate is derived from the much
            shorter analysis text and collapses to the floor.
    """
    topic = str(analysis_data.get("topic") or "")
    definitions = [str(x) for x in (analysis_data.get("definitions") or [])]
    core_concepts = [str(x) for x in (analysis_data.get("core_concepts") or [])]
    formulae = [str(x) for x in (analysis_data.get("formulae") or [])]
    variables = [str(x) for x in (analysis_data.get("variables") or [])]
    derivations = [str(x) for x in (analysis_data.get("derivations") or [])]
    misconceptions = [str(x) for x in (analysis_data.get("common_mistakes") or [])]
    exam_points = [str(x) for x in (analysis_data.get("exam_points") or [])]
    memory_candidates = [str(x) for x in (analysis_data.get("memory_candidates") or [])]
    prerequisites = [str(x) for x in (analysis_data.get("prerequisites") or [])]

    full_text = " ".join(definitions + core_concepts + derivations)
    # Prefer the real source length; fall back to the analysis text.
    text_length = source_char_count or len(full_text)

    if not subject:
        from edu_pipeline.ai.services.content_quality import infer_subject
        subject = infer_subject(topic, full_text)

    # Heuristic calculations
    difficulty = calculate_difficulty(len(formulae), len(derivations), len(core_concepts))
    exam_importance = calculate_exam_importance(len(formulae), len(derivations), len(exam_points))
    study_time = calculate_study_time(text_length, len(formulae), len(derivations))
    objectives = generate_learning_objectives(topic, definitions, formulae, derivations, core_concepts)
    formula_idx = build_formula_index(formulae, variables)
    prereq_graph = build_prerequisite_graph(topic, prerequisites, subject)
    concept_deps = build_concept_dependency_graph(core_concepts, formulae, subject)
    keywords = extract_revision_keywords(definitions, core_concepts, formulae)
    ranked_misc = rank_misconceptions(misconceptions)
    selected_hook = memory_candidates[0] if memory_candidates else ""

    enriched = dict(analysis_data)
    enriched["enrichment"] = {
        "subject": subject,
        "difficulty": difficulty,
        "exam_importance": exam_importance,
        "estimated_study_time": study_time,
        "learning_objectives": objectives,
        "formula_index": formula_idx,
        "prerequisite_graph": prereq_graph,
        "concept_dependency_graph": concept_deps,
        "revision_keywords": keywords,
        "ranked_misconceptions": ranked_misc,
        "selected_memory_hook": selected_hook,
    }
    return enriched


class KnowledgeEnrichmentService:
    """Domain service wrapper for the deterministic enrichment stage.

    Exists so the enrichment stage is addressed the same way as the other AI
    domain services (``NotesService`` / ``MCQService``) even though it performs
    no model calls. ``enrich_topic_analysis`` remains the implementation and
    stays part of the public surface.
    """

    @staticmethod
    def enrich(analysis_data: Dict[str, Any], subject: str = "",
               source_char_count: int = 0) -> Dict[str, Any]:
        """Return the Stage 1 analysis enriched with educational metadata."""
        return enrich_topic_analysis(analysis_data, subject=subject,
                                     source_char_count=source_char_count)
