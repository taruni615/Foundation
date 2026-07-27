# Textbook Extractor

Turn a textbook PDF into clean, reviewed content and save it to the database —
through a simple step-by-step website. No technical knowledge required.

## Running the website

1. **Install the requirements** (one time):

   ```bash
   make setup          # installs dependencies and creates .env from .env.example
   ```

   Then open `.env` and fill in your MySQL password (and Mathpix/Ollama
   settings if you plan to extract new PDFs or generate notes). Running
   `pip install -r requirements.txt` by hand works too.

2. **Start the website**:

   ```bash
   make serve          # or: python app_server.py
   ```

3. **Open it in your browser**:

   <http://127.0.0.1:8000/>

That's it. The website walks you through five steps:

| Step | What you do |
|------|-------------|
| **1 · Choose & Upload** | Pick the System/Board, Subject, and Class on the left, then upload a PDF (or choose one already on the server) on the right. |
| **2 · Extract** | Watch the progress bar while the textbook is read and broken into topics, theory, and questions. |
| **3 · Review & Edit** | See the original PDF and the extracted content side by side. Click **✎ Edit** to fix anything, then **💾 Save edits**. |
| **4 · Preview** | Review everything grouped by category. Search and edit any question or answer. |
| **5 · Save to Database** | Confirm the details and insert everything into the database. |

### Good to know

- **Try it right away:** four textbooks are already extracted, so Steps 2–4 work
  instantly for them — great for a first look without any setup.
- **Extracting a brand-new PDF** needs the extraction services
  (Mathpix + Ollama) configured. If they aren't, the website shows a clear
  message instead of failing silently.
- **Saving to the database** needs MySQL running (database `foundation`). If it
  isn't reachable, the website tells you exactly what to start.
- **Change the port** if 8000 is taken:

  ```bash
  APP_PORT=8080 python app_server.py
  ```

- **Database connection** is configured with environment variables
  (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`) — defaults match a
  local MySQL with database `foundation`.

## Behind the scenes (the pipeline)

The website is a friendly front end over the existing command-line pipeline. The
underlying flow is:

```
PDF → text (Mathpix) → topics → questions & answers (Ollama) → <book>_final.json → <book>_qa_table.json → MySQL
```

You can still run those steps directly from the terminal if you prefer:

```bash
BOOK="10 PHYSICS FOUNDATION"
python textbook_extract_pipeline.py "edu_pipeline/materials/input/$BOOK.pdf"
python final_to_qa_table.py "edu_pipeline/workspace/$BOOK/${BOOK}_final.json"
python insert_qa_table.py "edu_pipeline/workspace/$BOOK/${BOOK}_qa_table.json"
```

Run these from the repository root — the pipeline resolves `edu_pipeline/workspace`
and `edu_pipeline/materials/cache` relative to the current working directory.

A separate read-only viewer (`viewer_api.py`) is also available for browsing
what's already in the database.

## For developers

```bash
make install-dev    # runtime + dev dependencies
make test           # test suite (needs neither MySQL nor Ollama)
make check          # lint + tests, same as CI
make help           # all available tasks
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the onboarding guide, and
[CLAUDE.md](CLAUDE.md) for layer responsibilities and architecture rules.

## Repository layout

```
edu_pipeline/            # the application package
    materials/input/     # source PDFs (tracked)
    materials/cache/     # Mathpix OCR cache (generated, not tracked)
    workspace/           # extraction output per book (generated, not tracked)
    extraction/          # PDF → topics → *_final.json
    repository/          # BookRepository + RepositoryService
    ai/                  # providers, prompts, model manager, domain services
    generators/          # notes + question generators
    storage/             # QA table export and MySQL load
    assessment/          # exams, attempts, accounts (file-backed)
    web/                 # app server, read-only API, frontend

schema/                  # SQL schema and migrations
docs/                    # workflow documentation
tools/                   # non-runtime utilities (see below)
*.py (root)              # compatibility wrappers — stable CLI entry points
```

### Tools

Utilities that are *not* part of normal pipeline execution:

```bash
python tools/export/export_questions.py       # dump the bank to CSV/XLSX
python tools/migration/convert_db_to_mcq.py   # one-off DB theory → MCQ conversion
```

Both must be run from the repository root. `export_questions.py` additionally
requires `pandas` and `openpyxl`, which are not in `requirements.txt`.
