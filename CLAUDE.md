# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A pipeline + web app that turns Foundation-series textbook PDFs into structured,
reviewable digital content (chapter summaries, key points, topic-split theory,
and typed Q&A), loads it into MySQL, and serves it through browser viewers and a
question-bank / assessment web app. Everything is Python 3.13 **standard library
only** for the servers (no web framework); external work (OCR, LLM, DB) is
delegated to services and thin helper modules.

## Setup & running

```bash
make setup                               # dependencies + .env from .env.example
python scripts/app_server.py                      # main web app  → http://127.0.0.1:8000/  (APP_PORT to change)
python scripts/viewer_api.py                      # read-only DB/JSON viewer → http://127.0.0.1:8765/  (VIEWER_API_PORT)
```

Viewers must be reached through the server, not `file://`:
- DB viewer: `http://127.0.0.1:8765/Viewer/textbook_viewer.html`
- Questions viewer: `.../Viewer/questions_viewer.html?json=/<path>/<book>_questions.json`
- Theory viewer: `.../Viewer/theory_viewer.html?json=/<path>/<book>_theory.json`
- Combined JSON viewer: `.../Viewer/output_json_viewer.html?json=/<path>/<book>_final.json`

**One viewer per document — they are deliberately not merged.** Each reads a
single format and refuses the others with a message naming the right page:
- **`questions_viewer.html`** → `<book>_questions.json`. One card per question
  with its options (key marked), answer, explanation and figures. Faceted by
  section and question type with live counts, plus filters for missing answers /
  figures / options and a full-text search. Built for spotting extraction gaps.
- **`theory_viewer.html`** → `<book>_theory.json`. The chapter as continuous
  prose: summary, key points, then every section in order, with a sticky outline
  and a section filter.
- **`output_json_viewer.html`** → `<book>_final.json` only, with the topic tabs
  and the PDF-export buttons.

The two sidecars share a `chapters[]` spine, so the guards check for `sections[]`
vs `questions[]` rather than the top-level shape. Sidecar pages take `?json=` and
`&chapter=`; the final-JSON page takes `?json=`, `&topic=`, `&tab=` and
`&expand=1`.

All three share `Viewer/lib/content_render.js` (markdown, MathML/LaTeX, figure
resolution) and `Viewer/lib/viewer.css`. Rendering changes belong in the library,
not in a page. Figures resolve `[image:img_003]` tokens and raw CDN URLs against
the same asset map, preferring the cached file under `image_cache/` and falling
back to the original URL (via `data-fallback`) when that path does not resolve —
which is what makes a shared copy show its figures on someone else's machine.

### Sharing a viewer

```bash
python scripts/build_standalone_viewer.py                      # questions viewer
python scripts/build_standalone_viewer.py --page theory_viewer.html
```

Inlines `lib/` into one self-contained file under `dist/` (~40 KB) that opens by
double-clicking — no server, no `?json=`. The questions and theory viewers detect
`location.protocol === "file:"` and swap the path box for a file picker plus
drag-and-drop, reading the JSON with `FileReader`; nothing is uploaded. Served
from `viewer_api.py` they behave exactly as before, and the picker is available
there too.

For a copy that needs **no network at all**, build the viewer with `--offline`:

```bash
python scripts/build_standalone_viewer.py --offline            # MathJax vendored in
```

The JSON needs nothing done to it — the sidecars are self-contained already (see
below). `scripts/pack_offline_json.py` remains for documents produced before that
was true; it embeds figures into an existing JSON.

**MathJax must be the SVG build.** The default CHTML build still fetches web
fonts at render time, so vendoring it is not enough; `tex-mml-svg.js` carries its
own glyph outlines. `--offline` refuses to write a page that still has a remote
`<script>`.

Static assets are served from `edu_pipeline/web/frontend/` first, then from the
repo root — so `/Viewer/...` resolves to the package copy and
`/edu_pipeline/workspace/...` resolves to extraction output.

Quality gates: `make test` (366 tests, no MySQL/Ollama needed), `make lint`,
`make check`. Config lives in `pyproject.toml`; see CONTRIBUTING.md.

**Note:** `make lint` is a bare `ruff check .` and currently reports ~1,280
findings against modern ruff, almost all cosmetic `UP` rules (`Dict` → `dict`)
in legacy modules. `make check` therefore fails as configured. New code is kept
clean under `--select F,E9,B,I`.

Non-runtime utilities live in `tools/` (`tools/export/`, `tools/migration/`) and
are never imported by the application. The CLI entry points live in `scripts/`
and are thin wrappers over `edu_pipeline/`; the package is the implementation.

