# Textbook Extractor

Turn a textbook PDF into clean, reviewed content and save it to the database —
through a simple step-by-step website. No technical knowledge required.

## Running the website

1. **Install the requirements** (one time):

   ```bash
   pip install -r requirements.txt
   ```

2. **Start the website**:

   ```bash
   python app_server.py
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
python textbook_extract_pipeline.py "Input_PDFs/<book>.pdf"   # PDF → extracted JSON
python final_to_qa_table.py outputs/<book>/<book>_final.json  # → qa_table JSON
python insert_qa_table.py outputs/<book>/<book>_qa_table.json # → database
```

A separate read-only viewer (`viewer_api.py`) is also available for browsing
what's already in the database.
# IIT_Foundation
# IIT_Foundation
