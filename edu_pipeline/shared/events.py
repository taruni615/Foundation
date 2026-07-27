#!/usr/bin/env python3
"""Generic event bus and typed pipeline progress events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Type

from edu_pipeline.shared.logger import PipelineLogger


@dataclass(frozen=True)
class PipelineEvent:
    """Base class for all pipeline events."""
    task: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskStartedEvent(PipelineEvent):
    """Event emitted when a pipeline task starts."""


@dataclass(frozen=True)
class ProgressUpdatedEvent(PipelineEvent):
    """Event emitted when a task progress percentage or step updates."""
    progress: float = 0.0
    message: str = ""


@dataclass(frozen=True)
class TaskCompletedEvent(PipelineEvent):
    """Event emitted when a pipeline task completes successfully."""
    result_summary: str = ""


@dataclass(frozen=True)
class TaskFailedEvent(PipelineEvent):
    """Event emitted when a pipeline task encounters an error."""
    error_message: str = ""


class EventBus:
    """Lightweight in-memory event bus for subscribing and publishing pipeline events."""

    _subscribers: Dict[Type[PipelineEvent], List[Callable[[PipelineEvent], None]]] = {}

    @classmethod
    def subscribe(cls, event_type: Type[PipelineEvent], listener: Callable[[Any], None]) -> None:
        if event_type not in cls._subscribers:
            cls._subscribers[event_type] = []
        cls._subscribers[event_type].append(listener)

    @classmethod
    def publish(cls, event: PipelineEvent) -> None:
        event_type = type(event)
        for listener in cls._subscribers.get(event_type, []):
            try:
                listener(event)
            except Exception as err:
                PipelineLogger.error(f"Error in event listener for {event_type.__name__}: {err}")

    @classmethod
    def clear(cls) -> None:
        cls._subscribers.clear()
