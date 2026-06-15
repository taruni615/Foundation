#!/usr/bin/env python3
"""CLI entry point for the v3 topic-wise textbook extraction pipeline.

Default pipeline (--format v3, TopicWiseExporter)
-------------------------------------------------
  Step 1/6  Resolve PDF (or continue from cached Markdown)
  Step 2/6  Mathpix → cached book Markdown (``Mathpix_Cache/<book>.md``)
  Step 3/6  Split cache → per-topic Markdown (``outputs/<book>/topics_md/``)
  Step 4-5/6  Ollama enrichment → per-topic JSON (``outputs/<book>/topics_json/``)
  Step 6/6  Merge → ``outputs/<book>/<book>_final.json`` (+ ``<book>_qa_table.json``)

Examples::

  python textbook_extract_pipeline.py "Input_PDFs/10TH CHEMISTRY FOUNDATION.pdf"
  python textbook_extract_pipeline.py --topics 1,2 "Input_PDFs/book.pdf"
  python textbook_extract_pipeline.py --skip-llm --merge-final "Input_PDFs/book.pdf"
  python textbook_extract_pipeline.py --relabel-final "outputs/book/book_final.json"

Implementation lives in ``topicwise_pipeline.py`` (v3 only; no v2/db/MySQL).
"""

from topicwise_pipeline import main

if __name__ == "__main__":
    main()
