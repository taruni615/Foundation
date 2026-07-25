"""AI Provider package (LLM, Embedding, Registry)."""

from edu_pipeline.ai.providers.embedding import EmbeddingProvider, OllamaEmbeddingProvider
from edu_pipeline.ai.providers.llm import LLMProvider, OllamaLLMProvider
from edu_pipeline.ai.providers.registry import ProviderRegistry

__all__ = [
    "LLMProvider",
    "OllamaLLMProvider",
    "EmbeddingProvider",
    "OllamaEmbeddingProvider",
    "ProviderRegistry",
]
