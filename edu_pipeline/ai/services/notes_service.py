#!/usr/bin/env python3
"""Study Notes Generation Domain Service."""

from __future__ import annotations

from typing import Any, Dict, Optional

from edu_pipeline.ai.model_manager import ModelManager
from edu_pipeline.ai.prompts.service import PromptService


class NotesService:
    """Domain service managing student study notes generation from raw theory."""

    @classmethod
    def generate_notes(
        cls,
        topic_title: str,
        theory_markdown: str,
        provider_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate structured study notes from topic theory markdown."""
        provider = ModelManager.get_llm_provider(provider_name)

        sys_prompt = PromptService.notes_system_prompt().text
        user_prompt = PromptService.notes_user_prompt(
            topic_title=topic_title,
            theory_markdown=theory_markdown,
        )

        response = provider.generate(
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            temperature=0.4,
            json_format=False,
        )

        return {
            "ok": True,
            "topic_title": topic_title,
            "notes_markdown": response.text.strip(),
            "response": response,
        }
