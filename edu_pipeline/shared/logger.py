#!/usr/bin/env python3
"""PipelineLogger providing structured logging across pipeline operations."""

from __future__ import annotations

import logging
import sys
from typing import Dict


class PipelineLogger:
    """Centralized logger wrapper for console and file output."""

    # Cached per logger name. A single shared slot used to return the first
    # logger ever created regardless of the requested name.
    _loggers: Dict[str, logging.Logger] = {}

    @classmethod
    def get_logger(cls, name: str = "edu_pipeline") -> logging.Logger:
        logger = cls._loggers.get(name)
        if logger is None:
            logger = logging.getLogger(name)
            logger.setLevel(logging.INFO)
            if not logger.handlers:
                handler = logging.StreamHandler(sys.stdout)
                formatter = logging.Formatter(
                    "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
                handler.setFormatter(formatter)
                logger.addHandler(handler)
            cls._loggers[name] = logger
        return logger

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
