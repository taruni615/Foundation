#!/usr/bin/env python3
"""ModelManager lifecycle and health monitoring without automatic downloading."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional

import requests

from edu_pipeline.ai.providers.embedding import EmbeddingProvider
from edu_pipeline.ai.providers.llm import LLMProvider
from edu_pipeline.ai.providers.registry import ProviderRegistry
from edu_pipeline.exceptions import ModelNotFoundError
from edu_pipeline.shared.config import ConfigService


@dataclass(frozen=True)
class HealthStatus:
    """Structured health diagnostics result."""

    available: bool
    provider: str
    model: str
    latency_ms: float = 0.0
    error: str = ""


class ModelManager:
    """Manages AI model availability, health checks, and provider caching."""

    _llm_cache: Dict[str, LLMProvider] = {}
    _emb_cache: Dict[str, EmbeddingProvider] = {}

    @classmethod
    def get_llm_provider(cls, name: Optional[str] = None) -> LLMProvider:
        cfg = ConfigService.get().llm
        provider_name = (name or cfg.provider).lower()

        if provider_name not in cls._llm_cache:
            provider_inst = ProviderRegistry.get_llm(
                provider_name,
                base_url=cfg.base_url,
                model=cfg.model,
                timeout=cfg.timeout,
            )
            cls._llm_cache[provider_name] = provider_inst
        return cls._llm_cache[provider_name]

    @classmethod
    def get_embedding_provider(cls, name: Optional[str] = None) -> EmbeddingProvider:
        cfg = ConfigService.get().embedding
        provider_name = (name or cfg.provider).lower()

        if provider_name not in cls._emb_cache:
            provider_inst = ProviderRegistry.get_embedding(
                provider_name,
                base_url=cfg.base_url,
                model=cfg.model,
            )
            cls._emb_cache[provider_name] = provider_inst
        return cls._emb_cache[provider_name]

    @classmethod
    def health(cls, name: Optional[str] = None) -> HealthStatus:
        """Check provider health and latency."""
        cfg = ConfigService.get().llm
        provider_name = (name or cfg.provider).lower()
        base_url = cfg.base_url.rstrip("/")
        model = cfg.model

        start_time = time.time()
        try:
            resp = requests.get(f"{base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            latency = (time.time() - start_time) * 1000.0

            models_list = [m.get("name") for m in resp.json().get("models") or [] if isinstance(m, dict)]
            is_model_present = any(m == model or m.startswith(f"{model}:") for m in models_list)

            if not is_model_present:
                return HealthStatus(
                    available=False,
                    provider=provider_name,
                    model=model,
                    latency_ms=round(latency, 2),
                    error=f"Model '{model}' not found in Ollama local tag list.",
                )

            return HealthStatus(
                available=True,
                provider=provider_name,
                model=model,
                latency_ms=round(latency, 2),
            )
        except Exception as err:
            latency = (time.time() - start_time) * 1000.0
            return HealthStatus(
                available=False,
                provider=provider_name,
                model=model,
                latency_ms=round(latency, 2),
                error=str(err),
            )

    @classmethod
    def ensure_available(cls, name: Optional[str] = None) -> None:
        """Verify model availability or raise ModelNotFoundError."""
        status = cls.health(name)
        if not status.available:
            raise ModelNotFoundError(f"Model unavailable on provider '{status.provider}' ({status.model}): {status.error}")
