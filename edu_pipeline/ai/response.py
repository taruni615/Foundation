#!/usr/bin/env python3
"""Normalized LLM Response data container."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class LLMResponse:
    """Normalized response object returned by all LLMProviders."""

    text: str
    raw: Dict[str, Any] = field(default_factory=dict)
    tokens: int = 0
    model: str = ""
    finish_reason: str = "stop"
    duration: float = 0.0
