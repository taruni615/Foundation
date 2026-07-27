"""AI Layer package for edu_pipeline."""

from edu_pipeline.ai.facade import AIService
from edu_pipeline.ai.model_manager import HealthStatus, ModelManager
from edu_pipeline.ai.prompts.service import PromptService, PromptTemplate
from edu_pipeline.ai.providers.embedding import EmbeddingProvider, OllamaEmbeddingProvider
from edu_pipeline.ai.providers.llm import LLMProvider, OllamaLLMProvider
from edu_pipeline.ai.providers.registry import ProviderRegistry
from edu_pipeline.ai.response import LLMResponse
from edu_pipeline.ai.services.knowledge_enrichment import KnowledgeEnrichmentService
from edu_pipeline.ai.services.mcq_service import MCQService
from edu_pipeline.ai.services.notes_service import NotesService

__all__ = [
    "AIService",
    "MCQService",
    "NotesService",
    "KnowledgeEnrichmentService",
    "ModelManager",
    "HealthStatus",
    "PromptService",
    "PromptTemplate",
    "LLMResponse",
    "ProviderRegistry",
    "LLMProvider",
    "OllamaLLMProvider",
    "EmbeddingProvider",
    "OllamaEmbeddingProvider",
]