## Pipeline (command line)

The end-to-end flow, all driven by `scripts/topicwise_pipeline.py` unless noted:

```
PDF → Mathpix OCR (edu_pipeline/materials/cache/<book>_mathpix.md) → topics_md/
    → Ollama (qwen3:8b) key points + summaries → topics_json/
    → merge/relabel (v3.1) + LaTeX→MathML → <book>_final.json
    → <book>_theory.json + <book>_questions.json   (review sidecars)
    → <book>_qa_table.json → MySQL (foundation db)
```

Paths below are written as `WS` = `edu_pipeline/workspace` (extraction output)
and `IN` = `edu_pipeline/materials/input` (source PDFs). Both are resolved
**relative to the current working directory**, so always run from the repo root.

Key invocations:

```bash
# Unified Pipeline 1: Extraction & Ingestion (PDF -> OCR -> JSON -> MySQL -> Tagging)
python scripts/run_ingestion_pipeline.py "edu_pipeline/materials/input/10 PHYSICS FOUNDATION.pdf" --with-images

# Unified Pipeline 2: Generation & Conversion (MySQL/DB -> Theory-to-MCQ -> Similar MCQs -> Notes)
python scripts/run_generation_pipeline.py "10 PHYSICS FOUNDATION"

# --- Individual Step Wrappers ---
# Full extraction only from a PDF
python -u scripts/topicwise_pipeline.py "edu_pipeline/materials/input/10 PHYSICS FOUNDATION.pdf" --with-images

# Regenerate student summaries only, in place
python -u scripts/topicwise_pipeline.py --summarize-only "edu_pipeline/workspace/<book>/<book>_final.json" --force-summarize --summarize-llm

# Export the DB-ready QA table from a final.json
python scripts/final_to_qa_table.py "edu_pipeline/workspace/<book>/<book>_final.json"

# Load a QA table into MySQL (use --replace-book to overwrite an existing book)
python scripts/insert_qa_table.py "edu_pipeline/workspace/<book>/<book>_qa_table.json"

# Tag the freshly loaded rows so the Practice Engine can select against them
python scripts/tag_questions.py --coverage          # inspect first
python scripts/tag_questions.py                     # tag everything untagged

# Short-notes / study-notes only (never touches *_final.json)
python scripts/short_notes_pipeline.py "10 PHYSICS FOUNDATION"
```

## Working from the database instead of the pipeline

Once a book is loaded into MySQL, the three *downstream* jobs need nothing from
the extraction pipeline — theory and question rows are already in the `qa_*`
tables. `scripts/db_workbench.py` runs those jobs straight off the DB:

```bash
python scripts/db_workbench.py health                       # MySQL + Ollama reachability
python scripts/db_workbench.py books                        # book slugs; --book "<slug>" for chapters

# Study notes from qa_theory_chapter (no PDF, no OCR, no *_final.json)
python scripts/db_workbench.py notes "10 PHYSICS FOUNDATION" --topics 1,2

# Theory/open-ended rows -> auto-gradable MCQs
python scripts/db_workbench.py convert --book "10 PHYSICS FOUNDATION" --limit 20

# Existing bank MCQs -> fresh similar MCQs
python scripts/db_workbench.py similar --chapter 666 --per-item 2 --limit 10
```

It is **read-only against MySQL** and never touches `*_final.json`,
`*_qa_table.json`, or `edu_pipeline/workspace/`. Output goes to a separate
`edu_pipeline/workspace_db/` tree, so a DB-sourced run cannot overwrite
extraction output. `convert` / `similar` delegate to the same functions as
`scripts/mcq_generator.py` / `scripts/mcq_similar.py` (which already read the DB
directly); only the notes path needed new code —
`edu_pipeline/storage/db_repository.py` rebuilds the slice of the v3.1 document
that the notes generator reads, so `generate_short_notes` runs unmodified.

### Finding where a chapter starts

`find_topic_start_lines` matches each TOC entry against the headings in the
markdown, and a missed start is expensive: the chapter's content folds into its
neighbour, so its questions are attributed to the wrong chapter or lost with it.
Three signals earn their keep, and all three were needed to get every book right:

- **Character-level title similarity** (`title_char_similarity`), applied *last*
  so the case/length heuristics cannot downgrade it. Word overlap cannot see that
  `## NUTRITIONIN ANMALS` is "Nutrition in Animals" — OCR merged a space and
  dropped a letter — and the mixed-case rule caps a correct long title at 82,
  below a shouted sub-heading's 92.
- **`## Chapter N`** as a boundary marker. 11 of the 16 books print one.
- **Chapter aliases are scoped to the book.** `TOPIC_CHAPTER_ALIASES` is keyed by
  chapter number only and its numbers come from a class-10 Biology book, so an
  alias now fires only when the book's own contents agree. Without that,
  "chapter 1 is Life Processes" hijacked chapter 1 of every book — Biology
  Class 8th was extracting 17% of its content.

But a chapter can only be *found* if the contents page listed it. Books switch
notation partway down that page: Chemistry class 10 prints chapters 1-3 as
`3. Metals and Non-Metals ..... 97-144` and chapters 4-9 as table rows,
`| 4. | Carbon and its Compounds | 145-194 |`. `TOC_TABLE_TOPIC_RE` reads those
rows, in both `parse_toc` and `parse_contents_topics` (the latter is what builds
the `TopicMeta` list the split actually uses — changing only one of them looks
like it worked and changes nothing). Six chapters of Chemistry and five of
Biology class 10 were invisible, and their content folded into chapter 3, which
grew to 13,465 lines and gave that one chapter every later chapter's questions.

### Re-extracting after a pipeline change

`topics_json/topic_NN.json` caches the parsed content of each chapter, and
`materials/cache/<book>_mathpix.md` caches the OCR. The OCR cache should be kept
(re-running costs money); the topic cache must not go stale.

Each topic JSON is stamped with `TOPIC_CACHE_VERSION`, and a cache written by an
older extractor is ignored with a note rather than silently reused:

```
Topic JSON cache is from an older extractor (v1 < v2), re-extracting.
```

**Bump `TOPIC_CACHE_VERSION` whenever extraction changes what a topic JSON
contains** — question parsing, heading vocabulary, ordering, illustrations,
images. Without it a book extracted by an earlier build keeps its old output on
re-extraction and the change looks like it did not apply. `--force-llm` still
forces a rebuild explicitly; the version stamp just means you rarely need it.

The version stamp does not cover a change in *chapter boundaries*, because the
cache is then valid for a slice of the book that no longer belongs to that
chapter. Both caches therefore also record the line range they were cut from —
`lines:` in the topic markdown front matter, `source_lines` in the topic JSON —
and are rebuilt when it moves:

```
Topic combined MD covers 6238-19703, now 6238-9132; re-splitting.
```

Without that, fixing the contents page found the six missing chapters but
chapter 3 kept serving its stale 3.2 MB markdown, so the new chapters' questions
appeared *twice*: once in their own chapter and once in chapter 3.

### The extraction can succeed and still be wrong

Every fault in this section shipped silently: the run reported SUCCESS, the JSON
was well-formed, and the damage was only visible by reading the output. A book
that loses six of its nine chapters still "succeeds".

`edu_pipeline/extraction/quality.py` runs at the end of every extraction and
prints a report; `scripts/check_extraction_quality.py` runs the same checks over
existing output and exits non-zero on a failure, so a batch can be gated on it:

```bash
python scripts/check_extraction_quality.py outputs/*/*_questions.json
```

The sidecars are *derived* from `<book>_final.json`, so a change on the export
side — the sanitiser, option parsing, figure resolution — does not need the book
re-extracted from OCR:

```bash
python scripts/rebuild_sidecars.py outputs/*/*_final.json   # minutes, not hours
```

A change to *extraction* still needs a `TOPIC_CACHE_VERSION` bump and a re-run.

The checks are deliberately about **shape, not wording**, so a new book that
breaks in a new way still trips them:

| check | what it catches |
|---|---|
| `chapter_size` | a chapter several times its siblings' size — it absorbed them, whatever the contents page looked like |
| `duplicate_questions` | the same question in two chapters — a stale `topics_md/`/`topics_json/` cache. Warns for the handful a book genuinely reprints, fails when it is widespread |
| `answer_key` | an exercise chapter answering almost nothing while its siblings answer most — its SOLUTIONS banner was missed and the key parsed as questions |
| `runaway_question` | a question carrying more prose than any real question — it ran on into the theory or the next exercise |
| `page_furniture` | a banner, exam tag, table rule, `DIRECTIONS` preamble, un-embedded CDN URL or fullwidth character that reached a question |
| `answer_is_a_question` | an answer holding another question's text — the alignment slipped |
| `answer_outside_options` | a key of `(d)` against three options — the option list lost one |
| `unresolved_figure` | an `[image:…]` token with no figure attached, so it renders as nothing |
| `empty_chapter` | a chapter that produced nothing at all |

Each threshold is set from the corpus, not guessed, and each check is paired
with a test for the case that must *not* trip it — a book that prints no answer
key anywhere, a question long because it carries twenty structure diagrams, two
unrelated questions that share their MathML markup.

`edu_pipeline/extraction/topic_extractor.py` is the ~7,200-line core and owns most flags (`--topics`,
`--skip-llm`, `--force-llm`, `--merge-final`, `--relabel-final`,
`--export-qa-table`, `--summarize-llm`, `--with-images`, `--fix-mathml`,
`--theory-only`, …). **Important:** it stops at JSON — DB load and viewing are
separate manual steps, and human review is expected before a book is treated as
production-ready.

## Question bank: how questions find their answers

`edu_pipeline/extraction/question_bank.py` owns the parsing of a chapter's
exercises. It exists because a question and its answer are far apart in the
source: the exercises run mid-chapter and the whole answer key sits at the end,
under `## SOLUTIONS`. Numbering restarts in every sub-section, so a question is
identified only by its **`(exercise, sub-section, number)`** coordinates —
matching on the bare number pairs Exercise 1's MCQ 1 with Exercise 3's.

Both halves parse into the same `Block` shape and are aligned on those
coordinates, consumed in document order. The OCR damage the parser absorbs is
not incidental — it is the reason for most of the code:

- **Exercise numbers are mangled** — "Exercise 31", "Exercise 310",
  "Exercise 3101" and "Exercise 210" all occur, so blocks key on the exercise
  *name* ("Foundation Builder"), never the digits. `Foundation Builder +` is
  matched before `Foundation Builder`, or exercises 3 and 4 collapse into one.
- **Headings lose their `##`** about half the time, so headings are recognised
  from their text; `_looks_like_heading` rejects anything ending in sentence
  punctuation so a DIRECTIONS option list is not read as a heading. Some
  chapters lose the heading entirely and open on a bare
  `DIRECTIONS (Qs. 1-32) :`, which then names the block's kind.
- **The exercise key disagrees between halves** ("Exercise" vs "Exercise 1"), so
  the exercise key is a preference and a sub-section match still counts.
- **Answer keys are typeset in columns** and arrive flattened onto one line
  ("7. (b) 8. (c)") or out of order (1, 3, 5, …, 2, 4, 6).
- **The key covers *selected* questions only**, so an unmatched question block
  is normal and simply yields no answer.
- **The SOLUTIONS banner has several forms** — `## SOLUTIONS <br> (Brief
  Explanations…)`, a bare `SOLUTIONS`, and an unparenthesised
  `## Solutions Brief Explanations of Selected Questions`. Missing one is
  expensive: the whole answer key then parses as more questions.
- **The key sometimes names nothing at all.** Chemistry class 9 chapter 6
  prints a bare list under `## Solutions` with no exercise or sub-section
  heading, so there is no coordinate to match on and all 55 questions came back
  unanswered. `_align_blocks` falls back to matching an unlabelled solution
  block on its *numbers*, but only when most of the question block's numbers
  are present — matching on bare numbers globally is what paired Exercise 1's
  MCQ 1 with Exercise 3's in the first place.
- **`SOLUTION` carries content on its own line.** "SOLUTION: (i) Pressure =
  F/A" is a marker plus the first line of the answer. `SOLUTION_RE` accepts
  that only when a colon follows the word, because without the colon
  "SOLUTION OF A PAIR OF LINEAR EQUATIONS" is a theory heading — and treating
  it as a marker hands that whole section to the illustration above it. Missing
  the marker leaves the problem swallowing its own solution and the theory
  after it: 8,137 characters in one Physics class 9 illustration.
- **The banner can be missing altogether.** Maths chapter 2 has no `SOLUTIONS`
  line anywhere in its OCR, so the entire key parsed as 243 more unanswered
  questions — the chapter reported 255 questions and 12 answers.
  `find_answer_key_start` finds the key by its *shape* instead: a run of
  `3. (d) Substitute y = 1` lines, which a question list never produces (a
  question puts one option per line). It runs only when no banner was found,
  and measured against every chapter that *does* have one it never fires
  earlier than the real banner — so at worst it recovers part of a key, never
  cuts a chapter's questions in half. The split backs up over the heading
  directly above the run, or the key has no sub-section to align against.
