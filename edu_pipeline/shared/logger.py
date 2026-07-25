#!/usr/bin/env python3
"""PipelineLogger providing structured logging across pipeline operations."""

from __future__ import annotations

import logging
import sys
from typing import Optional


class PipelineLogger:
    """Centralized logger wrapper for console and file output."""

    _logger: Optional[logging.Logger] = None

    @classmethod
    def get_logger(cls, name: str = "edu_pipeline") -> logging.Logger:
        if cls._logger is None:
            logger = logging.getLogger(name)
            logger.setLevel(logging.INFO)
            if not logger.handlers:
                handler = logging.StreamHandler(sys.stdout)
                formatter = logging.Formatter("[%(levelname)s] [%(name)s] %(message)s")
                handler.setFormatter(formatter)
                logger.addHandler(handler)
            cls._logger = logger
        return cls._logger

    @classmethod
    def info(cls, msg: str, *args: object) -> None:
        cls.get_logger().info(msg, *args)

    @classmethod
    def warning(cls, msg: str, *args: object) -> None:
        cls.get_logger().warning(msg, *args)

    @classmethod
    def error(cls, msg: str, *args: object) -> None:
        cls.get_logger().error(msg, *args)

    @classmethod
    def debug(cls, msg: str, *args: object) -> None:
        cls.get_logger().debug(msg, *args)
