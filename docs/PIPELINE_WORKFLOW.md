# Foundation Textbook Pipeline

**Technical Workflow — What the Pipeline Does**

June 2026

---

## Executive Summary

This pipeline converts Foundation-series textbook PDFs into structured digital content: chapter summaries (student-friendly revision notes), key learning points, theory sections split by topic, and questions with answers grouped by type (illustrations, Check Your Knowledge, textbook exercises, practice exercises, case studies). Content is produced as JSON (format v3.1), exported to a flat QA table, optionally loaded into MySQL (database: foundation), and reviewed in local web viewers with PDF/HTML/JSON download.

**Critical point:** `topicwise_pipeline.py` stops at JSON files. Database load (`insert_qa_table.py`) and viewing (`viewer_api.py`) are separate manual steps. Human review is recommended before treating any book as production-ready.

---

## End-to-End Workflow

```
PDF in Input_PDFs/
│
▼
Mathpix OCR  ──►  Mathpix_Cache/<book>_mathpix.md
│
▼
Split by chapter/topic  ──►  outputs/<book>/topics_md/
│
▼
Ollama (qwen3:8b) — key points + student summaries  ──►  topics_json/
│
▼
Merge + relabel (v3.1) + MathML  ──►  outputs/<book>/<book>_final.json
│                      └── <book>_qa_table.json  (DB-ready)
▼
insert_qa_table.py  ──►  MySQL (foundation database)
│
▼
viewer_api.py + viewers  ──►  Browse / Summary PDF / Full PDF in browser
```

---

## Database Structure

| Table | Purpose |
|-------|---------|
| `qa_chapter` | Chapter header: name, pages, summary, key points |
| `qa_theory_chapter` | Theory subsections linked to chapter_id |
| `qa_content_row` | Individual questions and answers |

Schema: `schema/qa_theory_and_rows.sql` | Database name: `foundation`

---

## How Users View Content

**Start the API server:**

```powershell
python viewer_api.py
```

**Two viewers** (both require the API server — do not open HTML via `file://`):

- DB viewer: `http://127.0.0.1:8765/Viewer/textbook_viewer.html` — chapters from MySQL
- JSON viewer: `http://127.0.0.1:8765/Viewer/output_json_viewer.html?json=/outputs/<book>/<book>_final.json`

- Book dropdown lists all `book_slug` values in `qa_chapter`
- Chapter list and tabs load data via `/api/books`, `/api/chapters`, `/api/chapter/{id}`
- Summary, Key points, Theory, Illustrations, Check knowledge, Textbook, Exercises tabs
- MathJax renders equations in theory and Q&A
- Download: Summary PDF, Full chapter PDF, HTML, JSON

---

## Quick Reference

1. **Full pipeline from PDF:**
   ```powershell
   python -u topicwise_pipeline.py "Input_PDFs/10 PHYSICS FOUNDATION.pdf" --with-images
   ```

2. **Regenerate student summaries only:**
   ```powershell
   python -u topicwise_pipeline.py --summarize-only "outputs/10 PHYSICS FOUNDATION/10 PHYSICS FOUNDATION_final.json" --force-summarize --summarize-llm
   ```

3. **Load into MySQL:**
   ```powershell
   python insert_qa_table.py "outputs/10 PHYSICS FOUNDATION/10 PHYSICS FOUNDATION_qa_table.json"
   ```

4. **Start viewer API:**
   ```powershell
   python viewer_api.py
   ```

5. **Open browser:**
   - `http://127.0.0.1:8765/Viewer/textbook_viewer.html`
   - `http://127.0.0.1:8765/Viewer/output_json_viewer.html?json=/outputs/10%20PHYSICS%20FOUNDATION/10%20PHYSICS%20FOUNDATION_final.json`

---

*Regenerate Word file: `python docs/generate_pipeline_workflow_docx.py`*
