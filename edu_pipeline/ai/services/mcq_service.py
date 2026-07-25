#!/usr/bin/env python3
"""Intelligent MCQ Engine Domain Service (Question Conversion + Question Generation + Question Bank Builder)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from edu_pipeline.ai.model_manager import ModelManager
from edu_pipeline.ai.prompts.service import PromptService
from edu_pipeline.ai.services.mcq_builder import QuestionBankBuilder
from edu_pipeline.ai.services.mcq_planner import QuestionPlanItem, QuestionPlanner
from edu_pipeline.ai.services.mcq_validator import MCQValidator
from edu_pipeline.exceptions import AIError
from edu_pipeline.shared.logger import PipelineLogger

QA_SECTION_KEYS = (
    "illustrations",
    "check_your_knowledge_items",
    "textbook_exercises",
    "exercises",
    "examples",
)


class MCQService:
    """Intelligent MCQ Engine managing Question Conversion, Generation, Planning, and Validation."""

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
        parsed = cls._parse_json(content)
        if not parsed:
            return {"ok": False, "error": "LLM response did not contain valid JSON."}

        is_valid, errors, clean_mcq = MCQValidator.validate(
            parsed,
            origin="converted",
            plan_concept=chapter or subject or "Theory Conversion",
            plan_type=question_type or "Conceptual",
        )
        if not is_valid:
            return {"ok": False, "error": f"Validation failed: {', '.join(errors)}"}

        return {"ok": True, "mcq": clean_mcq, "response": response}

    @classmethod
    def generate_new_mcq(
        cls,
        plan_item: QuestionPlanItem,
        analysis_data: Dict[str, Any],
        subject: str = "",
        chapter: str = "",
        provider_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Mode B: Generate a completely new MCQ from analyzed topic content and plan item."""
        provider = ModelManager.get_llm_provider(provider_name)

        formulae = ", ".join(str(f) for f in (analysis_data.get("formulae") or []))
        misconceptions = ", ".join(str(m) for m in (analysis_data.get("common_mistakes") or []))

        user_prompt = (
            f"Subject: {subject}\n"
            f"Chapter/Topic: {chapter or plan_item.concept}\n"
            f"Concept Target: {plan_item.concept}\n"
            f"Difficulty Level: {plan_item.difficulty}\n"
            f"Bloom's Taxonomy: {plan_item.blooms}\n"
            f"Question Type: {plan_item.question_type}\n"
            f"Available Formulas: {formulae or 'None'}\n"
            f"Known Student Misconceptions: {misconceptions or 'None'}\n\n"
            f"Generate a brand new, highly original IIT Foundation MCQ testing '{plan_item.concept}'."
        )

        sys_prompt = PromptService.mcq_system_prompt().text
        response = provider.generate(
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            temperature=0.4,
            json_format=True,
        )

        parsed = cls._parse_json(response.text)
        if not parsed:
            return {"ok": False, "error": "LLM output unparsable"}

        is_valid, errors, clean_mcq = MCQValidator.validate(
            parsed,
            origin="generated",
            plan_concept=plan_item.concept,
            plan_difficulty=plan_item.difficulty,
            plan_blooms=plan_item.blooms,
            plan_type=plan_item.question_type,
        )

        if not is_valid:
            return {"ok": False, "error": f"Validation failed: {', '.join(errors)}"}

        return {"ok": True, "mcq": clean_mcq, "response": response}

    @classmethod
    def build_question_bank_for_topic(
        cls,
        topic_doc: Dict[str, Any],
        analysis_data: Optional[Dict[str, Any]] = None,
        target_count: int = 10,
        converted_ratio: float = 0.4,
        subject: str = "",
        provider_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Build a balanced, validated Question Bank combining Mode A Conversion & Mode B Generation."""
        topic_number = topic_doc.get("topic_number", 1)
        chapter_name = topic_doc.get("chapter_name") or topic_doc.get("topic_name") or f"Topic {topic_number}"

        # 1. Mode A: Extract existing textbook questions for conversion
        existing_questions: List[Dict[str, Any]] = []
        for key in QA_SECTION_KEYS:
            items = topic_doc.get(key) or []
            for item in items:
                if isinstance(item, dict):
                    q_text = item.get("question") or item.get("problem") or ""
                    a_text = item.get("answer") or item.get("solution") or ""
                    if q_text:
                        existing_questions.append({
                            "question": q_text,
                            "answer": a_text,
                            "type": item.get("question_type") or item.get("type") or "Conceptual",
                        })

        converted_mcqs: List[Dict[str, Any]] = []
        for eq in existing_questions[:target_count]:
            res = cls.generate_mcq(
                question=eq["question"],
                answer=eq["answer"],
                subject=subject,
                chapter=chapter_name,
                question_type=eq["type"],
                provider_name=provider_name,
            )
            if res.get("ok") and "mcq" in res:
                converted_mcqs.append(res["mcq"])

        # 2. Mode B: Generate new MCQs via Question Planner
        analysis = analysis_data or {"core_concepts": [chapter_name]}
        plan = QuestionPlanner.generate_plan(
            topic_name=chapter_name,
            analysis_data=analysis,
            target_count=target_count,
        )

        generated_mcqs: List[Dict[str, Any]] = []
        for plan_item in plan:
            res_gen = cls.generate_new_mcq(
                plan_item=plan_item,
                analysis_data=analysis,
                subject=subject,
                chapter=chapter_name,
                provider_name=provider_name,
            )
            if res_gen.get("ok") and "mcq" in res_gen:
                generated_mcqs.append(res_gen["mcq"])

        # 3. Question Bank Builder: Merge, deduplicate, balance answer distribution
        final_bank = QuestionBankBuilder.build_bank(
            converted_mcqs=converted_mcqs,
            generated_mcqs=generated_mcqs,
            target_count=target_count,
            converted_ratio=converted_ratio,
        )

        return final_bank

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