- **Mathpix renders some pages in fullwidth characters** — `５．` for `5.`,
  `（Brief Explanations…）` for `(Brief Explanations…)`. They look identical in a
  terminal and match nothing. `normalize_fullwidth` (used by `_clean_heading`
  and the SOLUTIONS split) and `normalize_number` fold them back to ASCII.
  Chemistry chapter 5 was one fullwidth bracket away from having its entire
  answer key — 523 answers — parsed as questions instead.

**Question type comes from the heading, never from the wording.** The books name
their own types, so `canonical_subsection_kind` maps a heading onto a stable kind
and `export_qa.SUBSECTION_KIND_LABEL` turns that into the exported label. 98% of
the corpus is typed this way; only illustrations and Check Your Knowledge (which
sit in the theory, under no heading) fall back to `classify_question`. Watch the
ordering of `_SUBSECTION_KINDS`: "One or More than One Option Correct" contains
the wording of both "single option" and "multiple choice", so `multiple_option`
has to be tested before either.

**Questions are exported in the book's own order.** Every item carries a
`source_order` — its line in the chapter markdown — because the extractor
collects illustrations, Check Your Knowledge and exercises in separate passes and
would otherwise emit them grouped by bucket rather than interleaved as printed.
`build_structured_questions_json` sorts on it and only then assigns
`question_number`.

`ILLUSTRATION` markers get the same treatment (plain lines, and `ILLUSTRATIOM`
for `ILLUSTRATION`). An illustration's figure is typeset *inside* its solution
block, so image references anywhere in the problem/solution pair belong to that
illustration.

**LaTeX → MathML has three sharp edges**, all of which put stray characters in
front of the reader:

- **The `aligned` column separator.** latex2mathml has no support for it and
  emits `<mi>&</mi>` — a visible glyph, and invalid XML besides. Mathpix wraps
  every multi-line derivation in `aligned` (4,000+ in the corpus), so this marked
  most equations. `strip_alignment_markers` drops it before conversion.
  Deliberately narrow: `matrix`/`pmatrix` use `&` for real cells and latex2mathml
  handles those correctly.
- **`$$$`.** Mathpix runs an inline `$…$` straight into a following block
  `$$…$$`. The block pattern then matches from the wrong `$`, swallows the
  inline span and leaves an unpaired delimiter, so the text `<math` comes back
  typeset as maths and the document ends up with more `</math>` than `<math>`.
  `normalize_math_delimiters` separates them.
- **Conversion is not run once.** It happens on both the image pass and the
  merge, and the block pass leaves `<math>` in the string that the inline pass
  then scans. `convert_text` masks existing MathML before each pass, which makes
  it idempotent — verify with `convert_text(convert_text(x)) == convert_text(x)`.

**Options are not the only thing in brackets.** `parse_options` recovers the
inline option list, and two shapes defeat a naive reading of it:

- A question labels its *statements* `(A) (B)` and its *options* `(a) (b) (c)
  (d)`. Case-folding them together makes the statements the options and
  swallows the real ones into the last of them, leaving a key of `(c)` against
  two options. Each marker style is matched separately and the longest run
  wins, lowercase breaking a tie.
- The last option must not run to the end of the text. OCR interleaves the two
  columns of a page, so another question's list can land inside this one;
  unbounded, the final option absorbs it. The option ends at the next `(a)` or
  Roman-numeral statement that follows.

A key naming an option the question does not have is caught by the
`answer_outside_options` check rather than silently shipped.

**A passage's figure belongs to every question under it.** `_resolve_images`
scans the passage as well as the question, answer and explanation — a diagram
referenced only from the passage is otherwise never attached, and the
`[image:img_068]` token renders as nothing for each question that shares it.

**Matching questions carry their two lists as fields.** `parse_matching_question`
splits the stem, `list_1` (Column I, `(A)`–`(E)`) and `list_2` (Column II,
`(p)`–`(t)` or `(1)`–`(5)`); `options` holds the combination choices (`A-2, B-1`)
when the book prints them and is empty when it expects a direct pairing. The
labels overlap — `(a)`–`(d)` options look exactly like Column II entries — so
they are told apart by *content*: an option's text is a list of pairings.
`parse_matching_answer` returns the option's label when there are options and the
pairing map otherwise.

**A question is the question, not the page around it.** The books set their
questions in boxes and sidebars that the OCR flattens into one stream, so a
question or answer runs on into whatever was printed next. Nothing marks where
those boxes end, and unbounded they absorb the rest of the chapter — one Check
Your Knowledge answer reached 48,769 characters, one exercise answer 202,912.
Three defences, each at the layer that can see the boundary:

- `_theory_resumes_at` (`topic_extractor.py`) ends a Check Your Knowledge or
  ILLUSTRATION box where the chapter's own prose starts again: a resumed
  definition (`(b) Alkenes or Olefins :`), a bare title followed by a real
  paragraph, or the next prompt. A figure caption inside an answer looks like a
  heading too, which is why what *follows* the line decides.
- `_looks_like_heading` (`question_bank.py`) requires a heading to be titled,
  not written — at least 60% of its substantial words capitalised. "After
  substituting numerical values in Eq.(7), we obtain" passed every other test
  and opened a sub-section that swallowed 15,509 characters of theory as its
  questions.
- `sanitize_question_text` (`export_qa.py`) cuts what still runs on at the next
  exercise's `DIRECTIONS`/`\section*` and strips the furniture itself: the Check
  Your Knowledge banner, stranded table rules, an unpaired `$$`. Exam credits
  (`[NTSE]`, `[JSTSE]`, `[KVPY]` — 558 in the corpus) are moved to
  `source.exam` rather than dropped, and shown as a chip in the questions
  viewer.

Two rules keep it from eating content: a block that *opens* on one of these
markers keeps it (a bare `DIRECTIONS (Qs. 1-32) :` names an exercise; a question
may legitimately say "Check your knowledge of…"), and a matched `$$ … $$` is an
equation, not debris. Only an unpaired one is removed.

**The sidecars carry their figures.** `<book>_questions.json` and
`<book>_theory.json` embed every figure as base64 and rewrite any raw
`![](https://cdn.mathpix…)` in a question's text to an `[image:img_003]` token,
so a document renders with no server, no `image_cache/` and no network — which is
what a copy sent to a reviewer needs. Two things this depends on:

- Read the **cached file**, not `image_assets[...]["base64"]`: that only holds a
  payload for the first `MAX_TOPIC_IMAGES` of a topic, so trusting it silently
  drops every figure past the 80th.
- Tokenise the text. Exercise questions are re-parsed from source markdown after
  the tokenising pass, so they still carry the original CDN URL; left alone it is
  the one thing in an otherwise self-contained file that still hits the network.

`EMBED_IMAGE_DATA=0` produces lean documents that point at `image_cache/`
instead. Embedding costs roughly 3-8x (Physics questions 2.9 MB → 9.6 MB, theory
2.3 MB → 18.4 MB); `_final.json` and `_qa_table.json` are unaffected.

**Figures are downscaled once, on the way into the cache.** Mathpix returns them
at print resolution (up to ~1700px), which no viewer or PDF export uses, and each
one is also base64-embedded in `*_final.json` where it costs a third again.
`compress_image_file` caps the long edge at `IMAGE_MAX_DIM` (default 1000) and
re-encodes at `IMAGE_JPEG_QUALITY` (default 78), shrinking the cache ~25%. Set
`IMAGE_MAX_DIM=0` to keep the originals.

Two properties matter and are easy to break:
- **It runs at most once per file.** JPEG is lossy, so the output is stamped with
  `IMAGE_COMPRESSED_MARKER` in its metadata and skipped afterwards; without that,
  every re-extraction would re-encode the same figure and degrade it.
- **Pillow is optional.** A missing library, an unreadable file, or a re-encode
  that comes out no smaller all leave the original untouched rather than failing
  the extraction.

**Images survive only when `SKIP_IMAGES` is off.** `topics_md/*.md` keeps its
image references under `--with-images`; stripping them there (as the pipeline
used to do unconditionally) leaves every question figure-less no matter what the
later stages do. `MAX_TOPIC_IMAGES` (default 80) bounds how many figures carry an
inline base64 payload in `*_final.json` — it does **not** drop the asset entry,
so a question can always resolve the file it points at.

## Architecture

**`edu_pipeline/extraction/topic_extractor.py` is the shared foundation.** It defines the DB config
(`DB_HOST/PORT/USER/PASSWORD/NAME`), the Ollama client, Mathpix client, JSON
extraction helpers, and pedagogy/relabelling logic. Almost every other module
imports from it rather than duplicating logic (`viewer_api`, `bank_read`,
`insert_qa_table`, `final_to_qa_table`, `mcq_generator`, `short_notes_pipeline`).
Config is env-driven with defaults (see the top of the file); `.env` holds MySQL
credentials and is loaded on server startup.

**Two servers, both stdlib `ThreadingHTTPServer`:**
- `edu_pipeline/web/server.py` (run via `scripts/app_server.py`) — the write/action app: upload PDF, run extraction with live
  progress, edit/preview extracted content, insert to MySQL, plus the question
  bank and assessment/exam APIs. Routes live in the GET/POST dispatch around
  line 332/388 (`/api/extract`, `/api/insert`, `/api/bank/*`, `/api/exams/*`,
  `/api/mcq/*`, `/api/auth/*`, …). It boots even when pymysql/Ollama are absent
  — only the affected routes degrade (bank/mcq modules are imported lazily).
- `edu_pipeline/web/api.py` (run via `scripts/viewer_api.py`) — read-only browsing of the MySQL `qa_*` tables (slated for
  retirement per code comments; `storage/database.py` deliberately owns its own DB
  connection to avoid depending on it).

**Data layers:**
- MySQL database `foundation`, three tables: `qa_chapter` (chapter header +
  summary + key points), `qa_theory_chapter` (theory subsections, FK to
  chapter), `qa_content_row` (one row per Q&A item). Schema in `schema/`.
- `subject` / `class` / `board` are **not columns** — they are derived from
  `book_slug` (see `web/server.guess_attributes_from_name`, mirrored in
  `storage/database.py`). Attribute filters resolve to matching `book_slug` sets
  before hitting SQL.
- `edu_pipeline/assessment/storage.py` is a **file-backed** store (JSON under
  `edu_pipeline/assessment/`:
  `users.json`, `exams.json`, `attempts.json`) for accounts, hosted exams, and
  student attempts. Grading is server-side (correct answers never sent to the
  client before submit); pbkdf2 passwords + HMAC bearer tokens. Works without
  MySQL.

**Practice Engine + student dashboard** (PRD Phase 1 MVP, additive):
- `generators/questions/tagger.py` — pure rule engine producing the four PRD
  tagging attributes (`difficulty`, `subtopic`, `cognitive_level` on Bloom's
  taxonomy, `learning_objective`). `storage/database.estimate_difficulty`
  delegates here so difficulty has one definition.
- `generators/questions/mcq_parser.py` — recovers gradable MCQs from bank rows,
  whose options live *inline* in the question text and whose key lives in the
  answer text. Deliberately conservative: a row whose key cannot be established
  is rejected rather than guessed at. Only ~15% of the bank (3,319 rows) is
  recoverable — many rows have a misaligned `answer` column holding the *next*
  question's text, which is an extraction-side data bug, not a parser bug.
- `storage/tagging.py` + `scripts/tag_questions.py` — chapter-by-chapter backfill
  of the tagging columns. Resumable (`--retag` to redo, default skips tagged
  rows), `--dry-run` and `--coverage` for inspection.
- `assessment/practice.py` — the six PRD practice modes (Topic, Chapter, Mixed,
  Timed Sprint, Adaptive, Mistake) plus Daily Challenge and Chapter Tests with
  mastery bands. File-backed sessions (`practice.json`), server-side grading,
  and the Result Analysis report (per topic / difficulty / Bloom level, time per
  question, mistakes, next-step recommendation).
- `assessment/dashboard.py` — the six dashboard widgets. Each is computed behind
  its own `ok` flag so one unavailable source degrades a single card.
- Frontend: `web/frontend/webapp/src/modules/practice/` and the rewritten
  student half of `modules/exams/views/dashboard.view.js`.

Schema migration `schema/add_question_tagging_columns.sql` adds the four columns
and their indexes; every statement is guarded by an `information_schema` check,
so it is safe to re-run.

**MCQ generation** (both Ollama-powered, additive, read-only w.r.t. DB):
- `generators/questions/mcq_generator.py` — converts theory/open-ended questions into auto-gradable MCQs.
- `generators/questions/similarity.py` — generates fresh MCQs similar to existing bank MCQs.

**Frontend** (`edu_pipeline/web/frontend/webapp/`, vanilla JS ES modules, no
build): a small SPA shell (`src/shell/` — router, registry, sidenav) over a store
(`src/state/`), with two feature modules — `src/modules/bank/` (question bank
browse/detail) and `src/modules/exams/` (dashboard, create, adaptive, analytics,
login views). API clients in `src/api/`. Standalone HTML viewers live in
`edu_pipeline/web/frontend/Viewer/`.

## External dependencies & their env vars

- **Mathpix** (PDF OCR): `MATHPIX_APP_ID`, `MATHPIX_APP_KEY`. Results cached in
  `edu_pipeline/materials/cache/` so re-runs skip OCR. The cache is **not**
  version-controlled but is kept on disk — deleting it means paying for OCR again.
