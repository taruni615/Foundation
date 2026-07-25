#!/usr/bin/env python3
"""MCQ Validation Stage and Metadata Attachment for Intelligent MCQ Engine."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


class MCQValidator:
    """Validates MCQs against strict quality rules and attaches internal metadata."""

    @classmethod
    def validate(
        cls,
        raw_mcq: Dict[str, Any],
        origin: str = "generated",
        plan_concept: str = "",
        plan_difficulty: str = "Medium",
        plan_blooms: str = "Apply",
        plan_type: str = "Conceptual",
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        """Validate an MCQ dictionary against quality checklist rules.

        Returns (is_valid, error_list, cleaned_mcq_with_metadata).
        """
        errors: List[str] = []
        if not isinstance(raw_mcq, dict):
            return False, ["MCQ payload must be a dictionary."], {}

        stem = str(raw_mcq.get("stem") or raw_mcq.get("question") or "").strip()
        options = raw_mcq.get("options") or []
        explanation = str(raw_mcq.get("explanation") or raw_mcq.get("answer") or "").strip()

        if not stem:
            errors.append("Missing question stem.")
        if not isinstance(options, list) or len(options) != 4:
            errors.append(f"Options count must be exactly 4 (got {len(options) if isinstance(options, list) else 0}).")

        cleaned_options: List[str] = []
        if isinstance(options, list):
            for opt in options:
                opt_str = str(opt).strip()
                cleaned_options.append(opt_str)

        # Check duplicate options
        unique_options = set(cleaned_options)
        if len(unique_options) < len(cleaned_options):
            errors.append("Options contain duplicates.")

        # Check forbidden option patterns ("All of the above", "None of the above")
        for opt in cleaned_options:
            opt_lower = opt.lower()
            if "all of the above" in opt_lower or "all the above" in opt_lower:
                errors.append("Option uses forbidden pattern 'All of the Above'.")
            if "none of the above" in opt_lower or "none of these" in opt_lower:
                errors.append("Option uses forbidden pattern 'None of the Above'.")

        # Correct index validation
        correct_idx = raw_mcq.get("correct_index")
        if correct_idx is None:
            correct_idx = raw_mcq.get("correct_option_index")
        try:
            ci = int(correct_idx)
            if not (0 <= ci < 4):
                errors.append(f"correct_index must be an integer between 0 and 3 (got {ci}).")
        except (TypeError, ValueError):
            errors.append("Missing or non-integer correct_index.")
            ci = 0

        if not explanation:
            explanation = "Refer to fundamental concepts for detailed reasoning."

        if errors:
            return False, errors, {}

        # Attach structured internal metadata
        cleaned_mcq = {
            "stem": stem,
            "options": cleaned_options,
            "correct_index": ci,
            "explanation": explanation,
            "metadata": {
                "concept": str(raw_mcq.get("concept") or plan_concept or "General").strip(),
                "difficulty": str(raw_mcq.get("difficulty") or plan_difficulty).strip(),
                "blooms": str(raw_mcq.get("blooms") or plan_blooms).strip(),
                "question_type": str(raw_mcq.get("question_type") or plan_type).strip(),
                "estimated_time": "45 sec" if plan_difficulty == "Easy" else ("60 sec" if plan_difficulty == "Medium" else "90 sec"),
                "exam_importance": "★★★★☆" if plan_difficulty == "Medium" else ("★★★★★" if plan_difficulty == "Hard" else "★★★☆☆"),
                "origin": origin,
            },
        }

        return True, [], cleaned_mcq
