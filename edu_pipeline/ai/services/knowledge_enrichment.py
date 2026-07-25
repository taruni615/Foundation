#!/usr/bin/env python3
"""Knowledge Enrichment Stage providing deterministic educational metadata heuristics for Study Notes.

Computes difficulty, exam importance, estimated study time, learning objectives,
formula index, prerequisite graph, concept dependency graph, revision keywords,
and misconception rankings without additional LLM calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class EnrichedEducationalMetadata:
    """Enriched educational metadata container derived deterministically."""

    learning_objectives: List[str]
    difficulty: str
    exam_importance: str
    estimated_study_time: str
    formula_index: List[Dict[str, Any]]
    prerequisite_graph: List[str]
    concept_dependency_graph: List[Dict[str, str]]
    revision_keywords: List[str]
    ranked_misconceptions: List[Dict[str, str]]
    selected_memory_hook: str


def calculate_difficulty(formula_count: int, derivation_count: int, concept_count: int) -> str:
    """Rule-based difficulty heuristic."""
    if derivation_count >= 1 or formula_count >= 3:
        return "🔴 Advanced"
    elif formula_count >= 1 or concept_count >= 4:
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
    """Rule-based study time calculation in minutes."""
    base_minutes = (text_length / 250) + (formula_count * 3) + (derivation_count * 5)
    rounded = max(10, min(45, round(base_minutes / 5) * 5))
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


def build_prerequisite_graph(topic: str, prerequisites: List[str]) -> List[str]:
    """Generate prerequisite progression graph."""
    graph: List[str] = []
    if prerequisites:
        for p in prerequisites[:4]:
            graph.append(f"{p} ➔ {topic}")
    else:
        graph.append(f"Basic Physical Concepts ➔ {topic}")
    return graph


def build_concept_dependency_graph(core_concepts: List[str], formulae: List[str]) -> List[Dict[str, str]]:
    """Generate concept dependency relationships."""
    deps: List[Dict[str, str]] = []
    for c in core_concepts[:3]:
        c_title = str(c)[:40].strip()
        deps.append({
            "concept": c_title,
            "depends_on": "Fundamental Physical Principles & Definitions",
        })
    for f in formulae[:2]:
        deps.append({
            "concept": f"Formula ({str(f)[:25]}...)",
            "depends_on": "Core Concept Definitions & Sign Conventions",
        })
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


def enrich_topic_analysis(analysis_data: Dict[str, Any]) -> Dict[str, Any]:
    """Main entry point for Stage 2 Knowledge Enrichment.

    Enriches Stage 1 analysis dictionary with deterministic educational metadata.
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
    text_length = len(full_text)

    # Heuristic calculations
    difficulty = calculate_difficulty(len(formulae), len(derivations), len(core_concepts))
    exam_importance = calculate_exam_importance(len(formulae), len(derivations), len(exam_points))
    study_time = calculate_study_time(text_length, len(formulae), len(derivations))
    objectives = generate_learning_objectives(topic, definitions, formulae, derivations, core_concepts)
    formula_idx = build_formula_index(formulae, variables)
    prereq_graph = build_prerequisite_graph(topic, prerequisites)
    concept_deps = build_concept_dependency_graph(core_concepts, formulae)
    keywords = extract_revision_keywords(definitions, core_concepts, formulae)
    ranked_misc = rank_misconceptions(misconceptions)
    selected_hook = memory_candidates[0] if memory_candidates else ""

    enriched = dict(analysis_data)
    enriched["enrichment"] = {
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