- **Ollama** (local LLM, default model `qwen3:8b`): `OLLAMA_BASE_URL`,
  `OLLAMA_MODEL`, `OLLAMA_TIMEOUT`. Used for key points, summaries, MCQ generation.
- **MySQL**: `DB_SOCKET` (UNIX socket, preferred) or `DB_HOST`/`DB_PORT` (TCP
  fallback), `DB_USER`, `DB_PASSWORD`, `DB_NAME` (default `foundation`).

## Layer responsibilities & dependency flow

```
        shared/         infrastructure: paths, db_config, logger, events,
          ▲             config, constants, json_utils. Imports nothing else.
          │
  ┌───────┴────────┬──────────────┬───────────────┐
  │                │              │               │
extraction/    repository/       ai/         assessment/
PDF → topics    *_final.json    providers,    exams, attempts,
→ *_final.json  load/query      prompts,      accounts
                (data access    services      (file-backed)
                 only)
  │                │              │               │
  └───────┬────────┴──────────────┘               │
          │                                       │
     generators/          storage/                │
     orchestrate:         QA-table export,        │
     notes + questions    MySQL load,             │
          │               bank queries            │
          └───────────────┬───────────────────────┘
                          │
                        web/    HTTP + frontend (composes everything)
```

- **Repositories** (`repository/`) only load, save and query `*_final.json`. No
  business logic, no LLM calls, no DB.
- **Services** (`ai/services/`) hold domain logic. Each AI service follows the
  same shape: *validate input → load prompt → execute model → parse response →
  validate output → return domain dict*, with `{"ok": bool, ...}` results rather
  than exceptions.
- **Generators** (`generators/`) orchestrate: read from a repository, call a
  service, persist. They should not contain extraction or DB logic.
- **`workflow.py`** is the only module allowed to import across all layers; it is
  the orchestrator, not a layer.

Two known deviations are accepted (not accidental):
- `storage/` imports `classify_question` from `generators/questions/classifier.py`.
  The classifier is a pure rule engine that belongs in a domain package, but it
  backs the public `scripts/question_type_classifier.py` wrapper, so it cannot move
  without renaming a public module.
- `extraction/topic_extractor.py` lazily calls into `generators` and `storage`
  for question typing and QA-table export. These were previously hidden behind
  root-wrapper imports; they are now explicit, and remain lazy to avoid cycles.

## Conventions worth respecting

- Servers use **stdlib only** — do not introduce Flask/FastAPI/etc. to match the
  existing style.
- Prefer importing helpers from `scripts/topicwise_pipeline.py` over re-implementing
  extraction/DB/LLM logic.
- Cross-layer helpers live in `edu_pipeline/shared/` — import from there rather
  than copying:
  - `shared/paths.py` — `PACKAGE_ROOT`, `PROJECT_ROOT`, `load_dotenv()`, and the
    CWD-relative `OUTPUT_DIR` / `MATHPIX_CACHE_DIR`
  - `shared/db_config.py` — `DB_HOST/PORT/USER/PASSWORD/NAME/CHARSET/COLLATION`.
    Deliberately **not** re-exported from `shared/__init__` so the env reads stay
    after `load_dotenv()` in `web/server.py`.
  - `shared/json_utils.py` — `extract_json_object()` for parsing LLM replies
  - `shared/constants.py` — `QA_SECTION_KEYS` (question arrays in `topics[]`)
  - `shared/logger.py` — `PipelineLogger`
- **Never import the root wrapper scripts from inside `edu_pipeline/`.** Use the
  real module (`from edu_pipeline.storage import database as bank_read`), not
  `import bank_read`. The wrappers exist for CLI users; importing them from the
  package inverts the dependency and only works when the repo root is on
  `sys.path`.
- One deliberate duplication remains: `storage/database.derive_attributes` and
  `web/server.guess_attributes_from_name` implement the same rule but are **not**
  identical (the server's `SUBJECTS` list carries an extra `"Other"` entry and
  its input is not `None`-safe). Keep them in sync by hand; do not merge them
  without deciding which behaviour is canonical.
- New capabilities have been added **additively**: importing a module must not
  pull in the heavy pipeline or require Ollama/MySQL at import time (use lazy
  imports and graceful degradation), so the app keeps working with the books
  already in `edu_pipeline/workspace/` when external services are offline.
- Output JSON format is **v3.1**; `<book>_final.json` is the source of truth,
  `<book>_qa_table.json` is the DB-ready flattening, and `<book>_theory.json` /
  `<book>_questions.json` are the two review sidecars (see below).

Further detail: `README.md` and `docs/PIPELINE_WORKFLOW.md`.
