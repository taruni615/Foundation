#!/usr/bin/env python3
"""Canonical MySQL connection settings.

These values used to be defined inside ``extraction/topic_extractor.py``, which
meant every layer that talks to the database (``storage``, ``web``,
``generators``) had to import the extraction pipeline just to learn the DB host.
The definitions live here now; ``topic_extractor`` re-exports them so existing
``from topicwise_pipeline import DB_HOST`` style imports keep working.

IMPORTANT — import timing
    Values are read from the environment once, at first import of this module,
    exactly as before. This module is therefore deliberately NOT re-exported
    from ``edu_pipeline.shared.__init__``: importing ``edu_pipeline.shared``
    happens very early in ``web/server.py`` (before ``load_dotenv()`` runs), and
    pulling these reads in at that point would freeze the defaults instead of
    the values from ``.env``.
"""

from __future__ import annotations

import os

# DATABASE CONFIGURATION (override via environment variables)
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "root")
DB_NAME = os.environ.get("DB_NAME", "foundation")
DB_CHARSET = os.environ.get("DB_CHARSET", "utf8mb4")
DB_COLLATION = os.environ.get("DB_COLLATION", "utf8mb4_unicode_ci")
