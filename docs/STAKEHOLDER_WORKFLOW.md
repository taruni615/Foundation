# Foundation Textbook Digitization — Stakeholder Overview

**Document purpose:** Explain what has been built, how content moves from PDF to database, and how stakeholders can review it.  
**Audience:** Non-technical executives, curriculum leads, and program sponsors.  
**Last updated:** May 2026  
**Repository:** `d:\Nithish\TRYING\TRYING`

---

## Council: Documentation emphasis (internal synthesis)

| Voice | Position |
|-------|----------|
| **Architect** | Document the two-phase delivery (pipeline artifacts → manual DB load → viewer) with a clear data model; technical accuracy prevents false “go-live” signals. |
| **Skeptic** | Lead with educator outcomes and honest quality limits; “in MySQL” is coverage, not editorial sign-off. |
| **Pragmatist** | Per-book status matrix and viewer as proof artifact beat stack diagrams. |
| **Critic** | Disclose automation risks, local-only viewer, and that pipeline completion does not update the database. |

**Verdict:** Stakeholders should see **outcomes + gates**, not only tooling. **Recommendation:** Use this document’s status table and review checklist before treating any book as production-ready.

---

## 1. Executive summary

This project converts **Foundation-series textbook PDFs** into structured digital content:

- **Chapter summaries** and **key learning points** (LLM-assisted)
- **Theory sections** split by topic within each chapter
- **Questions and answers** (exercises, examples, illustrations, “Check Your Knowledge,” etc.)

Content is produced as JSON files, loaded into a **MySQL** database (`foundation`), and browsed through a **web-based chapter viewer** on a local API server.

As of the latest database snapshot, **17,932 questions include a solution** (non-empty answer) across all loaded Foundation books.

**Important:** The automated pipeline stops at JSON. Putting data into MySQL and opening the viewer are **separate, deliberate steps** with human review in between.

---

## 2. What has been delivered

### 2.1 Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| PDF → structured Markdown (Mathpix) | Operational | Cached under `Mathpix_Cache/` |
| Per-chapter/topic split & extraction | Operational | Regex + TOC heuristics |
| LLM enrichment (summaries, key points) | Operational | Local Ollama (`qwen3:8b` default) |
| Merged book JSON (`*_final.json`) | Operational | Full pedagogical structure |
| QA export (`*_qa_table.json`) | Operational | Flat rows for database |
| MySQL storage (3 tables) | Operational | See Section 4 |
| Web viewer (books, chapters, tabs) | Operational | Summary / Key points / Theory / Q&A |
| Public cloud deployment | Not in scope | Viewer is local (`127.0.0.1`) |

### 2.2 Books loaded into MySQL (as of project logs)

These books have been inserted via `insert_qa_table.py` (counts from terminal output):

| Book | Chapters | Theory sections | Q&A rows |
|------|----------|-----------------|----------|
| 10 PHYSICS FOUNDATION | 8 | 639 | 2,944 |
| 10TH BIOLOGY FOUNDATION | 8 | 412 | 2,368 |
| 10TH CHEMISTRY FOUNDATION | 9 | 698 | 2,366 |
| 10TH MATHS FOUNDATION | 19 | 701 | 1,012 |
| Foundation Biology Class 8th | 11 | 141 | 32 |
| Foundation Chemistry Class 8 | 8 | 472 | 322 |
| Foundation Mathematics Class 6 | 14 | 727 | 330 |
| Foundation Mathematics Class 7 | 15 | 616 | 970 |
| Foundation Mathematics Class 8 | 16 | 844 | 160 |
| Foundation Physics Class 8 | 11 | 738 | 760 |
| Foundation Science Class 6 | 16 | 804 | 3,168 |
| Foundation Science Class 7 | 18 | 946 | 3,780 |

*Treat these counts as **inventory**, not quality certification. Each book still needs spot-check review in the viewer.*

### 2.3 Questions with solutions (database snapshot)

Counts from `qa_content_row` where `answer` is present and non-empty (queried May 2026).

| Metric | Count |
|--------|------:|
| **Total questions with solutions (all books)** | **17,932** |
| Total Q&A rows in database | 18,212 |
| Questions without a solution | 280 |

#### Class-wise (questions with solutions)

| Class | Count |
|-------|------:|
| Class 6 | 3,474 |
| Class 7 | 4,734 |
| Class 8 | 1,212 |
| Class 10 | 8,512 |
| **Combined total** | **17,932** |

*Class derived from book name (e.g. “Class 8”, “10TH”, “10 PHYSICS”).*

#### Subject-wise (questions with solutions)

| Subject | Count |
|---------|------:|
| Science | 6,948 |
| Physics | 3,572 |
| Chemistry | 2,604 |
| Biology | 2,400 |
| Mathematics | 1,412 |
| Maths | 996 |
| **Combined total** | **17,932** |

*Mathematics + Maths combined = **2,408** solution-bearing questions.*

#### Per book (with solutions / total Q&A)

