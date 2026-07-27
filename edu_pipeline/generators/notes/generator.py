#!/usr/bin/env python3
"""Short-notes-only pipeline.

A focused, standalone entry point that does ONE thing: generate the structured
"short notes" (study notes) for a book and write nothing else. It deliberately
ignores all question content (examples, exercises, case studies, the QA table)
and never rewrites ``*_final.json``.

It is a thin orchestrator over the proven helpers already living in
``topicwise_pipeline.py`` -- no extraction/parsing/summarisation logic is
duplicated here. Theory is taken from an already-extracted ``*_final.json`` (the
heavy PDF -> Mathpix -> theory work is a separate concern handled by the main
pipeline); this script only turns that theory into short notes.

Notes follow the agreed architecture:

    Chapter Introduction -> Prerequisites -> Topic Loop
    (Metadata -> Learning -> Reinforcement -> Formula -> Derivation)
    -> Periodic Quick Revision -> Chapter Revision Toolkit

Output (and ONLY this) per book, under ``outputs/<book>/``:
    * ``<book>_study_notes.json``        -- merged short-notes document
    * ``topics_study_notes/topic_NN.json`` -- one self-describing file per topic

Usage:
    python3 short_notes_pipeline.py "10 PHYSICS FOUNDATION"
    python3 short_notes_pipeline.py outputs/<book>/<book>_final.json --topics 1,2
    python3 short_notes_pipeline.py --list
"""

from __future__ import annotations

import argparse
import os
from typing import List, Optional

# Short notes are text-only and always use the rich layout. Lock these in BEFORE
# importing the pipeline so the module-level toggles are read correctly.
os.environ.setdefault("SUMMARY_RICH_FORMAT", "1")  # rich study-notes layout
os.environ.setdefault("SKIP_IMAGES", "1")          # notes are text-only
os.environ["LLM_SUMMARY"] = "1"                     # we want LLM short notes
os.environ["FORCE_SUMMARY"] = "1"                   # always (re)generate

# Reuse the existing, tested building blocks -- nothing is re-implemented here.
from edu_pipeline.extraction.topic_extractor import (  # noqa: E402
    OUTPUT_DIR,
    export_study_notes_sidecars,
    parse_topic_number_filter,
    study_notes_json_path_from_final,
    _study_notes_topics_dir_from_final,
)


from edu_pipeline.ai.services.content_quality import (
    infer_subject,
    strip_question_bank,
    validate_notes,
)
from edu_pipeline.repository import BookRepository, RepositoryService


def list_books() -> List[str]:
    """Return book folders under outputs/ that have a *_final.json to read from."""
    return RepositoryService.list_books(OUTPUT_DIR)


def resolve_final_json(book_arg: str) -> Optional[str]:
    """Resolve a user argument to a *_final.json path."""
    try:
        return RepositoryService.resolve_path(book_arg, OUTPUT_DIR)
    except FileNotFoundError:
        return None


