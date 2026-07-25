#!/usr/bin/env python3
"""Study Notes Generation Domain Service with model fallback (qwen3:14b -> qwen3:12b)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from edu_pipeline.ai.prompts.service import PromptService
from edu_pipeline.ai.providers.llm import OllamaLLMProvider
from edu_pipeline.shared.config import ConfigService
from edu_pipeline.shared.logger import PipelineLogger


class NotesService:
    """Domain service managing student study notes generation with automatic fallback."""

    @classmethod
    def generate_notes(
        cls,
        topic_title: str,
        theory_markdown: str,
        provider_name: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate structured IIT Foundation study notes from topic theory markdown.

        Tries primary model (qwen3:14b). If unavailable, errors out, or fails,
        retries automatically once using fallback model (qwen3:12b).
        """
        cfg = ConfigService.get().llm
        base_url = cfg.base_url
        timeout = cfg.timeout
        primary_model = model_override or cfg.notes_model
        fallback_model = cfg.notes_fallback_model

        sys_prompt = PromptService.notes_system_prompt().text
        user_prompt = PromptService.notes_user_prompt(
            topic_title=topic_title,
            theory_markdown=theory_markdown,
        )

        # 1. Attempt Primary Model (qwen3:14b)
        primary_provider = OllamaLLMProvider(base_url=base_url, model=primary_model, timeout=timeout)
        try:
            PipelineLogger.info(f"Generating study notes for '{topic_title}' using primary model '{primary_model}'...")
            response = primary_provider.generate(
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                json_format=False,
            )
            if response and response.text.strip():
                return {
                    "ok": True,
                    "topic_title": topic_title,
                    "notes_markdown": response.text.strip(),
                    "model": primary_model,
                    "fallback_used": False,
                    "response": response,
                }
            PipelineLogger.warning(f"Primary model '{primary_model}' returned empty text. Triggering fallback...")
        except Exception as primary_err:
            PipelineLogger.warning(
                f"Primary model '{primary_model}' failed for topic '{topic_title}': {primary_err}. Triggering fallback to '{fallback_model}'..."
            )

        # 2. Fallback Model Retry (qwen3:12b)
        fallback_provider = OllamaLLMProvider(base_url=base_url, model=fallback_model, timeout=timeout)
        try:
            PipelineLogger.info(f"Retrying study notes for '{topic_title}' using fallback model '{fallback_model}'...")
            response = fallback_provider.generate(
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                json_format=False,
            )
            return {
                "ok": True,
                "topic_title": topic_title,
                "notes_markdown": response.text.strip(),
                "model": fallback_model,
                "fallback_used": True,
                "response": response,
            }
        except Exception as fallback_err:
            PipelineLogger.error(f"Fallback model '{fallback_model}' also failed for topic '{topic_title}': {fallback_err}")
            return {
                "ok": False,
                "topic_title": topic_title,
                "error": f"Both primary ({primary_model}) and fallback ({fallback_model}) models failed: {fallback_err}",
            }
