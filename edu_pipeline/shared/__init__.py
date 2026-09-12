"""Shared utilities for edu_pipeline (paths, constants, logger, helpers, config)."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Paths and environment
# ---------------------------------------------------------------------------
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PACKAGE_ROOT.parent

DEFAULT_WORKSPACE_DIR = os.environ.get("OUTPUT_DIR") or str(PACKAGE_ROOT / "workspace")
DEFAULT_MATERIALS_DIR = os.environ.get("MATERIALS_DIR") or str(PACKAGE_ROOT / "materials")
DEFAULT_CACHE_DIR = os.environ.get("MATHPIX_CACHE_DIR") or str(PACKAGE_ROOT / "materials" / "cache")

OUTPUT_DIR = DEFAULT_WORKSPACE_DIR
MATHPIX_CACHE_DIR = DEFAULT_CACHE_DIR
MATHPIX_CACHE_DIR_ALIASES = (MATHPIX_CACHE_DIR,)


def load_dotenv(dotenv_path: Optional[Path | str] = None) -> None:
    """Minimal, standard-library dotenv loader."""
    path = Path(dotenv_path) if dotenv_path else (PROJECT_ROOT / ".env")
    if not path.is_file():
        return

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


# ---------------------------------------------------------------------------
# Canonical constants
# ---------------------------------------------------------------------------
QA_SECTION_KEYS: Tuple[str, ...] = (
    "illustrations",
    "check_your_knowledge_items",
    "textbook_exercises",
    "exercises",
    "examples",
)


# ---------------------------------------------------------------------------
# Canonical Database Configuration (defaults)
# ---------------------------------------------------------------------------
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "root")
DB_NAME = os.environ.get("DB_NAME", "foundation")
DB_CHARSET = os.environ.get("DB_CHARSET", "utf8mb4")
DB_COLLATION = os.environ.get("DB_COLLATION", "utf8mb4_unicode_ci")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
class PipelineLogger:
    """Centralized logger wrapper for console and file output."""

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def derive_attributes(book_name: str) -> Dict[str, str]:
    """Derive subject, class, and board from textbook name or slug."""
    s = str(book_name or "").lower()
    subject = "Other"
    for cand in ("physics", "chemistry", "biology", "mathematics", "maths", "science"):
        if cand in s:
            subject = "Mathematics" if cand == "maths" else cand.capitalize()
            break

    klass = ""
    m = re.search(r"class\s*(\d{1,2})", s) or re.search(r"(\d{1,2})\s*th", s) or re.match(r"^\s*(\d{1,2})\b", s)
    if m:
        klass = m.group(1)

    board = "Foundation" if "foundation" in s else "Other"
    return {"subject": subject, "class": klass, "board": board}


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Extract a JSON object from text."""
    if not text or not isinstance(text, str):
        return None
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if match:
        cleaned = match.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return None
    try:
        obj = json.loads(cleaned[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


__all__ = [
    "PACKAGE_ROOT",
    "PROJECT_ROOT",
    "DEFAULT_WORKSPACE_DIR",
    "DEFAULT_MATERIALS_DIR",
    "DEFAULT_CACHE_DIR",
    "OUTPUT_DIR",
    "MATHPIX_CACHE_DIR",
    "MATHPIX_CACHE_DIR_ALIASES",
    "load_dotenv",
    "QA_SECTION_KEYS",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "DB_CHARSET",
    "DB_COLLATION",
    "PipelineLogger",
    "derive_attributes",
    "extract_json_object",
]
