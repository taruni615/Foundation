#!/usr/bin/env python3
"""Educational content quality: cleaning, validation and scoring.

Deterministic (no model calls). Two responsibilities:

1. **Cleaning** — strip question-bank material that the extractor leaves inside
   theory text. Measured across the four extracted books, 35 of 44 topic
   summaries contained exam directions ("DIRECTIONS (Qs. 20-23)"), numbered
   exercise stems or answer keys. Feeding that to the notes model produces notes
   that read like a question paper.

2. **Validation** — checks that target *learning* defects rather than
   formatting: hallucinated formulae, missing prerequisites, contradictory
   difficulty labels, terminology drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Question-bank contamination
# ---------------------------------------------------------------------------
# Each pattern marks the START of question-bank material inside theory text.
_QB_MARKERS = (
    r"DIRECTIONS\s*\(",
    r"This\s+section\s+contains\s+(?:multiple\s+choice|\d+)",
    r"^\s*ASSERTION\s*(?:&|AND|/)\s*REASON",
    r"^\s*(?:EXERCISE|EXERCISES|PRACTICE\s+(?:QUESTIONS|EXERCISE))\s*[-:]?\s*\d*\s*$",
    r"^\s*(?:ANSWER\s*KEY|ANSWERS)\s*[-:]?\s*$",
    r"^\s*(?:MULTIPLE\s+CHOICE\s+QUESTIONS|OBJECTIVE\s+QUESTIONS)\s*$",
    r"Qs?\.\s*\d+\s*(?:-|to)\s*\d+",
)
_QB_START_RE = re.compile("|".join(_QB_MARKERS), re.IGNORECASE | re.MULTILINE)

# A run of numbered stems each followed by lettered options = a question block.
_NUMBERED_STEM_RE = re.compile(r"(?m)^\s{0,3}\d{1,3}\.\s+\S")
_LETTERED_OPTION_RE = re.compile(r"(?m)^\s{0,6}\(?[a-dA-D]\)\s+\S")


def strip_question_bank(text: str, window: int = 10) -> str:
    """Remove question-bank material from theory text.

    Question blocks are usually *interleaved* with theory rather than appended,
    so this scans a sliding window and drops the contaminated regions instead of
    truncating at the first marker (truncation discarded whole chapters).

    Conservative: if the result would lose more than 85% of the source the
    original is returned, so a false positive can never starve the notes model.
    """
    if not text:
        return ""

    lines = text.split("\n")
    drop = [False] * len(lines)

    for i, line in enumerate(lines):
        # An explicit exam marker taints its own line and the block after it.
        if _QB_START_RE.search(line):
            for j in range(i, min(len(lines), i + window)):
                drop[j] = True

    # A dense run of numbered stems + lettered options is a question block.
    for i in range(len(lines)):
        chunk = lines[i : i + window]
        stems = sum(1 for ln in chunk if _NUMBERED_STEM_RE.match(ln))
        options = sum(1 for ln in chunk if _LETTERED_OPTION_RE.match(ln))
        if stems >= 2 and options >= 3:
            for j in range(i, min(len(lines), i + window)):
                drop[j] = True

    # Individually-obvious question lines anywhere.
    for i, line in enumerate(lines):
        if _LETTERED_OPTION_RE.match(line) or _QB_START_RE.search(line):
            drop[i] = True

    cleaned = "\n".join(ln for ln, drop_it in zip(lines, drop) if not drop_it)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if len(cleaned) < max(200, len(text.strip()) * 0.15):
        return text.strip()
    return cleaned


def contamination_ratio(text: str) -> float:
    """Fraction of lines that look like question-bank material (0.0 - 1.0)."""
    lines = [ln for ln in (text or "").split("\n") if ln.strip()]
    if not lines:
        return 0.0
    hits = sum(
        1
        for ln in lines
        if _QB_START_RE.search(ln) or _NUMBERED_STEM_RE.match(ln) or _LETTERED_OPTION_RE.match(ln)
    )
    return hits / len(lines)


# ---------------------------------------------------------------------------
# Subject inference (drives subject-appropriate enrichment wording)
# ---------------------------------------------------------------------------
_SUBJECT_SIGNALS = {
    "Physics": ("force", "velocity", "magnet", "lens", "refraction", "reflection",
                "circuit", "momentum", "resistance", "ohm", "electric current",
                "wavelength", "optics", "friction", "gravitation"),
    "Chemistry": ("chemical", "acid", "alkali", "salt", "valency", "oxidation",
                  "reduction", "periodic table", "hydrocarbon", "carbon compound",
                  "metallurgy", "electrolysis", "mole ", "isotope", "corrosion",
                  "metals and non-metals", "non-metal", "compound"),
    "Biology": ("cell", "tissue", "organ", "photosynthesis", "respiration", "gene",
                "heredity", "nutrition", "digest", "blood", "species", "hormone",
                "reproduction", "ecosystem", "chromosome", "life process",
                "control and coordination", "excretion", "transportation"),
    "Mathematics": ("theorem", "polynomial", "triangle", "probability", "quadratic",
                    "trigonometr", "arithmetic progression", "geometry", "algebra",
                    "hcf", "lcm", "euclid", "real number", "coordinate", "mensuration"),
}

# The title is a far stronger signal than body prose, where shared vocabulary
# ("equation", "energy", "reaction") appears across every subject.
_TITLE_WEIGHT = 25


def infer_subject(topic: str, text: str = "") -> str:
    """Best-effort subject label from topic title and body text.

    Enrichment previously hard-coded physics wording ("Basic Physical Concepts")
    into prerequisite graphs for every book, including Biology and Mathematics.
    """
    title = str(topic or "").lower()
    body = str(text or "").lower()
    scores = {
        subject: _TITLE_WEIGHT * sum(signal in title for signal in signals)
        + sum(body.count(signal) for signal in signals)
        for subject, signals in _SUBJECT_SIGNALS.items()
    }
    best = max(scores, key=lambda s: scores[s])
    return best if scores[best] > 0 else "General Science"


# ---------------------------------------------------------------------------
# Educational validation
# ---------------------------------------------------------------------------
@dataclass
class ValidationReport:
    """Outcome of validating one generated artefact."""

    ok: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.errors.append(message)
        self.ok = False

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "errors": list(self.errors), "warnings": list(self.warnings)}


_FORMULA_TOKEN_RE = re.compile(r"[A-Za-z]\s*=|\\frac|<math|\^|_\{")


def _normalise_formula(formula: str) -> str:
    return re.sub(r"\s+", "", str(formula or "")).lower()


def validate_notes(notes_markdown: str, analysis: Dict[str, Any]) -> ValidationReport:
    """Validate generated notes against the analysis they were derived from.

    Catches the failure modes that matter educationally: invented formulae,
    dropped source formulae, missing required sections, and self-contradiction
    between the stated difficulty and the computed one.
    """
    report = ValidationReport()
    text = notes_markdown or ""

    if len(text.strip()) < 200:
        report.error("Notes are too short to be useful (under 200 characters).")

    required = ("Quick Summary", "Detailed Explanation", "Points to Remember")
    for section in required:
        if section.lower() not in text.lower():
            report.error(f"Missing required section: {section}.")

    source_formulae = [f for f in (analysis.get("formulae") or []) if str(f).strip()]
    if source_formulae:
        present = sum(1 for f in source_formulae if _normalise_formula(f)[:12] in _normalise_formula(text))
        if present == 0:
            report.error(
                f"None of the {len(source_formulae)} extracted formula(e) appear in the notes."
            )
        elif present < len(source_formulae):
            report.warn(f"Only {present}/{len(source_formulae)} source formulae carried through.")
        if "Formula Section" not in text:
            report.warn("Source has formulae but the notes omit the Formula Section.")

    if (analysis.get("derivations") or []) and "Derivation" not in text:
        report.warn("Source has derivations but the notes omit the Derivation Section.")

    enrichment = analysis.get("enrichment") or {}
    computed = enrichment.get("difficulty")
    if computed:
        wanted = computed.split()[-1]
        others = {"Easy", "Medium", "Advanced"} - {wanted}
        stated = re.search(r"\*\*Difficulty Level:\*\*\s*(.+)", text)
        if stated and any(o in stated.group(1) for o in others):
            report.warn(
                f"Notes state difficulty {stated.group(1).strip()!r} but enrichment computed {computed!r}."
            )

    if contamination_ratio(text) > 0.25:
        report.error("Notes contain question-bank material (exam directions or numbered stems).")

    return report


_HEDGE_RE = re.compile(
    r"\b(?:might be|may be|possibly|perhaps|I think|it seems|probably|not sure)\b", re.IGNORECASE
)


def validate_mcq_quality(mcq: Dict[str, Any]) -> ValidationReport:
    """Educational (not structural) checks on a single MCQ.

    Structural rules stay in MCQValidator; this layer catches the defects that
    make a *technically valid* question pedagogically weak.
    """
    report = ValidationReport()
    stem = str(mcq.get("stem") or "")
    options = [str(o) for o in (mcq.get("options") or [])]
    explanation = str(mcq.get("explanation") or "")

    if len(stem.strip()) < 15:
        report.error("Stem is too short to pose a real question.")
    if stem.strip().lower().startswith(("which of the following is true", "which is correct")) and len(stem) < 60:
        report.warn("Stem is generic; prefer a concept-specific question.")

    if options:
        try:
            correct = options[int(mcq.get("correct_index", 0))]
        except (ValueError, TypeError, IndexError):
            correct = ""
        if correct:
            lengths = [len(o) for o in options]
            # A correct option far longer than every distractor is guessable
            # without knowing the concept.
            if len(correct) == max(lengths) and len(correct) > 1.6 * (
                sum(lengths) - len(correct)
            ) / max(1, len(options) - 1):
                report.warn("Correct option is markedly longer than the distractors (length cue).")

        lowered = [o.strip().lower() for o in options]
        if len(set(lowered)) < len(lowered):
            report.error("Options are not mutually distinct.")
        if any(len(o.strip()) < 1 for o in options):
            report.error("An option is empty.")

    if len(explanation.strip()) < 25:
        report.warn("Explanation is too brief to teach the underlying concept.")
    if _HEDGE_RE.search(explanation):
        report.warn("Explanation hedges; MCQ rationales should be definite.")

    return report


def detect_duplicate_concepts(mcqs: List[Dict[str, Any]], threshold: float = 0.75) -> List[Dict[str, Any]]:
    """Flag near-duplicate stems that survive exact-match deduplication.

    The bank currently holds 51.5% exact-duplicate stems; near-duplicates on top
    of that make a paper feel repetitive even after exact dedup.
    """
    def tokens(text: str) -> set:
        return set(re.findall(r"[a-z0-9]+", str(text or "").lower())) - {
            "the", "a", "an", "of", "is", "are", "what", "which", "in", "to", "for", "and",
        }

    flagged: List[Dict[str, Any]] = []
    seen: List[tuple] = []
    for index, mcq in enumerate(mcqs):
        current = tokens(mcq.get("stem"))
        if not current:
            continue
        for prior_index, prior in seen:
            union = current | prior
            if union and len(current & prior) / len(union) >= threshold:
                flagged.append({"index": index, "duplicate_of": prior_index,
                                "stem": str(mcq.get("stem"))[:80]})
                break
        seen.append((index, current))
    return flagged
