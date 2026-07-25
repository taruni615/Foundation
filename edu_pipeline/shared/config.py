#!/usr/bin/env python3
"""Immutable configuration service for edu_pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class DBConfig:
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "iit_foundation"


@dataclass(frozen=True)
class PathConfig:
    root_dir: str = ""
    workspace_dir: str = ""
    materials_dir: str = ""
    cache_dir: str = ""
    output_dir: str = ""


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "ollama"
    model: str = "qwen3:8b"
    notes_model: str = "qwen3:14b"
    notes_fallback_model: str = "qwen3:12b"
    base_url: str = "http://localhost:11434"
    timeout: int = 1800
    temperature: float = 0.4
    retries: int = 3


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "ollama"
    model: str = "nomic-embed-text"
    base_url: str = "http://localhost:11434"


@dataclass(frozen=True)
class AppConfig:
    app_port: int = 8000
    viewer_port: int = 8765
    db: DBConfig = field(default_factory=DBConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)


class ConfigService:
    """Immutable configuration provider loaded once at runtime."""

    _instance: Optional[AppConfig] = None

    @classmethod
    def get(cls) -> AppConfig:
        if cls._instance is None:
            cls._instance = cls._load_from_env()
        return cls._instance

    @classmethod
    def _load_from_env(cls) -> AppConfig:
        repo_root = str(Path(__file__).resolve().parent.parent.parent)
        workspace = os.environ.get("OUTPUT_DIR") or os.path.join(repo_root, "edu_pipeline", "workspace")

        db_cfg = DBConfig(
            host=os.environ.get("DB_HOST") or os.environ.get("MYSQL_HOST") or "localhost",
            port=int(os.environ.get("DB_PORT") or os.environ.get("MYSQL_PORT") or "3306"),
            user=os.environ.get("DB_USER") or os.environ.get("MYSQL_USER") or "root",
            password=os.environ.get("DB_PASSWORD") or os.environ.get("MYSQL_PASSWORD") or "",
            database=os.environ.get("DB_NAME") or os.environ.get("MYSQL_DATABASE") or "iit_foundation",
        )

        paths_cfg = PathConfig(
            root_dir=repo_root,
            workspace_dir=workspace,
            materials_dir=os.path.join(repo_root, "edu_pipeline", "materials"),
            cache_dir=os.path.join(repo_root, "edu_pipeline", "materials", "cache"),
            output_dir=workspace,
        )

        llm_cfg = LLMConfig(
            provider=os.environ.get("LLM_PROVIDER") or "ollama",
            model=os.environ.get("OLLAMA_MODEL") or os.environ.get("LLM_MODEL") or "qwen3:8b",
            notes_model=os.environ.get("NOTES_MODEL") or "qwen3:14b",
            notes_fallback_model=os.environ.get("NOTES_FALLBACK_MODEL") or "qwen3:12b",
            base_url=os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434",
            timeout=int(os.environ.get("LLM_TIMEOUT") or "1800"),
            temperature=float(os.environ.get("LLM_TEMPERATURE") or "0.4"),
        )

        emb_cfg = EmbeddingConfig(
            provider=os.environ.get("EMBEDDING_PROVIDER") or "ollama",
            model=os.environ.get("EMBEDDING_MODEL") or "nomic-embed-text",
            base_url=os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434",
        )

        return AppConfig(
            app_port=int(os.environ.get("APP_PORT") or "8000"),
            viewer_port=int(os.environ.get("VIEWER_PORT") or "8765"),
            db=db_cfg,
            paths=paths_cfg,
            llm=llm_cfg,
            embedding=emb_cfg,
        )
