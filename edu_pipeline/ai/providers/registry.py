#!/usr/bin/env python3
"""ProviderRegistry for dynamic LLM and Embedding provider discovery."""

from __future__ import annotations

from typing import Any, Dict, List, Type

from edu_pipeline.exceptions import ProviderError


class ProviderRegistry:
    """Registry managing available LLM and Embedding providers."""

    _llm_providers: Dict[str, Type[Any]] = {}
    _embedding_providers: Dict[str, Type[Any]] = {}

    @classmethod
    def register_llm(cls, name: str, provider_cls: Type[Any]) -> None:
        cls._llm_providers[name.lower()] = provider_cls

    @classmethod
    def register_embedding(cls, name: str, provider_cls: Type[Any]) -> None:
        cls._embedding_providers[name.lower()] = provider_cls

    @classmethod
    def get_llm(cls, name: str, **kwargs: Any) -> Any:
        key = (name or "ollama").lower()
        if key not in cls._llm_providers:
            raise ProviderError(f"LLM Provider '{name}' is not registered. Available: {list(cls._llm_providers.keys())}")
        return cls._llm_providers[key](**kwargs)

    @classmethod
    def get_embedding(cls, name: str, **kwargs: Any) -> Any:
        key = (name or "ollama").lower()
        if key not in cls._embedding_providers:
            raise ProviderError(f"Embedding Provider '{name}' is not registered. Available: {list(cls._embedding_providers.keys())}")
        return cls._embedding_providers[key](**kwargs)

    @classmethod
    def list_llm_providers(cls) -> List[str]:
        return sorted(list(cls._llm_providers.keys()))

    @classmethod
    def list_embedding_providers(cls) -> List[str]:
        return sorted(list(cls._embedding_providers.keys()))
