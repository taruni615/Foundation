#!/usr/bin/env python3
"""EmbeddingProvider interface and OllamaEmbeddingProvider implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

import requests

from edu_pipeline.ai.providers.registry import ProviderRegistry
from edu_pipeline.exceptions import EmbeddingError


class EmbeddingProvider(ABC):
    """Abstract interface for text embedding providers."""

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Embed a single text string into a vector float list."""

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of text strings into vector float lists."""

    @abstractmethod
    def model_name(self) -> str:
        """Name of the active embedding model."""


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama implementation of EmbeddingProvider interface."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._model = model
        self.timeout = timeout

    def model_name(self) -> str:
        return self._model

    def embed(self, text: str) -> List[float]:
        url = f"{self.base_url}/api/embeddings"
        payload = {"model": self._model, "prompt": text}
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get("embedding") or []
        except Exception as err:
            raise EmbeddingError(f"Ollama embedding failed ({self._model} @ {url}): {err}") from err

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(t) for t in texts]


# Register default embedding provider
ProviderRegistry.register_embedding("ollama", OllamaEmbeddingProvider)
