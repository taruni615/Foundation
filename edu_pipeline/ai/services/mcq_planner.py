#!/usr/bin/env python3
"""Shared Question Planner for Intelligent MCQ Engine.

Generates a balanced question plan across concepts, difficulty levels (30% Easy,
50% Medium, 20% Hard), Bloom's Taxonomy, and question types.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List

BLOOMS_TAXONOMY = ("Remember", "Understand", "Apply", "Analyze")

QUESTION_TYPES = (
    "Definition",
    "Conceptual",
    "Application",
    "Numerical",
    "Formula-Based",
    "Assertion–Reason",
    "Common Misconception",
    "Multi-Step Reasoning",
    "Real-Life Scenario",
)


@dataclass(frozen=True)
class QuestionPlanItem:
    """Individual planned question metadata item."""

    concept: str
    difficulty: str
    question_type: str
    blooms: str


class QuestionPlanner:
    """Generates balanced internal question plans for MCQ generation."""

    @classmethod
    def generate_plan(
        cls,
        topic_name: str,
        analysis_data: Dict[str, Any],
        target_count: int = 10,
        easy_pct: float = 0.3,
        medium_pct: float = 0.5,
        hard_pct: float = 0.2,
    ) -> List[QuestionPlanItem]:
        """Build a balanced list of QuestionPlanItem objects based on content analysis."""
        concepts = [str(c) for c in (analysis_data.get("core_concepts") or [])]
        if not concepts:
            concepts = [topic_name or "General Concept"]

        formulae = [str(f) for f in (analysis_data.get("formulae") or [])]
        derivations = [str(d) for d in (analysis_data.get("derivations") or [])]
        misconceptions = [str(m) for m in (analysis_data.get("common_mistakes") or [])]

        easy_count = max(1, math.floor(target_count * easy_pct))
        hard_count = max(1, math.floor(target_count * hard_pct))
        medium_count = max(1, target_count - easy_count - hard_count)

        difficulties = (
            ["Easy"] * easy_count +
            ["Medium"] * medium_count +
            ["Hard"] * hard_count
        )

        plan: List[QuestionPlanItem] = []
        for i in range(target_count):
            diff = difficulties[i if i < len(difficulties) else -1]
            concept = concepts[i % len(concepts)]

            if diff == "Easy":
                q_type = "Definition" if i % 2 == 0 else "Conceptual"
                blooms = "Remember" if i % 2 == 0 else "Understand"
            elif diff == "Medium":
                if formulae and i % 2 == 0:
                    q_type = "Formula-Based"
                    blooms = "Apply"
                elif misconceptions and i % 3 == 0:
                    q_type = "Common Misconception"
                    blooms = "Understand"
                else:
                    q_type = "Application"
                    blooms = "Apply"
            else:  # Hard
                if derivations and i % 2 == 0:
                    q_type = "Multi-Step Reasoning"
                    blooms = "Analyze"
                elif formulae:
                    q_type = "Numerical"
                    blooms = "Analyze"
                else:
                    q_type = "Assertion–Reason"
                    blooms = "Analyze"

            plan.append(QuestionPlanItem(
                concept=concept[:50],
                difficulty=diff,
                question_type=q_type,
                blooms=blooms,
            ))

        return plan
