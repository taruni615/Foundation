#!/usr/bin/env python3
"""Canonical filesystem anchors and the shared ``.env`` loader.

``PACKAGE_ROOT`` / ``PROJECT_ROOT`` were previously recomputed from ``__file__``
in every entry point, and ``load_dotenv`` was duplicated verbatim in
``web/server.py`` and ``generators/questions/mcq_generator.py``.

This module imports nothing from ``edu_pipeline`` so it stays safe to import
from any layer.
"""

from __future__ import annotations

from pathlib import Path

# edu_pipeline/shared/paths.py -> edu_pipeline/ -> <repo root>
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

# ---------------------------------------------------------------------------
# Workspace / cache directories
# ---------------------------------------------------------------------------
# These are intentionally CWD-relative (the pipeline has always resolved them
# against the process working directory, with a fallback to the pre-refactor
# locations). The expressions are reproduced verbatim from the extraction
# module, which now re-exports them; behaviour is unchanged, but the repository
# and generator layers no longer have to import the extraction pipeline just to
# learn where the workspace lives.
import os  # noqa: E402

MATHPIX_CACHE_DIR = os.path.join("edu_pipeline", "materials", "cache") if os.path.exists(os.path.join("edu_pipeline", "materials", "cache")) else "Mathpix_Cache"
MATHPIX_CACHE_DIR_ALIASES = [MATHPIX_CACHE_DIR, "Mathpix_Cache", "mathpix_cache", "Mathpix_Cache".lower()]
OUTPUT_DIR = os.path.join("edu_pipeline", "workspace") if os.path.exists(os.path.join("edu_pipeline", "workspace")) else "outputs"


def load_dotenv(path: Path) -> None:
    """Populate ``os.environ`` from a KEY=VALUE ``.env`` file.

    Values already present in the real environment win. Must run BEFORE
    importing pipeline modules, which freeze ``DB_*`` / ``OLLAMA_*`` at import
    time. A missing file is not an error.
    """
    import os

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass
