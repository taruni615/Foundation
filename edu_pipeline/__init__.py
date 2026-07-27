"""edu_pipeline package.

Loads the repository ``.env`` exactly once, before any submodule reads the
environment. Several modules freeze configuration at import time
(``shared/db_config.py``, ``extraction/topic_extractor.py``), so this has to
happen here — at the package boundary — rather than in individual entry points.

``load_dotenv`` uses ``os.environ.setdefault``: real environment variables
always win over the file, and a missing ``.env`` is not an error.
"""

from edu_pipeline.shared.paths import PROJECT_ROOT, load_dotenv

load_dotenv(PROJECT_ROOT / ".env")