| Book | With solution | Total Q&A |
|------|-------------:|----------:|
| Foundation Science Class 7 | 3,780 | 3,780 |
| Foundation Science Class 6 | 3,168 | 3,168 |
| 10 PHYSICS FOUNDATION | 2,866 | 2,944 |
| 10TH BIOLOGY FOUNDATION | 2,368 | 2,368 |
| 10TH CHEMISTRY FOUNDATION | 2,282 | 2,366 |
| 10TH MATHS FOUNDATION | 996 | 1,012 |
| Foundation Mathematics Class 7 | 954 | 970 |
| Foundation Physics Class 8 | 706 | 760 |
| Foundation Chemistry Class 8 | 322 | 322 |
| Foundation Mathematics Class 6 | 306 | 330 |
| Foundation Mathematics Class 8 | 152 | 160 |
| Foundation Biology Class 8th | 32 | 32 |

**SQL used for audit:**

```sql
SELECT book_slug,
       COUNT(*) AS total_q,
       SUM(CASE WHEN answer IS NOT NULL AND TRIM(answer) <> '' THEN 1 ELSE 0 END) AS with_solution
FROM qa_content_row
GROUP BY book_slug;
```

---

## 3. End-to-end workflow (how it is done)

### 3.1 High-level flow

```mermaid
flowchart LR
  A[Source PDF] --> B[Mathpix OCR]
  B --> C[Book Markdown cache]
  C --> D[Split by chapter/topic]
  D --> E[Per-topic JSON + LLM]
  E --> F["Book *_final.json"]
  F --> G["Book *_qa_table.json"]
  G --> H[insert_qa_table.py]
  H --> I[(MySQL foundation)]
  I --> J[viewer_api.py]
  J --> K[textbook_viewer.html]
```

### 3.2 Six-step pipeline (`topicwise_pipeline.py`)

| Step | What happens | Output location |
|------|----------------|-----------------|
| **1** | Resolve source PDF (or use existing cache) | `Input_PDFs/<book>.pdf` |
| **2** | Mathpix converts PDF to Markdown | `Mathpix_Cache/<book>_mathpix.md` |
| **3** | Split book MD into per-topic files | `outputs/<book>/topics_md/` |
| **4–5** | Extract theory/Q&A; Ollama adds summary & key points | `outputs/<book>/topics_json/topic_XX.json` |
| **6** | Merge all topics | `outputs/<book>/<book>_final.json` and `<book>_qa_table.json` |

**Typical command (from repo root):**

```powershell
python topicwise_pipeline.py "Input_PDFs\10 PHYSICS FOUNDATION.pdf"
```

**Useful variants:**

- `--skip-llm` — Skip Ollama (faster, no new summaries)
- `--topics 1,2,3` — Process only selected chapters
- `--merge-final` — Rebuild final JSON from cached `topics_json/` only
- `--export-qa-table path\to\book_final.json` — Regenerate QA JSON only

**Requirements:** Python 3, Mathpix API credentials (`MATHPIX_APP_ID`, `MATHPIX_APP_KEY`), Ollama running locally for LLM steps.

### 3.3 QA table export (`final_to_qa_table.py`)

Builds or refreshes `*_qa_table.json` from an existing `*_final.json`:

```powershell
python final_to_qa_table.py "outputs\10TH BIOLOGY FOUNDATION\10TH BIOLOGY FOUNDATION_final.json"
```

The pipeline can also write this file automatically at Step 6.

---

## 4. Database design

**Database name:** `foundation` (configurable via `DB_NAME`)  
**Schema file:** `schema/qa_theory_and_rows.sql`

### 4.1 Tables

| Table | Role | Key fields |
|-------|------|------------|
| `qa_chapter` | One row per chapter (topic) per book | `book_slug`, `chapter_number`, `chapter_name`, `page_range`, `summary`, `key_points` |
| `qa_theory_chapter` | Theory subsections within a chapter | `chapter_id`, `topic_name`, `topic_explanation`, `section_order` |
| `qa_content_row` | Individual Q&A items | `chapter_id`, `question`, `answer`, `book_slug`, `chapter_name` |

Relationships: deleting a `qa_chapter` row **cascades** to its theory and Q&A rows.

### 4.2 One-time database setup

```powershell
mysql -u root -p foundation < schema/qa_theory_and_rows.sql
```

Set credentials via environment variables: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.

---

## 5. How data is inserted into the database

**Script:** `insert_qa_table.py`  
**Input:** `outputs/<book>/<book>_qa_table.json`

### 5.1 What the loader does

1. Reads `metadata.book_slug` and `topics[]` / `rows[]` from the JSON file.
2. **Upserts** chapter headers into `qa_chapter` (matched on `book_slug` + `chapter_number`).
3. Resolves `chapter_id` for each chapter number.
4. **Upserts** theory sections into `qa_theory_chapter`.
5. **Inserts** Q&A rows into `qa_content_row` (new rows each run unless book is replaced).

### 5.2 Commands

**Insert or update a book (additive Q&A rows on re-run):**

```powershell
python insert_qa_table.py "outputs\10 PHYSICS FOUNDATION\10 PHYSICS FOUNDATION_qa_table.json"
```

**Replace all data for one book** (deletes existing chapters for that slug, then reloads):

