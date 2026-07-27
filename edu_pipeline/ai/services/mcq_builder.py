#!/usr/bin/env python3
"""Question Bank Builder for merging, deduplicating, and balancing MCQs."""

from __future__ import annotations

import math
from typing import Any, Dict, List

from edu_pipeline.ai.services.mcq_validator import MCQValidator


class QuestionBankBuilder:
    """Merges, deduplicates, and balances converted and generated MCQs into a Question Bank."""

    @classmethod
    def deduplicate(cls, mcqs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove questions with duplicate stems or identical options."""
        unique_mcqs: List[Dict[str, Any]] = []
        seen_stems = set()

        for mcq in mcqs:
            stem = str(mcq.get("stem") or "").strip().lower()
            stem_normalized = "".join(c for c in stem if c.isalnum())
            if not stem_normalized or stem_normalized in seen_stems:
                continue
            seen_stems.add(stem_normalized)
            unique_mcqs.append(mcq)

        return unique_mcqs

    @classmethod
    def balance_answer_distribution(cls, mcqs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Permute options so correct answer index is evenly distributed across 0, 1, 2, 3 (A, B, C, D)."""
        balanced: List[Dict[str, Any]] = []

        for i, mcq in enumerate(mcqs):
            item = dict(mcq)
            options = list(item.get("options") or [])
            curr_idx = item.get("correct_index", 0)

            if len(options) == 4 and 0 <= curr_idx < 4:
                correct_text = options[curr_idx]
                target_idx = i % 4

                # Swap correct option into target position
                options[curr_idx], options[target_idx] = options[target_idx], options[curr_idx]
                item["options"] = options
                item["correct_index"] = target_idx

            balanced.append(item)

        return balanced

    @classmethod
    def _validated(cls, mcqs: List[Dict[str, Any]], origin: str) -> List[Dict[str, Any]]:
        """Validate items that have not been validated yet.

        Items arriving from MCQService already carry a ``metadata`` block. Re-
        running the validator on them re-derived that metadata from default
        arguments, silently downgrading planner-assigned difficulty and Bloom
        level (e.g. Hard/Analyze -> Medium/Apply). Already-clean items pass
        through untouched.
        """
        out: List[Dict[str, Any]] = []
        for mcq in mcqs:
            if isinstance(mcq, dict) and isinstance(mcq.get("metadata"), dict):
                out.append(mcq)
                continue
            ok, _errors, clean = MCQValidator.validate(mcq, origin=origin)
            if ok:
                out.append(clean)
        return out

    @classmethod
    def build_bank(
        cls,
        converted_mcqs: List[Dict[str, Any]],
        generated_mcqs: List[Dict[str, Any]],
        target_count: int = 10,
        converted_ratio: float = 0.4,
    ) -> List[Dict[str, Any]]:
        """Merge converted and generated MCQs into a balanced, validated Question Bank."""
        target_converted = math.floor(target_count * converted_ratio)
        target_generated = target_count - target_converted

        valid_converted = cls._validated(converted_mcqs, origin="converted")
        valid_generated = cls._validated(generated_mcqs, origin="generated")

        selected_converted = valid_converted[:target_converted]
        selected_generated = valid_generated[:target_generated]

        # Fill remaining count if one list is shorter
        remaining = target_count - len(selected_converted) - len(selected_generated)
        if remaining > 0:
            extra_gen = valid_generated[len(selected_generated):len(selected_generated) + remaining]
            selected_generated.extend(extra_gen)
            remaining = target_count - len(selected_converted) - len(selected_generated)
            if remaining > 0:
                extra_conv = valid_converted[len(selected_converted):len(selected_converted) + remaining]
                selected_converted.extend(extra_conv)

        combined = selected_converted + selected_generated
        deduped = cls.deduplicate(combined)
        final_bank = cls.balance_answer_distribution(deduped)

        return final_bank
