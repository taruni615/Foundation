#!/usr/bin/env python3
"""Domain exceptions for edu_pipeline."""

from __future__ import annotations


class PipelineError(Exception):
    """Base exception for all edu_pipeline errors."""


class AIError(PipelineError):
    """Base exception for AI layer errors."""


class ProviderError(AIError):
    """AI provider failure or communication error."""


class ModelNotFoundError(ProviderError):
    """Requested model is missing or unavailable on the provider."""


class PromptError(AIError):
    """Prompt template or version loading error."""


class ConfigurationError(PipelineError):
    """Configuration loading or parsing error."""


class EmbeddingError(AIError):
    """Embedding generation error."""
