#!/usr/bin/env python3
"""Measurable educational-quality metrics.

Deterministic and offline: everything is computed from artefacts already on
disk or in the database, so quality can be tracked over time without spending
model calls. Used by ``tools/quality/educational_report.py``.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List

from edu_pipeline.ai.services.content_quality import (
    contamination_ratio,
    detect_duplicate_concepts,
    infer_subject,
)
from edu_pipeline.repository.service import RepositoryService

BLOOM_LEVELS = ("Remember", "Understand", "Apply", "Analyze")


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


# ---------------------------------------------------------------------------
# Notes / theory metrics
# ---------------------------------------------------------------------------
def notes_metrics(document: Dict[str, Any]) -> Dict[str, Any]:
    """Coverage and cleanliness metrics for one book's theory and notes."""
    topics = document.get("topics") or []
    total = len(topics)

    with_theory = with_notes = with_enrichment = 0
    contamination: List[float] = []
    formula_total = formula_present = 0
    prereq_ok = revision_ok = 0
    study_minutes: List[int] = []
    difficulties: Counter = Counter()
    subjects: Counter = Counter()

    for topic in topics:
        theory = RepositoryService.get_topic_theory_text(topic)
        if len(theory.strip()) >= 40:
            with_theory += 1

        notes = str((topic.get("study_notes") or {}).get("notes_markdown") or topic.get("summary") or "")
        if len(notes.strip()) >= 200:
            with_notes += 1
            contamination.append(contamination_ratio(notes))

        enrichment = (topic.get("study_notes") or {}).get("enrichment") or {}
        if enrichment:
            with_enrichment += 1
            if enrichment.get("prerequisite_graph"):
                prereq_ok += 1
            if len(enrichment.get("revision_keywords") or []) >= 3:
                revision_ok += 1
            if enrichment.get("difficulty"):
                difficulties[enrichment["difficulty"]] += 1
            if enrichment.get("subject"):
                subjects[enrichment["subject"]] += 1
            minutes = re.match(r"(\d+)", str(enrichment.get("estimated_study_time") or ""))
            if minutes:
                study_minutes.append(int(minutes.group(1)))

            for entry in enrichment.get("formula_index") or []:
                formula_total += 1
                needle = re.sub(r"\s+", "", str(entry.get("formula") or ""))[:12].lower()
                if needle and needle in re.sub(r"\s+", "", notes).lower():
                    formula_present += 1

        if not subjects:
            subjects[infer_subject(str(topic.get("chapter_name") or ""), theory[:4000])] += 1

    return {
        "topics": total,
        "theory_coverage_pct": _pct(with_theory, total),
        "notes_coverage_pct": _pct(with_notes, total),
        "enrichment_coverage_pct": _pct(with_enrichment, total),
        "formula_coverage_pct": _pct(formula_present, formula_total),
        "formula_count": formula_total,
        "prerequisite_completeness_pct": _pct(prereq_ok, with_enrichment),
        "revision_density_pct": _pct(revision_ok, with_enrichment),
        "mean_contamination": round(sum(contamination) / len(contamination), 3) if contamination else 0.0,
        "mean_study_minutes": round(sum(study_minutes) / len(study_minutes), 1) if study_minutes else 0.0,
        "difficulty_distribution": dict(difficulties),
        "subject_distribution": dict(subjects),
    }


# ---------------------------------------------------------------------------
# Question metrics
# ---------------------------------------------------------------------------
_INLINE_OPT_RE = re.compile(r"(?m)(?:^|\n)\s*\(?[a-dA-D1-4][\).]\s+\S")

# Question text lives under different keys in the JSON documents (problem /
# solution) and in the database rows (question / answer).
_STEM_KEYS = ("question", "stem", "problem", "prompt_markdown", "problem_markdown", "prompt")
_ANSWER_KEYS = ("answer", "explanation", "solution", "solution_markdown")


def _field(item: Dict[str, Any], keys) -> str:
    for key in keys:
        value = item.get(key)
        if value:
            return str(value)
    return ""


