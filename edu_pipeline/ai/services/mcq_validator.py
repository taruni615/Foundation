#!/usr/bin/env python3
"""MCQ Validation Stage and Metadata Attachment for Intelligent MCQ Engine."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from edu_pipeline.ai.services.content_quality import validate_mcq_quality

# Models often echo the "A) " scaffolding from the schema into the option text,
# which then renders as "A) A) ..." in the UI and breaks duplicate detection.
_OPTION_PREFIX_RE = re.compile(r"^\(?[A-Da-d1-4][\).]\s+")

# Difficulty -> (time per question, exam weighting). Derived from the RESOLVED
# difficulty, not from the planner's default, so the fields cannot contradict
# the difficulty printed beside them.
_DIFFICULTY_PROFILE = {
    "easy": ("45 sec", "★★★☆☆"),
    "medium": ("60 sec", "★★★★☆"),
    "hard": ("90 sec", "★★★★★"),
}


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

        # The author prompt may declare a source unconvertible (essay, diagram,
        # subjective). Honour that instead of forcing a fabricated question.
        if raw_mcq.get("convertible") is False:
            return False, ["Source declared not convertible to a fair single-answer MCQ."], {}

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
                opt_str = _OPTION_PREFIX_RE.sub("", str(opt).strip()).strip()
                cleaned_options.append(opt_str)

        if any(not o for o in cleaned_options):
            errors.append("One or more options are empty after normalisation.")

        # Check duplicate options (case-insensitively, after prefix stripping)
        unique_options = {o.lower() for o in cleaned_options}
        if len(unique_options) < len(cleaned_options):
            errors.append("Options contain duplicates.")

        if stem and re.search(r"(?m)^\s*\(?[a-d]\)\s+\S", stem):
            errors.append("Stem embeds its own lettered options.")

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
        difficulty = str(raw_mcq.get("difficulty") or plan_difficulty).strip()
        est_time, importance = _DIFFICULTY_PROFILE.get(
            difficulty.lower(), _DIFFICULTY_PROFILE["medium"]
        )

        cleaned_mcq = {
            "stem": stem,
            "options": cleaned_options,
            "correct_index": ci,
            "explanation": explanation,
            "metadata": {
                "concept": str(raw_mcq.get("concept") or plan_concept or "General").strip(),
                "difficulty": difficulty,
                "blooms": str(raw_mcq.get("blooms") or plan_blooms).strip(),
                "question_type": str(raw_mcq.get("question_type") or plan_type).strip(),
                "estimated_time": est_time,
                "exam_importance": importance,
                "origin": origin,
            },
        }

        # Educational (non-structural) review: recorded as warnings so a weak but
        # usable question is still returned, and reviewers can see why.
        quality = validate_mcq_quality(cleaned_mcq)
        if quality.warnings:
            cleaned_mcq["metadata"]["quality_warnings"] = quality.warnings
        if not quality.ok:
            return False, quality.errors, {}

        return True, [], cleaned_mcq
