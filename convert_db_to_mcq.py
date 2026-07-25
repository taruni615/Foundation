#!/usr/bin/env python3
"""Script to convert database questions to MCQ type using Ollama and sync changes to source JSON files."""

import os
import sys
import re
import argparse
import json
import pymysql
from pymysql.cursors import DictCursor
from pathlib import Path

# Force the available Ollama model
os.environ["OLLAMA_MODEL"] = "qwen2.5:1.5b-instruct"

# Add repository root to path
REPO_ROOT = Path(__file__).resolve().parent
sys.path.append(str(REPO_ROOT))

# Force UTF-8 stdout to avoid CP1252 encoding issues on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import mcq_generator
from final_to_qa_table import save_qa_table_json

# Option marker letter mapping
IDX_TO_LETTER = {0: "a", 1: "b", 2: "c", 3: "d"}

def connect_db():
    # Load .env
    env_path = REPO_ROOT / ".env"
    env_vars = {}
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            env_vars[key.strip()] = val.strip().strip('"').strip("'")
            
    db_host = env_vars.get("DB_HOST", "127.0.0.1")
    db_port = int(env_vars.get("DB_PORT", "3306"))
    db_user = env_vars.get("DB_USER", "root")
    db_name = env_vars.get("DB_NAME", "foundation")
    
    # Try different passwords
    passwords = ["root", env_vars.get("DB_PASSWORD", "Taruni@2005"), ""]
    for pwd in passwords:
        try:
            conn = pymysql.connect(
                host=db_host,
                port=db_port,
                user=db_user,
                password=pwd,
                database=db_name,
                charset="utf8mb4",
                cursorclass=DictCursor,
                autocommit=False
            )
            print(f"Connected to database successfully using password: '{pwd}'")
            return conn
        except Exception:
            continue
    raise ConnectionError("Failed to connect to MySQL database with tried passwords.")

