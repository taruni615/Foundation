.DEFAULT_GOAL := help
PY ?= python3

.PHONY: help setup install-dev test test-all test-db lint format format-check typecheck audit check clean serve viewer notes extract

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
setup:  ## Install runtime dependencies and create .env from the template
	$(PY) -m pip install -r requirements.txt
	@test -f .env || (cp .env.example .env && echo "Created .env — fill in your credentials")

install-dev:  ## Install runtime + development dependencies
	$(PY) -m pip install -r requirements.txt -r requirements-dev.txt

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
test:  ## Run the test suite (skips tests needing MySQL/Ollama)
	$(PY) -m pytest -m "not requires_db and not requires_ollama"

test-all:  ## Run every test, including service-backed ones
	$(PY) -m pytest

test-db:  ## Run only the tests that need MySQL
	$(PY) -m pytest -m requires_db

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
lint:  ## Lint with ruff
	$(PY) -m ruff check .

format:  ## Format with black + isort
	$(PY) -m isort .
	$(PY) -m black .

format-check:  ## Check formatting without writing changes
	$(PY) -m black --check .

typecheck:  ## Type-check shared/, repository/ and ai/
	$(PY) -m mypy

audit:  ## Scan dependencies for known vulnerabilities
	$(PY) -m pip_audit -r requirements.txt

check: lint test  ## What CI runs

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
serve:  ## Start the web app on http://127.0.0.1:8000/
	$(PY) scripts/app_server.py

viewer:  ## Start the read-only viewer on http://127.0.0.1:8765/
	$(PY) scripts/viewer_api.py

notes:  ## Generate study notes: make notes BOOK="10 PHYSICS FOUNDATION"
	$(PY) scripts/short_notes_pipeline.py $(if $(BOOK),"$(BOOK)",--list)

extract:  ## Extract a PDF: make extract PDF="edu_pipeline/materials/input/<book>.pdf"
	@test -n "$(PDF)" || (echo "Usage: make extract PDF=<path to pdf>" && exit 1)
	$(PY) scripts/textbook_extract_pipeline.py "$(PDF)"

clean:  ## Remove caches and bytecode
	find . -path ./.git -prune -o -name '__pycache__' -type d -print0 | xargs -0 rm -rf
	find . -path ./.git -prune -o -name '.DS_Store' -type f -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache
