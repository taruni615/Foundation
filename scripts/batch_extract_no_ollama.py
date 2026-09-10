#!/usr/bin/env python3
"""Batch extract questions from all PDFs in materials/input without Ollama.

Books that already produced a QA table are skipped so an interrupted batch can
be resumed. Pass --force to re-extract everything, which is what you want after
a pipeline change: the per-topic caches invalidate themselves on a version bump,
but this script would otherwise never reach them.
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure repository root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edu_pipeline.extraction.topic_extractor import main as extract_main
from edu_pipeline.shared.paths import OUTPUT_DIR

INPUT_DIR = os.path.join("edu_pipeline", "materials", "input")

def get_pdf_files() -> list[str]:
    if not os.path.exists(INPUT_DIR):
        print(f"Directory not found: {INPUT_DIR}")
        return []
    files = [os.path.join(INPUT_DIR, f) for f in os.listdir(INPUT_DIR) if f.lower().endswith(".pdf")]
    return sorted(files)

def run_batch(force: bool = False, only: str = ""):
    pdf_files = get_pdf_files()
    if only:
        needle = only.lower()
        pdf_files = [p for p in pdf_files if needle in os.path.basename(p).lower()]
    print(f"Found {len(pdf_files)} PDF files in {INPUT_DIR}")
    
    os.environ["SKIP_LLM"] = "1"
    os.environ["SKIP_IMAGES"] = "0"
    
    summary_results = []
    
    for idx, pdf_path in enumerate(pdf_files, 1):
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        qa_json_path = os.path.join(OUTPUT_DIR, base_name, f"{base_name}_qa_table.json")
        print(f"\n==================================================")
        print(f"[{idx}/{len(pdf_files)}] Processing: {base_name}")
        print(f"==================================================")
        if os.path.exists(qa_json_path) and not force:
            try:
                import json
                with open(qa_json_path, "r", encoding="utf-8") as f:
                    qa_data = json.load(f)
                rows = len(qa_data.get("rows", []))
                topics = len(qa_data.get("topics", []))
                if rows > 0:
                    print(f"-> ALREADY COMPLETED: {topics} topics, {rows} question rows "
                          f"(skipping; use --force to re-extract)")
                    summary_results.append((base_name, "SKIPPED_DONE", topics, rows, 0.0))
                    continue
            except Exception:
                pass

        start_t = time.time()
        try:
            # Run extraction pipeline with --skip-llm and --with-images
            extract_main([pdf_path, "--skip-llm", "--with-images"])
            elapsed = time.time() - start_t
            
            if os.path.exists(qa_json_path):
                import json
                with open(qa_json_path, "r", encoding="utf-8") as f:
                    qa_data = json.load(f)
                rows = len(qa_data.get("rows", []))
                topics = len(qa_data.get("topics", []))
                print(f"-> SUCCESS ({elapsed:.1f}s): {topics} topics, {rows} question rows")
                summary_results.append((base_name, "SUCCESS", topics, rows, elapsed))
            else:
                print(f"-> WARNING ({elapsed:.1f}s): Pipeline finished but {qa_json_path} missing")
                summary_results.append((base_name, "MISSING_OUTPUT", 0, 0, elapsed))
        except Exception as e:
            elapsed = time.time() - start_t
            print(f"-> ERROR ({elapsed:.1f}s): {e}")
            summary_results.append((base_name, f"ERROR: {e}", 0, 0, elapsed))

    print("\n\n==================================================")
    print("BATCH EXTRACTION SUMMARY (NO OLLAMA)")
    print("==================================================")
    total_q = 0
    for name, status, t_cnt, q_cnt, sec in summary_results:
        print(f"- {name:<35} | {status:<15} | Topics: {t_cnt:2d} | Questions: {q_cnt:4d} | Time: {sec:.1f}s")
        total_q += q_cnt
    print("--------------------------------------------------")
    print(f"TOTAL QUESTIONS EXTRACTED ACROSS ALL BOOKS: {total_q}")
    print("==================================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="Re-extract books that already have output")
    parser.add_argument("--book", default="",
                        help="Only process PDFs whose filename contains this text")
    args = parser.parse_args()
    run_batch(force=args.force, only=args.book)
