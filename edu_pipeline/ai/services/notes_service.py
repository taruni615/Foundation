#!/usr/bin/env python3
"""Two-Stage Study Notes Generation Domain Service (Stage 1 Analysis -> Stage 2 Generation)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from edu_pipeline.ai.prompts.service import PromptService
from edu_pipeline.ai.providers.llm import OllamaLLMProvider
from edu_pipeline.shared.config import ConfigService
from edu_pipeline.shared.logger import PipelineLogger


class NotesService:
    """Domain service executing a 2-stage notes generation pipeline with model fallback (qwen3:14b -> qwen3:12b)."""

    @classmethod
    def analyze_content(
        cls,
        topic_title: str,
        theory_markdown: str,
        primary_model: str,
        fallback_model: str,
        base_url: str,
        timeout: int,
    ) -> Dict[str, Any]:
        """Stage 1: Exhaustive Content Analysis to produce a structured topic representation."""
        sys_prompt = PromptService.notes_analysis_system_prompt().text
        user_prompt = PromptService.notes_analysis_user_prompt(
            topic_title=topic_title,
            theory_markdown=theory_markdown,
        )

        # 1. Attempt Primary Model (qwen3:14b) for Stage 1
        primary_provider = OllamaLLMProvider(base_url=base_url, model=primary_model, timeout=timeout)
        try:
            PipelineLogger.info(f"[Stage 1 Analysis] Analyzing '{topic_title}' using primary model '{primary_model}'...")
            res = primary_provider.generate(
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
                json_format=True,
            )
            parsed = cls._parse_json(res.text)
            if parsed:
                return {"ok": True, "analysis": parsed, "model": primary_model, "fallback_used": False}
            PipelineLogger.warning(f"[Stage 1 Analysis] Primary model '{primary_model}' returned unparsable JSON. Triggering fallback...")
        except Exception as err:
            PipelineLogger.warning(f"[Stage 1 Analysis] Primary model '{primary_model}' failed: {err}. Triggering fallback to '{fallback_model}'...")

        # 2. Fallback Model Retry (qwen3:12b) for Stage 1
        fallback_provider = OllamaLLMProvider(base_url=base_url, model=fallback_model, timeout=timeout)
        try:
            PipelineLogger.info(f"[Stage 1 Analysis] Retrying analysis for '{topic_title}' using fallback model '{fallback_model}'...")
            res = fallback_provider.generate(
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
                json_format=True,
            )
            parsed = cls._parse_json(res.text)
            if parsed:
                return {"ok": True, "analysis": parsed, "model": fallback_model, "fallback_used": True}
        except Exception as fallback_err:
            PipelineLogger.error(f"[Stage 1 Analysis] Fallback model '{fallback_model}' also failed: {fallback_err}")

        # Basic structured fallback dict if both LLM calls fail for Stage 1
        return {
            "ok": True,
            "analysis": {
                "topic": topic_title,
                "core_concepts": [theory_markdown[:300]],
            },
            "model": "fallback_raw",
            "fallback_used": True,
        }

    @classmethod
    def generate_notes(
        cls,
        topic_title: str,
        theory_markdown: str,
        provider_name: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute the two-stage Notes generation pipeline (Stage 1 Analysis -> Stage 2 Generation)."""
        cfg = ConfigService.get().llm
        base_url = cfg.base_url
        timeout = cfg.timeout
        primary_model = model_override or cfg.notes_model
        fallback_model = cfg.notes_fallback_model

        # STAGE 1: Content Analysis
        analysis_res = cls.analyze_content(
            topic_title=topic_title,
            theory_markdown=theory_markdown,
            primary_model=primary_model,
            fallback_model=fallback_model,
            base_url=base_url,
            timeout=timeout,
        )
        analysis_data = analysis_res.get("analysis", {})

        # STAGE 2: Deterministic Knowledge Enrichment (No LLM calls)
        from edu_pipeline.ai.services.knowledge_enrichment import enrich_topic_analysis
        enriched_data = enrich_topic_analysis(analysis_data)
        analysis_json_str = json.dumps(enriched_data, indent=2, ensure_ascii=False)

        # STAGE 3: Notes Synthesis from Enriched Analysis Representation
        sys_prompt = PromptService.notes_system_prompt().text
        user_prompt = PromptService.notes_user_prompt(
            topic_title=topic_title,
            structured_analysis_json=analysis_json_str,
        )

        # Attempt Primary Model (qwen3:14b) for Stage 2
        primary_provider = OllamaLLMProvider(base_url=base_url, model=primary_model, timeout=timeout)
        try:
            PipelineLogger.info(f"[Stage 2 Generation] Synthesizing notes for '{topic_title}' using primary model '{primary_model}'...")
            res2 = primary_provider.generate(
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                json_format=False,
            )
            if res2 and res2.text.strip():
                return {
                    "ok": True,
                    "topic_title": topic_title,
                    "notes_markdown": res2.text.strip(),
                    "analysis": analysis_data,
                    "model": primary_model,
                    "fallback_used": analysis_res.get("fallback_used", False),
                    "response": res2,
                }
            PipelineLogger.warning(f"[Stage 2 Generation] Primary model '{primary_model}' returned empty output. Triggering fallback...")
        except Exception as primary_err:
            PipelineLogger.warning(
                f"[Stage 2 Generation] Primary model '{primary_model}' failed: {primary_err}. Triggering fallback to '{fallback_model}'..."
            )

        # Fallback Model Retry (qwen3:12b) for Stage 2
        fallback_provider = OllamaLLMProvider(base_url=base_url, model=fallback_model, timeout=timeout)
        try:
            PipelineLogger.info(f"[Stage 2 Generation] Retrying notes synthesis for '{topic_title}' using fallback model '{fallback_model}'...")
            res2 = fallback_provider.generate(
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                json_format=False,
            )
            return {
                "ok": True,
                "topic_title": topic_title,
                "notes_markdown": res2.text.strip(),
                "analysis": analysis_data,
                "model": fallback_model,
                "fallback_used": True,
                "response": res2,
            }
        except Exception as fallback_err:
            PipelineLogger.error(f"[Stage 2 Generation] Fallback model '{fallback_model}' also failed: {fallback_err}")
            return {
                "ok": False,
                "topic_title": topic_title,
                "error": f"Both primary ({primary_model}) and fallback ({fallback_model}) models failed during notes synthesis: {fallback_err}",
            }

    @staticmethod
    def _parse_json(text: str) -> Optional[Dict[str, Any]]:
        text_clean = text.strip()
        try:
            return json.loads(text_clean)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text_clean, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    return None
            return None
