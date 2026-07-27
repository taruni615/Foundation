# Contributing

## Getting set up (5 minutes)

```bash
git clone <repo> && cd IIT-Foundation
make install-dev          # runtime + dev dependencies
cp .env.example .env      # then fill in your credentials
make test                 # should pass with no MySQL and no Ollama running
```

`make help` lists every task.

### What you need running

| Component | Needed for | Without it |
|---|---|---|
| Nothing | Browsing already-extracted books, the whole test suite | — |
| **MySQL** | Question bank, exams, DB insert | Bank/exam routes degrade; `make test` still passes |
| **Ollama** | Notes + MCQ generation | Generation routes report unavailable; tests use a fake model |
| **Mathpix** | Extracting a *new* PDF | Existing books in `edu_pipeline/workspace/` still work |

The app boots with none of them installed — only the affected routes degrade.

## Layout

```
edu_pipeline/       the application package (see CLAUDE.md for layer rules)
tests/              pytest suite — no MySQL/Ollama required
tools/              non-runtime utilities (export, migration)
schema/             SQL schema and migrations
docs/               workflow documentation
*.py (repo root)    compatibility wrappers — the stable CLI entry points
```

## Ground rules

1. **Servers stay stdlib-only.** No Flask/FastAPI — `http.server` is deliberate.
2. **Never import a root wrapper from inside `edu_pipeline/`.** Use the real
   module (`from edu_pipeline.storage import database`), not `import bank_read`.
   A test enforces this (`tests/test_backward_compat.py`).
3. **Don't delete or rename the root wrappers.** They are the documented CLI.
4. **Shared helpers live in `edu_pipeline/shared/`** — check there before writing
   a path, JSON-parsing or config helper.
5. **No secrets in source.** Everything goes through `.env`; `.env.example`
   documents each variable. A test guards the previously-leaked Mathpix keys.
6. **Modules must import cleanly without MySQL/Ollama.** Use lazy imports for
   heavy or service-dependent code.

## Before you push

```bash
make check        # lint + tests
make format       # black + isort
make typecheck    # mypy over shared/, repository/, ai/
```

CI runs `make check` on every push and pull request.

## Testing

Tests assert **behaviour**, not implementation. Use the fixtures in
`tests/conftest.py`:

- `sample_document` / `workspace` — a synthetic v3.1 book on disk
- `analysis_payload` — a Stage 1 content-analysis payload
- `fake_llm` — installs a stub model; records calls and returns canned replies,
  so you can assert pipeline shape without Ollama
- `app_server` / `viewer_server` — launch the real entry points on a free port

Anything genuinely needing a service goes behind `@pytest.mark.requires_db` or
`@pytest.mark.requires_ollama`; those are skipped by `make test`.

## Incremental adoption

Two quality gates are configured but not yet enforced repo-wide, deliberately:

- **Formatting.** `pyproject.toml` configures black/isort, but the legacy
  modules are unformatted. Reformatting `edu_pipeline/extraction/topic_extractor.py`
  (7k lines) in one commit would destroy `git blame`. Format files as you touch
  them; `make format-check` shows the current gap.
- **Typing.** `mypy` covers `shared/`, `repository/` and `ai/`. The extraction
  package is excluded via `ignore_errors`. Remove that override once the module
  is decomposed.
