"""Shared utilities for edu_pipeline (config, logging, events)."""

from edu_pipeline.shared.config import AppConfig, ConfigService
from edu_pipeline.shared.constants import QA_SECTION_KEYS
from edu_pipeline.shared.events import (
    EventBus,
    PipelineEvent,
    ProgressUpdatedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskStartedEvent,
)
from edu_pipeline.shared.json_utils import extract_json_object
from edu_pipeline.shared.logger import PipelineLogger
from edu_pipeline.shared.paths import PACKAGE_ROOT, PROJECT_ROOT, load_dotenv

__all__ = [
    "AppConfig",
    "ConfigService",
    "QA_SECTION_KEYS",
    "extract_json_object",
    "PACKAGE_ROOT",
    "PROJECT_ROOT",
    "load_dotenv",
    "PipelineLogger",
    "EventBus",
    "PipelineEvent",
    "TaskStartedEvent",
    "ProgressUpdatedEvent",
    "TaskCompletedEvent",
    "TaskFailedEvent",
]
