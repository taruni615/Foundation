#!/usr/bin/env python3
"""Prompt Version Manager and PromptService."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict

from edu_pipeline.exceptions import PromptError

PROMPTS_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass(frozen=True)
class PromptTemplate:
    """Immutable prompt template container with version metadata."""

    name: str
    version: str
    text: str

    def format(self, **kwargs: str) -> str:
        """Format prompt text with template kwargs."""
        try:
            return self.text.format(**kwargs)
        except KeyError as err:
            raise PromptError(f"Missing required key '{err}' when formatting prompt '{self.name}' ({self.version})") from err


class PromptService:
    """Prompt Version Manager serving versioned text prompt templates."""

    _cache: Dict[str, PromptTemplate] = {}

    @classmethod
    def get_template(cls, name: str, version: str = "v1") -> PromptTemplate:
        cache_key = f"{version}/{name}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        file_path = os.path.join(PROMPTS_DIR, version, f"{name}.txt")
        if not os.path.isfile(file_path):
            raise PromptError(f"Prompt template file not found: '{file_path}'")

        with open(file_path, "r", encoding="utf-8") as handle:
            content = handle.read()

        template = PromptTemplate(name=name, version=version, text=content)
        cls._cache[cache_key] = template
        return template

    @classmethod
    def mcq_system_prompt(cls, version: str = "v1") -> PromptTemplate:
        return cls.get_template("mcq_system", version)

    @classmethod
    def mcq_user_prompt(cls, question: str, answer: str, subject: str = "", chapter: str = "", question_type: str = "", version: str = "v1") -> str:
        tmpl = cls.get_template("mcq_user", version)
        return tmpl.format(
            question=question or "",
            answer=answer or "",
            subject=subject or "",
            chapter=chapter or "",
            question_type=question_type or "",
        )

    @classmethod
    def notes_analysis_system_prompt(cls, version: str = "v1") -> PromptTemplate:
        return cls.get_template("notes_analysis_system", version)

    @classmethod
    def notes_analysis_user_prompt(cls, topic_title: str, theory_markdown: str, version: str = "v1") -> str:
        tmpl = cls.get_template("notes_analysis_user", version)
        return tmpl.format(
            topic_title=topic_title or "",
            theory_markdown=theory_markdown or "",
        )

    @classmethod
    def notes_system_prompt(cls, version: str = "v1") -> PromptTemplate:
        return cls.get_template("notes_system", version)

    @classmethod
    def notes_user_prompt(cls, topic_title: str, structured_analysis_json: str, version: str = "v1") -> str:
        tmpl = cls.get_template("notes_user", version)
        return tmpl.format(
            topic_title=topic_title or "",
            structured_analysis_json=structured_analysis_json or "{}",
        )
