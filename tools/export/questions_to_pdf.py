"""Render the exported question bank to PDF, one file per class + subject.

The bank stores maths as **MathML** and some questions embed HTML tables, so
the questions are laid out as printable HTML and handed to headless Chromium
(Chrome or Edge, whichever is installed) via ``--print-to-pdf``. Chromium
renders MathML Core natively, which no pure-Python PDF library here does --
reportlab/fpdf would need the MathML flattened to plain text first, losing
fractions, roots and superscripts.

Usage::

    python tools/export/questions_to_pdf.py                 # all 14 subjects
    python tools/export/questions_to_pdf.py --class 8       # just class 8
    python tools/export/questions_to_pdf.py --html-only     # skip the PDF step
    python tools/export/questions_to_pdf.py --with-answers  # include answer key

Output lands in ``exports/pdf/`` as ``Class_8_Physics.pdf`` etc., each with a
title page, a chapter/topic contents list, and questions grouped by chapter and
topic in the same order as the JSON.
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.append(str(Path(__file__).resolve().parents[2]))

DEFAULT_IN = "exports/questions/flat/all_questions_flat.json"
DEFAULT_OUT = "exports/pdf"

_BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser",
]

_CSS = """
@page { size: A4; margin: 16mm 14mm 18mm 14mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Calibri, Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.45; color: #111; margin: 0; }
h1.title { font-size: 26pt; margin: 0 0 6pt; }
.sub { color: #555; font-size: 12pt; margin-bottom: 24pt; }
.cover { page-break-after: always; padding-top: 40mm; }
.cover table { border: none; margin-top: 18pt; }
.cover td { border: none; padding: 3pt 14pt 3pt 0; font-size: 11pt; }
.toc { page-break-after: always; }
.toc h2 { font-size: 15pt; border-bottom: 1.5pt solid #333; padding-bottom: 4pt; }
.toc li { margin: 2pt 0; }
h2.chapter { font-size: 15pt; margin: 20pt 0 8pt; padding: 6pt 8pt;
             background: #eef2f7; border-left: 4pt solid #3a5f8a;
             page-break-before: always; page-break-after: avoid; }
h3.topic { font-size: 12pt; margin: 14pt 0 6pt; color: #24405e;
           border-bottom: 1pt dotted #9bb; padding-bottom: 3pt;
           page-break-after: avoid; }
.q { margin: 0 0 11pt; padding: 7pt 9pt; border: 0.6pt solid #d6dbe1;
     border-radius: 3pt; page-break-inside: avoid; }
.qhead { font-size: 8pt; color: #667; margin-bottom: 3pt;
         text-transform: uppercase; letter-spacing: .4pt; }
.qnum { font-weight: 700; color: #24405e; }
.qtext { white-space: pre-wrap; }
ol.opts { list-style: none; margin: 6pt 0 0; padding-left: 4pt; }
ol.opts li { margin: 2pt 0; white-space: pre-wrap; }
ol.opts .oid { display: inline-block; min-width: 15pt; font-weight: 700; }
.correct { background: #e7f5ea; border-radius: 2pt; padding: 0 3pt; }
.ans { margin-top: 5pt; font-size: 9.5pt; color: #1c5b2c; }
.exp { margin-top: 4pt; font-size: 9.5pt; color: #333; white-space: pre-wrap;
       border-left: 2.5pt solid #d8dde3; padding-left: 7pt; }
table { border-collapse: collapse; margin: 5pt 0; font-size: 9.5pt;
        max-width: 100%; }
th, td { border: 0.6pt solid #9aa; padding: 2.5pt 5pt; text-align: left; }
th { background: #f2f4f7; }
math { font-size: 1.02em; }
img { max-width: 100%; }
"""


def find_browser() -> Optional[str]:
    for candidate in _BROWSERS:
        if candidate.startswith(("C:", "/")):
            if Path(candidate).exists():
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


def esc(text: Any) -> str:
    return html_mod.escape(str(text or ""))


# Question text is stored as a fragment of the source document: it may contain
# MathML, HTML tables and literal newlines. It must be emitted as-is (CSS
# `white-space: pre-wrap` keeps the newlines) -- escaping would print raw tags.
# Only a stray script/style is stripped, which the bank never legitimately has.
_STRIP = re.compile(r"<\s*/?\s*(?:script|style|iframe|object|embed)[^>]*>", re.I)

# Inside <table> cells the extractor stored MathML *escaped* ("&lt;math ...&gt;"),
# so a browser prints the markup instead of the maths. Decoding exactly one
# level turns it back into a real element; the character entities it contains
# ("&amp;#x00028;" -> "&#x00028;") are then decoded by the HTML parser as usual.
_ESCAPED_MATH = re.compile(r"&lt;\s*math\b.*?&lt;\s*/\s*math\s*&gt;", re.S | re.I)


def unescape_mathml(text: str) -> str:
    def decode(match: re.Match) -> str:
        decoded = html_mod.unescape(match.group(0))
        # Only accept a decode that actually produced an element.
        return decoded if decoded.lstrip().lower().startswith("<math") else match.group(0)

    return _ESCAPED_MATH.sub(decode, text or "")


def markup(text: str) -> str:
    return _STRIP.sub("", unescape_mathml(text or ""))


def render_html(rows: List[Dict[str, Any]], cls: str, subject: str,
                with_answers: bool) -> str:
    chapters: Dict[Any, Dict[str, List[Dict]]] = OrderedDict()
    for row in rows:
        key = (row.get("chapter_number"), row.get("chapter") or "Unspecified")
        chapters.setdefault(key, OrderedDict())
        chapters[key].setdefault(row.get("topic") or "General", []).append(row)

    parts: List[str] = []
    total_topics = sum(len(t) for t in chapters.values())
    with_opts = sum(1 for r in rows if r.get("options"))
    parts.append(f"""<div class="cover">
      <h1 class="title">Class {esc(cls)} &middot; {esc(subject)}</h1>
      <div class="sub">Foundation Question Bank</div>
      <table>
        <tr><td><b>Questions</b></td><td>{len(rows)}</td></tr>
        <tr><td><b>Chapters</b></td><td>{len(chapters)}</td></tr>
        <tr><td><b>Topics</b></td><td>{total_topics}</td></tr>
        <tr><td><b>With options</b></td><td>{with_opts}</td></tr>
      </table></div>""")

    parts.append('<div class="toc"><h2>Contents</h2><ol>')
    for (number, name), topics in chapters.items():
        count = sum(len(v) for v in topics.values())
        label = f"Chapter {number}: {esc(name)}" if number is not None else esc(name)
        parts.append(f"<li>{label} <i>({count} questions, {len(topics)} topics)</i></li>")
    parts.append("</ol></div>")

    index = 0
    for (number, name), topics in chapters.items():
        heading = f"Chapter {number} &middot; {esc(name)}" if number is not None else esc(name)
        parts.append(f'<h2 class="chapter">{heading}</h2>')
        for topic, questions in topics.items():
            parts.append(f'<h3 class="topic">{esc(topic)}</h3>')
            for row in questions:
                index += 1
                parts.append(render_question(row, index, with_answers))
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>Class {esc(cls)} {esc(subject)}</title>"
            f"<style>{_CSS}</style></head><body>{''.join(parts)}</body></html>")


def render_question(row: Dict[str, Any], index: int, with_answers: bool) -> str:
    meta = " &middot; ".join(
        esc(v) for v in (row.get("question_type"), row.get("difficulty"),
                         row.get("cognitive_level")) if v
    )
    out = [f'<div class="q"><div class="qhead">'
           f'<span class="qnum">Q{index}</span> &nbsp;{meta} &nbsp;'
           f'<span style="color:#99a">#{esc(row.get("question_id"))}</span></div>']
    out.append(f'<div class="qtext">{markup(row.get("question"))}</div>')

    answer = row.get("answer") or ""
    options = row.get("options") or []
    if options:
        out.append('<ol class="opts">')
        for option in options:
            oid = esc(option.get("id"))
            mark = " correct" if with_answers and answer and option.get("id") == answer else ""
            out.append(f'<li><span class="oid{mark}">({oid})</span> '
                       f'{markup(option.get("text"))}</li>')
        out.append("</ol>")
    if with_answers:
        if answer:
            out.append(f'<div class="ans"><b>Answer:</b> {esc(answer)}</div>')
        if row.get("explanation"):
            out.append(f'<div class="exp"><b>Explanation.</b> '
                       f'{esc(row["explanation"])}</div>')
    out.append("</div>")
    return "".join(out)


def to_pdf(browser: str, html_path: Path, pdf_path: Path, timeout: int) -> bool:
    with tempfile.TemporaryDirectory() as profile:
        command = [
            browser, "--headless", "--disable-gpu", "--no-sandbox",
            f"--user-data-dir={profile}",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=30000",
            f"--print-to-pdf={pdf_path.resolve()}",
            html_path.resolve().as_uri(),
        ]
        try:
            done = subprocess.run(command, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"    ! timed out after {timeout}s")
            return False
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        tail = (done.stderr or b"").decode(errors="replace").strip().splitlines()[-3:]
        print("    ! chromium produced no PDF", *tail, sep="\n      ")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", default=DEFAULT_IN)
    parser.add_argument("--out-dir", default=DEFAULT_OUT)
    parser.add_argument("--class", dest="only_class", action="append")
    parser.add_argument("--subject", dest="only_subject", action="append")
    parser.add_argument("--with-answers", action="store_true",
                        help="include the answer key and explanations")
    parser.add_argument("--html-only", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    with open(args.src, encoding="utf-8") as handle:
        data = json.load(handle)
    rows = data["questions"] if isinstance(data, dict) else data
    print(f"Loaded {args.src} ({len(rows)} questions)")

    if args.only_class:
        wanted = {c.strip() for c in args.only_class}
        rows = [r for r in rows if str(r.get("class")) in wanted]
    if args.only_subject:
        wanted = {s.strip().lower() for s in args.only_subject}
        rows = [r for r in rows if str(r.get("subject", "")).lower() in wanted]
    if not rows:
        print("Nothing matched the filters.")
        return 1

    groups: Dict[Any, List[Dict]] = defaultdict(list)
    for row in rows:
        groups[(str(row.get("class")), str(row.get("subject")))].append(row)

    browser = None if args.html_only else find_browser()
    if not args.html_only and not browser:
        print("No Chrome/Edge found -- writing HTML only; open it and Print to PDF.")
        args.html_only = True
    elif browser:
        print(f"Renderer: {browser}")

    out_dir = Path(args.out_dir)
    (out_dir / "html").mkdir(parents=True, exist_ok=True)
    made = 0
    for (cls, subject) in sorted(groups, key=lambda k: (
            int(k[0]) if k[0].isdigit() else 99, k[1])):
        subset = groups[(cls, subject)]
        stem = f"Class_{cls}_{re.sub(r'[^A-Za-z0-9]+', '_', subject).strip('_')}"
        html_path = out_dir / "html" / f"{stem}.html"
        html_path.write_text(render_html(subset, cls, subject, args.with_answers),
                             encoding="utf-8")
        size = html_path.stat().st_size / 1e6
        print(f"  {stem}: {len(subset)} questions, HTML {size:.1f} MB")
        if args.html_only:
            continue
        pdf_path = out_dir / f"{stem}.pdf"
        if to_pdf(browser, html_path, pdf_path, args.timeout):
            made += 1
            print(f"    -> {pdf_path} ({pdf_path.stat().st_size/1e6:.1f} MB)")

    print(f"\n{made} PDF(s) in {out_dir}" if not args.html_only
          else f"\nHTML in {out_dir / 'html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