```powershell
python insert_qa_table.py --replace-book "outputs\10 PHYSICS FOUNDATION\10 PHYSICS FOUNDATION_qa_table.json"
```

**Dry run (counts only, no DB connection):**

```powershell
python insert_qa_table.py --dry-run "path\to\book_qa_table.json"
```

**Success output example:**

```
Inserted/updated 8 chapter(s), 639 theory section(s), 2944 Q&A row(s).
book_slug='10 PHYSICS FOUNDATION'
```

### 5.3 Common issues

| Symptom | Cause | Action |
|---------|-------|--------|
| `MySQL access denied` | Wrong password | Set `DB_PASSWORD` or use `--password` |
| `File not found` | Path/spacing mismatch | Use full path; match folder name exactly |
| Viewer empty / API error | DB not loaded or API not running | Run `insert_qa_table.py`, then `python viewer_api.py` |
| Duplicate Q&A rows | Re-insert without `--replace-book` | Use `--replace-book` for clean reload |

---

## 6. How users view the content

### 6.1 Components

| Component | File | Role |
|-----------|------|------|
| API + static server | `viewer_api.py` | Serves HTML and JSON endpoints from MySQL |
| Browser UI | `Viewer/textbook_viewer.html` | Book dropdown, chapter list, tabbed content |

### 6.2 Start the viewer (required)

From the repository root:

```powershell
pip install pymysql
python viewer_api.py
```

Then open in a browser:

**http://127.0.0.1:8765/Viewer/textbook_viewer.html**

Do **not** open the HTML file directly (`file://`); the page needs the API on the same origin (or set the API base URL field to `http://127.0.0.1:8765`).

### 6.3 Using the viewer

1. Confirm **API** field shows `http://127.0.0.1:8765` (default when served via `viewer_api.py`).
2. Click **Reload from DB** if books do not appear.
3. Select a **Book** from the dropdown (populated from `qa_chapter`).
4. Pick a **chapter** from the left list (filter box available).
5. Use tabs: **Summary**, **Key points**, **Theory**, **Q&A** (paginated for large chapters).
6. Math content is rendered via MathJax when equations are present.

### 6.4 API endpoints (for technical staff)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/books` | List all `book_slug` values with chapter counts |
| `GET /api/chapters?book_slug=...` | Chapters for selected book |
| `GET /api/chapter/{id}?offset=0&limit=40` | Chapter detail + theory + paginated Q&A |

---

## 7. Quality gates (recommended before “production”)

Stakeholders should treat content as **draft** until these checks pass:

- [ ] Spot-check 3 chapters per book in the viewer (Summary, Theory, Q&A tabs)
- [ ] Verify math renders correctly (equations, symbols)
- [ ] Compare page ranges and chapter titles against the printed TOC
- [ ] Confirm exercise answers match source material for a sample set
- [ ] Re-load with `--replace-book` after pipeline re-runs to avoid duplicate Q&A rows

---

## 8. Folder structure (reference)

```
TRYING/
├── Input_PDFs/              # Source PDFs
├── Mathpix_Cache/           # OCR Markdown per book
├── outputs/<book>/          # Per-book artifacts
│   ├── topics_md/
│   ├── topics_json/
│   ├── <book>_final.json
│   └── <book>_qa_table.json
├── schema/                  # MySQL DDL
├── Viewer/
│   └── textbook_viewer.html
├── topicwise_pipeline.py    # Main 6-step pipeline
├── final_to_qa_table.py     # QA JSON export helper
├── insert_qa_table.py       # MySQL loader
└── viewer_api.py            # Local API + static server
```

---

## 9. Risks and limitations (disclosed)

- **OCR & layout:** Mathpix may misread tables, diagrams, or mixed scripts.
- **LLM content:** Summaries and key points are model-generated; require human review.
- **Chapter boundaries:** TOC heuristics can mis-split topics; affects all downstream data.
- **Not auto-synced:** Re-running the pipeline does not update MySQL until `insert_qa_table.py` is run again.
- **Local viewer only:** No authentication, no multi-user hosting in current form.
- **Images:** Skipped by default for speed (`--with-images` to embed).

---

## 10. Roles and responsibilities (suggested)

| Role | Responsibility |
|------|----------------|
| Operations | Run pipeline, Mathpix credentials, Ollama availability |
| Content / pedagogy | Review chapters in viewer; approve per book |
| Data | MySQL backups, `insert_qa_table.py` loads, `--replace-book` policy |
| Engineering | Viewer/API, schema migrations, future hosting |

---

## 11. Quick reference commands

```powershell
# Full pipeline for one PDF
python topicwise_pipeline.py "Input_PDFs\10 PHYSICS FOUNDATION.pdf"

# Load into MySQL
python insert_qa_table.py "outputs\10 PHYSICS FOUNDATION\10 PHYSICS FOUNDATION_qa_table.json"

# Start viewer
python viewer_api.py
# Browser: http://127.0.0.1:8765/Viewer/textbook_viewer.html
```

---

*For technical deep-dives, see inline documentation in `topicwise_pipeline.py`, `insert_qa_table.py`, and `viewer_api.py`.*
