#!/usr/bin/env python3
"""AIService Facade entry point delegating to task-specific domain services."""

from __future__ import annotations

from typing import Any, Dict, Optional

from edu_pipeline.ai.services.mcq_service import MCQService
from edu_pipeline.ai.services.notes_service import NotesService


class AIService:
    """Facade entry point providing unified access to AI domain services."""

    @staticmethod
    def generate_mcq(
        question: str,
        answer: str,
        subject: str = "",
        chapter: str = "",
        question_type: str = "",
        provider_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delegate MCQ generation to MCQService."""
        return MCQService.generate_mcq(
            question=question,
            answer=answer,
            subject=subject,
            chapter=chapter,
            question_type=question_type,
            provider_name=provider_name,
        )

    @staticmethod
    def generate_notes(
        topic_title: str,
        theory_markdown: str,
        provider_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delegate study notes generation to NotesService."""
        return NotesService.generate_notes(
            topic_title=topic_title,
            theory_markdown=theory_markdown,
            provider_name=provider_name,
        )
