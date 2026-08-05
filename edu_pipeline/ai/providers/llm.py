#!/usr/bin/env python3
"""LLMProvider interface and OllamaLLMProvider implementation."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import requests

from edu_pipeline.ai.providers.registry import ProviderRegistry
from edu_pipeline.ai.response import LLMResponse
from edu_pipeline.exceptions import ProviderError


class LLMProvider(ABC):
    """Abstract interface for LLM text generation providers."""

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: Optional[int] = None,
        json_format: bool = False,
    ) -> LLMResponse:
        """Generate text or JSON response from system and user prompts."""

    @abstractmethod
    def supports_json(self) -> bool:
        """Whether the provider supports native JSON mode."""

    @abstractmethod
    def supports_streaming(self) -> bool:
        """Whether the provider supports token streaming."""

    @abstractmethod
    def model_name(self) -> str:
        """Name of the active underlying model."""


class OllamaLLMProvider(LLMProvider):
    """Ollama implementation of LLMProvider interface."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3:8b",
        timeout: int = 1800,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._model = model
        self.timeout = timeout

    def model_name(self) -> str:
        return self._model

    def supports_json(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: Optional[int] = None,
        json_format: bool = False,
    ) -> LLMResponse:
        url = f"{self.base_url}/api/chat"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        import os
        num_ctx = int(os.environ.get("OLLAMA_NUM_CTX") or "32768")
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        if json_format:
            payload["format"] = "json"

        start_time = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            duration = time.time() - start_time

            msg = data.get("message") or {}
            content = msg.get("content") or ""
            eval_count = data.get("eval_count") or 0
            done_reason = data.get("done_reason") or "stop"

            return LLMResponse(
                text=content,
                raw=data,
                tokens=eval_count,
                model=self._model,
                finish_reason=done_reason,
                duration=duration,
            )
        except Exception as err:
            raise ProviderError(f"Ollama generation request failed ({self._model} @ {url}): {err}") from err


# Register default provider
ProviderRegistry.register_llm("ollama", OllamaLLMProvider)