def question_metrics(questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Diversity, coverage and explanation quality for a set of questions."""
    total = len(questions)
    if not total:
        return {"questions": 0}

    stems = [re.sub(r"\W+", "", _field(q, _STEM_KEYS).lower())[:120] for q in questions]
    unique = len({s for s in stems if s})

    types: Counter = Counter(
        str(q.get("question_type") or q.get("type") or "Unclassified") for q in questions
    )
    chapters: Counter = Counter(str(q.get("chapter_name") or q.get("topic_number") or "?")
                                for q in questions)

    explanations = [_field(q, _ANSWER_KEYS) for q in questions]
    adequate = sum(1 for e in explanations if len(e.strip()) >= 40)
    missing = sum(1 for e in explanations if not e.strip())
    embeds_options = sum(
        1 for q in questions if len(_INLINE_OPT_RE.findall(_field(q, _STEM_KEYS))) >= 2
    )

    # Chapter balance: 1.0 = perfectly even coverage across chapters.
    if chapters:
        share = [c / total for c in chapters.values()]
        even = 1 / len(chapters)
        balance = round(1 - sum(abs(s - even) for s in share) / 2, 3)
    else:
        balance = 0.0

    return {
        "questions": total,
        "unique_stem_pct": _pct(unique, total),
        "duplicate_pct": round(100 - _pct(unique, total), 1),
        "type_diversity": len(types),
        "type_distribution": dict(types.most_common()),
        "chapter_coverage": len(chapters),
        "chapter_balance": balance,
        "explanation_adequate_pct": _pct(adequate, total),
        "explanation_missing_pct": _pct(missing, total),
        "stem_embeds_options_pct": _pct(embeds_options, total),
    }


def mcq_bank_metrics(mcqs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bloom's, difficulty, answer-position and duplication for generated MCQs."""
    total = len(mcqs)
    if not total:
        return {"mcqs": 0}

    blooms: Counter = Counter()
    difficulty: Counter = Counter()
    concepts: Counter = Counter()
    positions: Counter = Counter()
    warned = 0

    for mcq in mcqs:
        meta = mcq.get("metadata") or {}
        blooms[meta.get("blooms", "Unknown")] += 1
        difficulty[meta.get("difficulty", "Unknown")] += 1
        concepts[meta.get("concept", "Unknown")] += 1
        positions[mcq.get("correct_index", -1)] += 1
        if meta.get("quality_warnings"):
            warned += 1

    # Answer-position balance: 1.0 = uniform across the four positions.
    ideal = total / 4
    position_balance = round(1 - sum(abs(positions.get(i, 0) - ideal) for i in range(4)) / (2 * total), 3)

    # Concept concentration: share held by the most-represented concept.
    top_share = _pct(concepts.most_common(1)[0][1], total) if concepts else 0.0

    return {
        "mcqs": total,
        "blooms_distribution": {b: blooms.get(b, 0) for b in BLOOM_LEVELS if blooms.get(b)},
        "blooms_coverage": sum(1 for b in BLOOM_LEVELS if blooms.get(b)),
        "difficulty_distribution": dict(difficulty),
        "distinct_concepts": len(concepts),
        "top_concept_share_pct": top_share,
        "answer_position_balance": position_balance,
        "near_duplicate_count": len(detect_duplicate_concepts(mcqs)),
        "quality_warning_pct": _pct(warned, total),
    }


def summarise(metrics: Dict[str, Any]) -> List[str]:
    """Turn a metrics dict into reviewer-facing findings."""
    findings: List[str] = []
    if metrics.get("theory_coverage_pct", 100) < 100:
        findings.append(f"Only {metrics['theory_coverage_pct']}% of topics have usable theory.")
    if metrics.get("mean_contamination", 0) > 0.15:
        findings.append(f"Notes still carry question-bank text (mean {metrics['mean_contamination']}).")
    if 0 < metrics.get("formula_count", 0) and metrics.get("formula_coverage_pct", 100) < 80:
        findings.append(f"Only {metrics['formula_coverage_pct']}% of source formulae reach the notes.")
    if metrics.get("duplicate_pct", 0) > 20:
        findings.append(f"{metrics['duplicate_pct']}% of questions are duplicate stems.")
    if metrics.get("explanation_adequate_pct", 100) < 60:
        findings.append(f"Only {metrics['explanation_adequate_pct']}% of answers are substantial.")
    if metrics.get("top_concept_share_pct", 0) > 40:
        findings.append(f"One concept holds {metrics['top_concept_share_pct']}% of the bank.")
    if metrics.get("answer_position_balance", 1) < 0.8:
        findings.append("Correct answers are unevenly distributed across positions.")
    return findings
