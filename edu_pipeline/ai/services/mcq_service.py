#!/usr/bin/env python3
"""MCQ Generation Domain Service."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from edu_pipeline.ai.model_manager import ModelManager
from edu_pipeline.ai.prompts.service import PromptService
from edu_pipeline.exceptions import AIError


class MCQService:
    """Domain service managing theory question to MCQ conversion."""

    @classmethod
    def generate_mcq(
        cls,
        question: str,
        answer: str,
        subject: str = "",
        chapter: str = "",
        question_type: str = "",
        provider_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convert a theory question and answer into a structured MCQ dictionary."""
        provider = ModelManager.get_llm_provider(provider_name)

        sys_prompt = PromptService.mcq_system_prompt().text
        user_prompt = PromptService.mcq_user_prompt(
            question=question,
            answer=answer,
            subject=subject,
            chapter=chapter,
            question_type=question_type,
        )

        response = provider.generate(
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
            json_format=True,
        )

        content = response.text.strip()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # Fallback regex extraction if raw JSON contained surrounding formatting
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                return {"ok": False, "error": "LLM response did not contain valid JSON."}
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError as err:
                return {"ok": False, "error": f"Failed to parse MCQ JSON: {err}"}

        # Validate required MCQ keys
        if not isinstance(parsed, dict) or "stem" not in parsed or "options" not in parsed:
            return {"ok": False, "error": "MCQ JSON missing required keys ('stem', 'options')."}

        return {"ok": True, "mcq": parsed, "response": response}