def generate_short_notes(
    target: str | BookRepository,
    *,
    topic_filter: Optional[set] = None,
) -> Optional[str]:
    """Generate short notes for one book and write ONLY the study-notes files.

    Reads theory from a BookRepository or final_json_path (never rewrites it),
    produces the rich study notes per topic via the existing summariser, and
    persists them through the existing sidecar exporter. Returns the merged
    study-notes path, or None.
    """
    if isinstance(target, BookRepository):
        repo = target
    else:
        resolved_path = resolve_final_json(target)
        if not resolved_path:
            raise FileNotFoundError(f"Could not resolve book JSON for: '{target}'")
        repo = RepositoryService.load(resolved_path)

    document = repo.raw_json
    final_json_path = repo.source_path or ""

    book_slug = os.path.basename(final_json_path).replace("_final.json", "") if final_json_path else repo.metadata.get("name", "book")
    topics = RepositoryService.get_topics(repo)
    print(f"Book: {book_slug}  ({len(topics)} topic(s) in {final_json_path or 'repository'})")

    made = 0
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        tn = int(topic.get("topic_number") or 0)
        if topic_filter and tn not in topic_filter:
            continue
        name = topic.get("chapter_name") or topic.get("topic_name") or f"Topic {tn}"
        print(f"  Short notes — topic {tn}: {name}")

        raw_theory = RepositoryService.get_topic_theory_text(topic)
        theory_text = strip_question_bank(raw_theory)

        if len(theory_text.strip()) < 40:
            print(f"    Warning: no usable theory for topic {tn}; skipping.")
            continue
        removed = len(raw_theory) - len(theory_text)
        if removed > 0:
            print(f"    Removed {removed} chars of question-bank text from the source.")

        # Infer the subject from the real chapter name and source text rather
        # than from the model's echoed "topic" field, so discipline-specific
        # wording never depends on model output.
        subject = infer_subject(name, theory_text[:8000])

        from edu_pipeline.ai import NotesService
        res = NotesService.generate_notes(name, theory_text, subject=subject)
        if res.get("ok"):
            notes_md = res.get("notes_markdown") or ""
            analysis = res.get("analysis") or {}
            validation = validate_notes(notes_md, analysis)
            if not validation.ok:
                print(f"    Quality check: {'; '.join(validation.errors)}")
            for warning in validation.warnings:
                print(f"    Note: {warning}")

            topic["summary"] = notes_md
            topic["summary_source"] = "student_llm"
            topic["study_notes"] = {
                "topic_number": tn,
                "topic_name": name,
                "model_used": res.get("model", "qwen3:14b"),
                "fallback_used": res.get("fallback_used", False),
                "notes_markdown": notes_md,
                # Persist the deterministic metadata so downstream consumers
                # (viewer, exports, metrics) can use it without re-deriving.
                "enrichment": analysis.get("enrichment", {}),
                "quality": validation.as_dict(),
            }
            made += 1

    if not made and not (topic_filter is None):
        print("  No new short notes generated for the requested topics.")

    # Persist ONLY the study-notes files. export_study_notes_sidecars pops
    # study_notes off the in-memory topics and writes the standalone per-topic +
    # merged files. We never save the (mutated) document, so *_final.json and the
    # QA table are left completely untouched.
    topics_dir = _study_notes_topics_dir_from_final(final_json_path)
    merged_path = study_notes_json_path_from_final(final_json_path)
    written = export_study_notes_sidecars(
        document,
        book_slug,
        topics_dir,
        merged_path,
        source_final_path=final_json_path,
    )
    if written:
        print(f"\nSaved short notes: {written}")
        print(f"Per-topic notes : {topics_dir}/topic_NN.json")
    else:
        print("\nNo short notes were written.")
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate ONLY the structured short notes for a book "
                    "(theory -> study notes; no questions, no QA table).",
    )
    parser.add_argument(
        "book",
        nargs="?",
        default=None,
        help="Book name (folder under outputs/) or path to a *_final.json",
    )
    parser.add_argument(
        "--topics",
        default=None,
        help="Comma-separated topic numbers to generate (e.g. 1,2,3)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List books that have an extracted *_final.json and exit",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.list or not args.book:
        books = list_books()
        if books:
            print("Books available for short-notes generation:")
            for b in books:
                print(f"  - {b}")
        else:
            print(f"No extracted books found under {OUTPUT_DIR}/.")
        if not args.book:
            if not args.list:
                print("\nPass a book name or *_final.json path to generate notes.")
            return

    final_json_path = resolve_final_json(args.book)
    if not final_json_path:
        print(f"Could not find a *_final.json for: {args.book}")
        print("Use --list to see available books.")
        raise SystemExit(1)

    topic_filter = parse_topic_number_filter(args.topics)
    if topic_filter:
        print(f"Topics filter: {sorted(topic_filter)}")
    generate_short_notes(final_json_path, topic_filter=topic_filter)


if __name__ == "__main__":
    main()