def update_source_json(book_slug: str, orig_question: str, new_question: str, new_answer: str):
    """Finds and updates the question in outputs/{book_slug}/{book_slug}_final.json or outputs1/..."""
    final_path = REPO_ROOT / "outputs" / book_slug / f"{book_slug}_final.json"
    if not final_path.is_file():
        final_path = REPO_ROOT / "outputs1" / book_slug / f"{book_slug}_final.json"
        
    if not final_path.is_file():
        print(f"  [JSON Sync] Source final.json not found in outputs/ or outputs1/: {book_slug}")
        return False
        
    try:
        with open(final_path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception as exc:
        print(f"  [JSON Sync] Failed to read final.json: {exc}")
        return False
        
    updated = False
    
    # Clean helpers to match question text robustly
    def clean_text(t):
        if not t:
            return ""
        return re.sub(r"\s+", "", str(t)).strip().lower()
        
    orig_clean = clean_text(orig_question)
    
    QA_SECTION_KEYS = ("illustrations", "check_your_knowledge_items", "textbook_exercises", "exercises", "examples")
    
    for topic in doc.get("topics", []):
        if not isinstance(topic, dict):
            continue
        for key in QA_SECTION_KEYS:
            items = topic.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Check possible question keys
                q_val = item.get("problem") or item.get("question") or item.get("problem_markdown") or item.get("prompt_markdown") or ""
                if clean_text(q_val) == orig_clean:
                    # Update fields
                    if "problem" in item:
                        item["problem"] = new_question
                    if "question" in item:
                        item["question"] = new_question
                    if "problem_markdown" in item:
                        item["problem_markdown"] = new_question
                    if "prompt_markdown" in item:
                        item["prompt_markdown"] = new_question
                        
                    if "solution" in item:
                        item["solution"] = new_answer
                    if "solution_markdown" in item:
                        item["solution_markdown"] = new_answer
                    if "answer" in item:
                        item["answer"] = new_answer
                        
                    item["question_type"] = "MCQ"
                    updated = True
                    
    if updated:
        try:
            with open(final_path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2, ensure_ascii=False)
            # Rebuild the qa_table.json sidecar to keep in sync
            save_qa_table_json(str(final_path))
            print(f"  [JSON Sync] Updated and rebuilt QA table for {book_slug}")
            return True
        except Exception as exc:
            print(f"  [JSON Sync] Failed to save updated final.json: {exc}")
            return False
    else:
        print(f"  [JSON Sync] Could not match question in final.json")
        return False

def main():
    parser = argparse.ArgumentParser(description="Convert theory questions in database to MCQ type.")
    parser.add_argument("--limit", type=int, default=5, help="Number of questions to convert")
    parser.add_argument("--book", default=None, help="Filter by specific book slug")
    parser.add_argument("--dry-run", action="store_true", help="Print conversions without updating database/files")
    args = parser.parse_args()
    
    # Initialize DB connection
    try:
        conn = connect_db()
    except Exception as exc:
        print(f"Database connection failed: {exc}", file=sys.stderr)
        sys.exit(1)
        
    # Verify Ollama is reachable
    h = mcq_generator.health()
    if not h.get("ollama_ok"):
        print(f"Ollama error: {h.get('error')}", file=sys.stderr)
        sys.exit(1)
        
    print(f"Targeting Ollama model: {h.get('model')}")
    
    try:
        with conn.cursor() as cur:
            # Query candidate questions
            sql = "SELECT id, book_slug, chapter_name, question, answer, question_type FROM qa_content_row WHERE question_type != 'MCQ'"
            params = []
            if args.book:
                sql += " AND book_slug = %s"
                params.append(args.book)
                
            cur.execute(sql, params)
            all_rows = cur.fetchall()
            
            # Filter candidates that need conversion using the heuristic in mcq_generator
            candidates = []
            for row in all_rows:
                if mcq_generator.needs_conversion(row["question_type"], row["question"]):
                    candidates.append(row)
                    
            print(f"Found {len(candidates)} candidates needing MCQ conversion.")
            if args.book:
                print(f"Filtered by book slug: {args.book}")
                
            targets = candidates[:args.limit]
            print(f"Processing first {len(targets)} questions...")
            
            success_count = 0
            
            for i, row in enumerate(targets, 1):
                row_id = row["id"]
                book_slug = row["book_slug"]
                chapter = row["chapter_name"]
                orig_q = row["question"]
                orig_ans = row["answer"]
                q_type = row["question_type"]
                
                print(f"\n[{i}/{len(targets)}] Converting Question ID: {row_id} (Type: {q_type}, Book: {book_slug})")
                print(f"  Source Question: {orig_q[:120]}...")
                
                # Run Ollama conversion
                res = mcq_generator.theory_to_mcq(orig_q, orig_ans, "", chapter, q_type)
                
                if not res.get("ok"):
                    print(f"  Skipped: {res.get('reason', 'generation failed')}")
                    continue
                    
                mcq = res["mcq"]
                stem = mcq["stem"]
                options = mcq["options"]
                ci = mcq["correct_index"]
                explanation = mcq["explanation"]
                
                # Format question
                new_q = stem + "\n" + "\n".join(f"({IDX_TO_LETTER[idx]}) {opt}" for idx, opt in enumerate(options))
                
                # Format answer
                correct_letter = IDX_TO_LETTER[ci]
                correct_opt_text = options[ci]
                new_ans = f"({correct_letter}) {correct_opt_text}\nExplanation: {explanation}"
                
                print("  Generated MCQ stem:")
                print(f"    {stem}")
                print("  Options:")
                for idx, opt in enumerate(options):
                    marker = f"*({IDX_TO_LETTER[idx]})*" if idx == ci else f" ({IDX_TO_LETTER[idx]}) "
                    print(f"    {marker} {opt}")
                print(f"  Explanation: {explanation}")
                
                if args.dry_run:
                    print("  [Dry Run] No DB or JSON update executed.")
                    success_count += 1
                    continue
                    
                # Update DB
                try:
                    update_sql = "UPDATE qa_content_row SET question = %s, answer = %s, question_type = 'MCQ' WHERE id = %s"
                    cur.execute(update_sql, (new_q, new_ans, row_id))
                    conn.commit()
                    print("  [Database] Row updated successfully.")
                    
                    # Update source JSON files
                    update_source_json(book_slug, orig_q, new_q, new_ans)
                    success_count += 1
                except Exception as db_exc:
                    conn.rollback()
                    print(f"  [Database Error] Update failed, rolled back: {db_exc}")
                    
            print(f"\nFinished batch conversion. Successfully converted: {success_count}/{len(targets)} target(s).")
            
    finally:
        conn.close()

if __name__ == "__main__":
    main()
