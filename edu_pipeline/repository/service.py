#!/usr/bin/env python3
"""RepositoryService providing loading, saving, validation, and querying for BookRepository."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from edu_pipeline.repository.models import BookRepository

# QA question sections present in topics[]
QA_SECTION_KEYS = (
    "illustrations",
    "check_your_knowledge_items",
    "textbook_exercises",
    "exercises",
    "examples",
)


class RepositoryService:
    """Service layer managing loading, saving, validation, and querying of BookRepository."""

    @staticmethod
    def resolve_path(path_or_slug: str, workspace_dir: Optional[str] = None) -> str:
        """Resolve a user argument or book slug into an absolute *_final.json path."""
        path_str = str(path_or_slug or "").strip()
        if os.path.isfile(path_str):
            return os.path.abspath(path_str)

        if not workspace_dir:
            from edu_pipeline.extraction.topic_extractor import OUTPUT_DIR
            workspace_dir = OUTPUT_DIR

        # Check workspace_dir/<slug>/<slug>_final.json
        candidate = os.path.join(workspace_dir, path_str, f"{path_str}_final.json")
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)

        # Check direct JSON file under workspace
        if not path_str.endswith(".json"):
            json_candidate = os.path.join(workspace_dir, path_str, f"{path_str}.json")
            if os.path.isfile(json_candidate):
                return os.path.abspath(json_candidate)

        raise FileNotFoundError(f"Could not resolve book repository path for: '{path_or_slug}'")

    @staticmethod
    def load(path_or_slug: str, workspace_dir: Optional[str] = None) -> BookRepository:
        """Load a *_final.json file into a BookRepository container."""
        resolved = RepositoryService.resolve_path(path_or_slug, workspace_dir)
        with open(resolved, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return BookRepository(raw_json=data, source_path=resolved)

    @staticmethod
    def save(repo: BookRepository, path: Optional[str] = None) -> str:
        """Save a BookRepository's raw_json back to disk."""
        target_path = path or repo.source_path
        if not target_path:
            raise ValueError("No save target path specified and BookRepository has no source_path.")

        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as handle:
            json.dump(repo.raw_json, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

        repo.source_path = target_path
        return target_path

    @staticmethod
    def reload(repo: BookRepository) -> BookRepository:
        """Reload the BookRepository from its source path."""
        if not repo.source_path or not os.path.isfile(repo.source_path):
            raise FileNotFoundError(f"Source file not available for reload: '{repo.source_path}'")
        return RepositoryService.load(repo.source_path)

    @staticmethod
    def validate(repo: BookRepository) -> Dict[str, Any]:
        """Validate the structural integrity of a BookRepository."""
        errors: List[str] = []
        warnings: List[str] = []

        if not repo.raw_json:
            errors.append("Repository raw_json is empty.")
        if not repo.metadata:
            warnings.append("Repository metadata is missing.")
        if not repo.topics:
            warnings.append("Repository contains no topics.")

        for i, topic in enumerate(repo.topics):
            if "topic_number" not in topic:
                warnings.append(f"Topic at index {i} missing 'topic_number'.")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "topic_count": len(repo.topics),
            "book_name": repo.metadata.get("name", "Unknown"),
        }

    @staticmethod
    def get_topics(repo: BookRepository) -> List[Dict[str, Any]]:
        """Return the list of topics in the repository."""
        return repo.topics

    @staticmethod
    def get_theory(repo: BookRepository) -> List[Dict[str, Any]]:
        """Extract and flatten all theory sections across all topics in the repository."""
        theory_list: List[Dict[str, Any]] = []
        for topic in repo.topics:
            topic_num = topic.get("topic_number")
            chapter_name = topic.get("chapter_name") or topic.get("topic_name") or ""
            sections = topic.get("theory_sections") or []
            for sec in sections:
                theory_item = dict(sec)
                theory_item["topic_number"] = topic_num
                theory_item["chapter_name"] = chapter_name
                theory_list.append(theory_item)
        return theory_list

    @staticmethod
    def get_questions(repo: BookRepository) -> List[Dict[str, Any]]:
        """Extract and flatten all question items across all topics in the repository."""
        questions_list: List[Dict[str, Any]] = []
        for topic in repo.topics:
            topic_num = topic.get("topic_number")
            chapter_name = topic.get("chapter_name") or topic.get("topic_name") or ""
            for key in QA_SECTION_KEYS:
                items = topic.get(key) or []
                for item in items:
                    if isinstance(item, dict):
                        q_item = dict(item)
                        q_item["section_key"] = key
                        q_item["topic_number"] = topic_num
                        q_item["chapter_name"] = chapter_name
                        questions_list.append(q_item)
        return questions_list

    @staticmethod
    def find_topic(repo: BookRepository, topic_number: int) -> Optional[Dict[str, Any]]:
        """Find and return a specific topic by topic_number."""
        for topic in repo.topics:
            if topic.get("topic_number") == topic_number:
                return topic
        return None

    @staticmethod
    def get_topic(repo: BookRepository, topic_number: int) -> Optional[Dict[str, Any]]:
        """Alias for find_topic."""
        return RepositoryService.find_topic(repo, topic_number)

    @staticmethod
    def find_question(repo: BookRepository, query: str) -> List[Dict[str, Any]]:
        """Search for questions containing query string in problem/question or solution/answer text."""
        query_lower = str(query or "").lower().strip()
        matched: List[Dict[str, Any]] = []
        if not query_lower:
            return matched

        for q in RepositoryService.get_questions(repo):
            combined_text = (
                str(q.get("question") or "") + " " +
                str(q.get("problem") or "") + " " +
                str(q.get("title") or "") + " " +
                str(q.get("answer") or "") + " " +
                str(q.get("solution") or "")
            ).lower()
            if query_lower in combined_text:
                matched.append(q)
        return matched

    @staticmethod
    def list_books(workspace_dir: Optional[str] = None) -> List[str]:
        """List all available book names in workspace that have a *_final.json."""
        if not workspace_dir:
            from edu_pipeline.extraction.topic_extractor import OUTPUT_DIR
            workspace_dir = OUTPUT_DIR

        books: List[str] = []
        if not os.path.isdir(workspace_dir):
            return books

        for name in sorted(os.listdir(workspace_dir)):
            final_path = os.path.join(workspace_dir, name, f"{name}_final.json")
            if os.path.isfile(final_path):
                books.append(name)
        return books
