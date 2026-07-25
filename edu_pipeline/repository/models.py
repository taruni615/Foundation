#!/usr/bin/env python3
"""Lightweight data container for educational book repositories.

Wraps the canonical v3.1 JSON data structure without modifying internal dictionaries.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class BookRepository:
    """Lightweight repository data container wrapping raw book JSON content."""

    def __init__(self, raw_json: Optional[Dict[str, Any]] = None, source_path: Optional[str] = None) -> None:
        self.raw_json: Dict[str, Any] = raw_json if raw_json is not None else {}
        self.source_path: Optional[str] = source_path
        self.metadata: Dict[str, Any] = self.raw_json.get("metadata", {})
        self.topics: List[Dict[str, Any]] = self.raw_json.get("topics", [])

    def __repr__(self) -> str:
        name = self.metadata.get("name", "Unknown Book")
        topic_count = len(self.topics)
        return f"<BookRepository(name='{name}', topics={topic_count}, path='{self.source_path}')>"
