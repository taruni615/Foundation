"""Repository package for canonical educational content."""

from edu_pipeline.repository.models import BookRepository
from edu_pipeline.repository.service import RepositoryService

__all__ = ["BookRepository", "RepositoryService"]
