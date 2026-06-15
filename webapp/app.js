/* Textbook Extractor — front-end wizard.
   Talks to app_server.py. Pure vanilla JS, no build step. */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  attributes: { board: "", subject: "", class: "" },
  pdfFilename: "",      // file in Input_PDFs
  book: "",             // book name (PDF stem)
  jobId: "",
  document: null,       // final.json document (editable)
  topicIndex: 0,
  preview: null,        // { rows, topics, summary }
  dirtyExtraction: false,
  dirtyPreview: false,
};

// Content categories inside each topic of the final.json document.
const QA_CATEGORIES = [
  { key: "illustrations", label: "Illustrations" },
  { key: "examples", label: "Examples" },
  { key: "textbook_exercises", label: "Textbook Exercises" },
  { key: "exercises", label: "Exercises" },
  { key: "check_your_knowledge_items", label: "Check Your Knowledge" },
  { key: "case_studies", label: "Case Studies" },
  { key: "practice_exercises", label: "Practice Exercises" },
];

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */
function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast " + kind;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 2600);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const msg = (data && data.error) || (typeof data === "string" ? data : "Request failed");
    const err = new Error(msg);
    err.payload = data;
    throw err;
  }
  return data;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  (Array.isArray(children) ? children : [children]).forEach((c) => {
    if (c == null) return;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  });
  return node;
}

function goToStep(n) {
  $$(".panel-step").forEach((p) => (p.hidden = true));
  $("#step-" + n).hidden = false;
  $$("#stepper .step").forEach((s) => {
    const sn = Number(s.dataset.step);
    s.classList.toggle("active", sn === n);
    s.classList.toggle("done", sn < n);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function computeSlug() {
  const a = state.attributes;
  const parts = [a.board, a.subject, a.class ? "class-" + a.class : ""].filter(Boolean);
  if (parts.length) return slugify(parts.join(" "));
  return state.book ? slugify(state.book) : "";
}
function slugify(s) {
  return String(s || "").toLowerCase().replace(/[^\w\s-]+/g, "").trim().replace(/[\s_]+/g, "-").replace(/-+/g, "-");
}

/* ------------------------------------------------------------------ */
/* Step 1: attributes + upload                                         */
/* ------------------------------------------------------------------ */
async function initStep1() {
  const data = await api("/api/attributes");
  fillSelect($("#attr-board"), data.boards, "Select board / system");
  fillSelect($("#attr-subject"), data.subjects, "Select subject");
  fillSelect($("#attr-class"), data.classes.map((c) => ({ value: c, label: "Class " + c })), "Select class");

  ["#attr-board", "#attr-subject", "#attr-class"].forEach((id) => {
    $(id).addEventListener("change", onAttrChange);
  });
  updateSlug();
}

function fillSelect(node, items, placeholder) {
  node.innerHTML = "";
  node.appendChild(el("option", { value: "" }, placeholder));
  items.forEach((it) => {
    const value = typeof it === "string" ? it : it.value;
    const label = typeof it === "string" ? it : it.label;
    node.appendChild(el("option", { value }, label));
  });
}

function onAttrChange() {
  state.attributes = {
    board: $("#attr-board").value,
    subject: $("#attr-subject").value,
    class: $("#attr-class").value,
  };
  updateSlug();
}

function updateSlug() {
  const slug = computeSlug();
  $("#slug-out").textContent = slug || "—";
}

function applyGuess(guess) {
  if (!guess) return;
  if (guess.board) $("#attr-board").value = guess.board;
  if (guess.subject) $("#attr-subject").value = guess.subject;
  if (guess.class) $("#attr-class").value = guess.class;
  onAttrChange();
}

function selectBook(filename, book, note, guess) {
  state.pdfFilename = filename;
  state.book = book;
  applyGuess(guess);
  const box = $("#selected-book");
  box.hidden = false;
  $("#selected-book-name").textContent = book;
  $("#selected-book-note").textContent = note || "";
  $("#to-extract").disabled = false;
  updateSlug();
}

/* upload via drag/drop or browse — raw bytes + X-Filename header */
async function uploadFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    setUploadStatus("Please choose a PDF file.", "err");
    return;
  }
  setUploadStatus(`Uploading “${file.name}”…`, "");
  try {
    const buf = await file.arrayBuffer();
    const data = await api("/api/upload", {
      method: "POST",
      headers: { "X-Filename": encodeURIComponent(file.name), "Content-Type": "application/pdf" },
      body: buf,
    });
    const note = data.already_extracted
      ? "Already extracted — extraction will load instantly."
      : `Uploaded (${Math.round(data.bytes / 1024)} KB).`;
    setUploadStatus("✓ " + note, "ok");
    selectBook(data.filename, data.book, note, data.guess);
  } catch (e) {
    setUploadStatus("Upload failed: " + e.message, "err");
  }
}

function setUploadStatus(msg, kind) {
  const s = $("#upload-status");
  s.textContent = msg;
  s.className = "upload-status " + (kind || "");
}

/* ------------------------------------------------------------------ */
/* Step 2: extraction                                                  */
/* ------------------------------------------------------------------ */
async function startExtraction() {
  goToStep(2);
  $("#to-review").disabled = true;
  $("#extract-error").hidden = true;
  $("#extract-log").hidden = true;
  $("#extract-sub").textContent = `Extracting “${state.book}”. This reads the PDF and pulls out topics, theory, and questions.`;
  renderExtractSteps(0, false);

  try {
    const res = await api("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pdf: state.pdfFilename, book: state.book }),
    });
    state.jobId = res.job_id;
    state.book = res.book;
    pollExtraction();
  } catch (e) {
    showExtractError(e.message);
  }
}

const EXTRACT_STEP_LABELS = [
  "Reading the PDF",
  "Converting pages to text",
  "Splitting into topics",
  "Organising questions & answers",
  "Finalising extracted content",
];

function renderExtractSteps(activeIdx, allDone) {
  const ul = $("#extract-steps");
  ul.innerHTML = "";
  EXTRACT_STEP_LABELS.forEach((label, i) => {
    const done = allDone || i < activeIdx;
    const active = !allDone && i === activeIdx;
    ul.appendChild(
      el("li", { class: done ? "done" : active ? "active" : "" }, [
        el("span", { class: "ico" }, done ? "✓" : String(i + 1)),
        label,
      ])
    );
  });
}

async function pollExtraction() {
  try {
    const s = await api("/api/extract/status?job_id=" + state.jobId);
    const pct = Math.max(0, Math.min(100, s.progress || 0));
    $("#progress-fill").style.width = pct + "%";
    $("#progress-pct").textContent = pct + "%";
    $("#extract-message").textContent = s.message || "";
    if (s.log) {
      $("#extract-log").hidden = false;
      $("#extract-log").textContent = s.log;
    }
    renderExtractSteps(s.step || 0, s.state === "done");

    if (s.state === "done") {
      $("#to-review").disabled = false;
      toast("Extraction complete", "ok");
      return;
    }
    if (s.state === "error") {
      showExtractError(s.error || "Extraction failed.", s.log);
      return;
    }
    setTimeout(pollExtraction, 700);
  } catch (e) {
    showExtractError(e.message);
  }
}

function showExtractError(msg, log) {
  const box = $("#extract-error");
  box.hidden = false;
  box.innerHTML = "";
  box.appendChild(el("strong", {}, "Extraction problem"));
  box.appendChild(el("div", {}, msg));
  if (log) box.appendChild(el("pre", { class: "extract-log" }, log));
}

/* ------------------------------------------------------------------ */
/* Step 3: split-screen review + edit                                  */
/* ------------------------------------------------------------------ */
async function initReview() {
  goToStep(3);
  $("#pdf-frame").src = "/api/pdf?book=" + encodeURIComponent(state.book);
  if (!state.document) {
    const data = await api("/api/extraction?book=" + encodeURIComponent(state.book));
    state.document = data.document;
  }
  const topics = state.document.topics || [];
  const ts = $("#topic-select");
  ts.innerHTML = "";
  topics.forEach((t, i) => {
    const name = t.chapter_name || t.topic_name || `Topic ${t.topic_number || i + 1}`;
    ts.appendChild(el("option", { value: String(i) }, `${i + 1}. ${name}`));
  });
  ts.onchange = () => {
    state.topicIndex = Number(ts.value);
    renderTopic();
  };
  state.topicIndex = 0;
  renderTopic();
}

function renderTopic() {
  const topic = (state.document.topics || [])[state.topicIndex];
  const root = $("#extracted-content");
  root.innerHTML = "";
  if (!topic) {
    root.appendChild(el("p", { class: "empty-note" }, "No topic selected."));
    return;
  }

  // Chapter name
  root.appendChild(textSection("Chapter name", topic, "chapter_name", false));
  // Summary (can be huge — show editable textarea)
  root.appendChild(textSection("Summary", topic, "summary", true));

  // Key points
  if (Array.isArray(topic.key_points) && topic.key_points.length) {
    const sec = sectionShell("Key points", topic.key_points.length);
    const body = sec.querySelector(".x-body");
    topic.key_points.forEach((kp, idx) => {
      body.appendChild(editableItem("Key point " + (idx + 1), kp, "text"));
    });
    root.appendChild(sec);
  }

  // Theory sections
  if (Array.isArray(topic.theory_sections) && topic.theory_sections.length) {
    const sec = sectionShell("Theory sections", topic.theory_sections.length);
    const body = sec.querySelector(".x-body");
    topic.theory_sections.forEach((ts, idx) => {
      const title = ts.topics || ts.title || "Section " + (idx + 1);
      body.appendChild(editableItem(title, ts, "markdown"));
    });
    root.appendChild(sec);
  }

  // Q&A categories
  QA_CATEGORIES.forEach((cat) => {
    const items = topic[cat.key];
    if (!Array.isArray(items) || !items.length) return;
    const sec = sectionShell(cat.label, items.length);
    const body = sec.querySelector(".x-body");
    items.forEach((item, idx) => {
      body.appendChild(qaItemEditor(item, idx));
    });
    root.appendChild(sec);
  });
}

function sectionShell(title, count) {
  const sec = el("div", { class: "x-section" });
  const h = el("h3", {}, title);
  if (count != null) h.appendChild(el("span", { class: "count-pill" }, String(count)));
  sec.appendChild(h);
  sec.appendChild(el("div", { class: "x-body" }));
  return sec;
}

/* a single-value editable section bound to obj[field] */
function textSection(label, obj, field, big) {
  const sec = sectionShell(label, null);
  sec.querySelector(".x-body").appendChild(editableItem(null, obj, field, big));
  return sec;
}

/* generic editable item bound to obj[field] (string). Toggles between a
   read-only view and a textarea; writes back to obj on "Done". */
function editableItem(label, obj, field, big) {
  const wrap = el("div", { class: "x-item" });
  if (label) wrap.appendChild(el("div", { class: "x-label" }, label));

  const view = el("div", { class: "x-text" });
  view.textContent = obj[field] != null ? String(obj[field]) : "";
  wrap.appendChild(view);

  const row = el("div", { class: "x-edit-row" });
  const btn = el("button", { class: "x-edit-btn" }, "✎ Edit");
  row.appendChild(btn);
  wrap.appendChild(row);

  let editing = false;
  let ta = null;
  btn.addEventListener("click", () => {
    if (!editing) {
      editing = true;
      ta = el("textarea", { class: "editable-area" });
      if (big) ta.style.minHeight = "140px";
      ta.value = obj[field] != null ? String(obj[field]) : "";
      view.replaceWith(ta);
      btn.textContent = "✓ Done";
      ta.focus();
    } else {
      editing = false;
      obj[field] = ta.value;
      view.textContent = ta.value;
      ta.replaceWith(view);
      btn.textContent = "✎ Edit";
      markExtractionDirty();
    }
  });
  return wrap;
}

/* Q&A item: problem + solution editable */
function qaItemEditor(item, idx) {
  const wrap = el("div", { class: "x-item" });
  const title = item.title || item.question_number || "Item " + (idx + 1);
  wrap.appendChild(el("div", { class: "x-label" }, title));

  const qField = "problem" in item ? "problem" : ("problem_markdown" in item ? "problem_markdown" : "question");
  const aField = "solution" in item ? "solution" : ("solution_markdown" in item ? "solution_markdown" : "answer");

  wrap.appendChild(el("div", { class: "x-label" }, "Question"));
  wrap.appendChild(editableItem(null, item, qField, false));
  if (aField in item || item[aField] != null) {
    wrap.appendChild(el("div", { class: "x-label" }, "Answer"));
    wrap.appendChild(editableItem(null, item, aField, false));
  }
  return wrap;
}

function markExtractionDirty() {
  state.dirtyExtraction = true;
  $("#save-extraction").disabled = false;
  $("#extraction-save-note").textContent = "Unsaved changes";
  $("#extraction-save-note").style.color = "var(--warn)";
}

async function saveExtraction() {
  try {
    $("#save-extraction").disabled = true;
    await api("/api/save-extraction", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ book: state.book, document: state.document }),
    });
    state.dirtyExtraction = false;
    state.preview = null; // force rebuild on next preview
    $("#extraction-save-note").textContent = "✓ Saved";
    $("#extraction-save-note").style.color = "var(--ok)";
    toast("Extraction saved", "ok");
  } catch (e) {
    $("#save-extraction").disabled = false;
    toast("Save failed: " + e.message, "err");
  }
}

/* ------------------------------------------------------------------ */
/* Step 4: preview by category                                         */
/* ------------------------------------------------------------------ */
async function initPreview() {
  goToStep(4);
  if (state.dirtyExtraction) {
    if (confirm("You have unsaved edits in the review step. Save them before previewing?")) {
      await saveExtraction();
    }
  }
  $("#preview-rows").innerHTML = '<p class="empty-note">Building preview…</p>';
  try {
    const slug = computeSlug();
    const data = await api(`/api/preview?book=${encodeURIComponent(state.book)}&book_slug=${encodeURIComponent(slug)}`);
    state.preview = data;
    renderPreviewSummary(data.summary);
    buildCategorySelect(data.summary.by_section);
    renderPreviewRows();
  } catch (e) {
    $("#preview-rows").innerHTML = "";
    $("#preview-rows").appendChild(el("div", { class: "error-box" }, "Could not build preview: " + e.message));
  }
}

function renderPreviewSummary(summary) {
  const root = $("#preview-summary");
  root.innerHTML = "";
  root.appendChild(chip(summary.total_rows, "Total questions"));
  const sections = Object.keys(summary.by_section || {}).length;
  root.appendChild(chip(sections, "Categories"));
  const topics = (state.preview.topics || []).length;
  root.appendChild(chip(topics, "Topics / chapters"));
}
function chip(num, label) {
  return el("div", { class: "summary-chip" }, [el("b", {}, String(num)), el("span", {}, label)]);
}

function prettySection(s) {
  return String(s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function buildCategorySelect(bySection) {
  const sel = $("#category-select");
  sel.innerHTML = "";
  sel.appendChild(el("option", { value: "__all__" }, "All categories"));
  Object.entries(bySection || {}).forEach(([k, n]) => {
    sel.appendChild(el("option", { value: k }, `${prettySection(k)} (${n})`));
  });
  sel.onchange = renderPreviewRows;
  $("#preview-search").oninput = debounce(renderPreviewRows, 200);
}

function renderPreviewRows() {
  const cat = $("#category-select").value;
  const q = ($("#preview-search").value || "").toLowerCase().trim();
  const root = $("#preview-rows");
  root.innerHTML = "";
  let rows = state.preview.rows || [];
  if (cat && cat !== "__all__") rows = rows.filter((r) => r.section_type === cat);
  if (q) rows = rows.filter((r) => (r.question || "").toLowerCase().includes(q) || (r.answer || "").toLowerCase().includes(q));

  if (!rows.length) {
    root.appendChild(el("p", { class: "empty-note" }, "No questions in this view."));
    return;
  }
  const MAX = 300;
  rows.slice(0, MAX).forEach((r) => root.appendChild(previewCard(r)));
  if (rows.length > MAX) {
    root.appendChild(el("p", { class: "empty-note" }, `Showing first ${MAX} of ${rows.length}. Use search or category to narrow down.`));
  }
}

function previewCard(row) {
  const card = el("div", { class: "qa-card" });
  const top = el("div", { class: "qa-top" }, [
    el("span", { class: "qa-type" }, row.question_type || prettySection(row.section_type)),
    el("span", { class: "qa-meta" }, `${prettySection(row.section_type)} · ${row.chapter_name || ""}`),
  ]);
  card.appendChild(top);

  card.appendChild(previewField(row, "question", "Question"));
  card.appendChild(previewField(row, "answer", "Answer"));

  const editRow = el("div", { class: "x-edit-row" });
  const btn = el("button", { class: "x-edit-btn" }, "✎ Edit");
  editRow.appendChild(btn);
  card.appendChild(editRow);

  btn.addEventListener("click", () => togglePreviewEdit(card, row, btn));
  return card;
}

function previewField(row, field, label) {
  const wrap = el("div", { class: "qa-field", "data-field": field });
  wrap.appendChild(el("span", { class: "x-label" }, label));
  const v = el("span", { class: "x-text" });
  v.textContent = row[field] != null ? String(row[field]) : "";
  wrap.appendChild(v);
  return wrap;
}

function togglePreviewEdit(card, row, btn) {
  const editing = card.classList.toggle("editing");
  ["question", "answer"].forEach((field) => {
    const wrap = card.querySelector(`.qa-field[data-field="${field}"]`);
    const cur = wrap.querySelector(".x-text, .editable-area");
    if (editing) {
      const ta = el("textarea", { class: "editable-area" });
      ta.value = cur.textContent;
      cur.replaceWith(ta);
    } else {
      const v = el("span", { class: "x-text" });
      v.textContent = cur.value;
      row[field] = cur.value;
      cur.replaceWith(v);
      markPreviewDirty();
    }
  });
  btn.textContent = editing ? "✓ Done" : "✎ Edit";
}

function markPreviewDirty() {
  state.dirtyPreview = true;
  $("#save-preview").disabled = false;
  $("#preview-save-note").textContent = "Unsaved changes";
  $("#preview-save-note").style.color = "var(--warn)";
}

async function savePreview() {
  try {
    $("#save-preview").disabled = true;
    await api("/api/save-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ book: state.book, rows: state.preview.rows }),
    });
    state.dirtyPreview = false;
    $("#preview-save-note").textContent = "✓ Saved";
    $("#preview-save-note").style.color = "var(--ok)";
    toast("Preview edits saved", "ok");
  } catch (e) {
    $("#save-preview").disabled = false;
    toast("Save failed: " + e.message, "err");
  }
}

/* ------------------------------------------------------------------ */
/* Step 5: insert                                                      */
/* ------------------------------------------------------------------ */
async function initInsert() {
  goToStep(5);
  if (state.dirtyPreview) {
    if (confirm("You have unsaved preview edits. Save them before inserting?")) await savePreview();
  }
  const a = state.attributes;
  const recap = $("#insert-recap");
  recap.innerHTML = "";
  recap.appendChild(recapItem("Book", state.book));
  recap.appendChild(recapItem("Saved as", computeSlug() || "—"));
  recap.appendChild(recapItem("Board", a.board || "—"));
  recap.appendChild(recapItem("Subject", a.subject || "—"));
  recap.appendChild(recapItem("Class", a.class || "—"));
  const total = state.preview ? state.preview.summary.total_rows : "—";
  recap.appendChild(recapItem("Questions", String(total)));
  $("#insert-success").hidden = true;
  $("#insert-error").hidden = true;
  $("#start-over").hidden = true;
  $("#do-insert").hidden = false;
}
function recapItem(label, value) {
  return el("div", { class: "recap-item" }, [el("span", {}, label), el("b", {}, value)]);
}

async function doInsert() {
  $("#insert-error").hidden = true;
  $("#insert-success").hidden = true;
  $("#insert-progress").hidden = false;
  $("#do-insert").disabled = true;
  try {
    const res = await api("/api/insert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        book: state.book,
        attributes: state.attributes,
        book_slug: computeSlug(),
        replace: $("#replace-book").checked,
      }),
    });
    $("#insert-progress").hidden = true;
    const box = $("#insert-success");
    box.hidden = false;
    box.innerHTML = "";
    box.appendChild(el("h3", {}, "✓ Saved to the database!"));
    box.appendChild(el("p", {}, `Book “${res.book_slug}” is now in the database.`));
    const counts = el("div", { class: "counts" });
    counts.appendChild(countBlock(res.chapters, "Chapters"));
    counts.appendChild(countBlock(res.theory_sections, "Theory sections"));
    counts.appendChild(countBlock(res.qa_rows, "Questions"));
    box.appendChild(counts);
    $("#do-insert").hidden = true;
    $("#start-over").hidden = false;
    toast("Inserted into database", "ok");
  } catch (e) {
    $("#insert-progress").hidden = true;
    $("#do-insert").disabled = false;
    const box = $("#insert-error");
    box.hidden = false;
    box.innerHTML = "";
    box.appendChild(el("strong", {}, "Could not save to the database"));
    box.appendChild(el("div", {}, e.message));
    const p = e.payload || {};
    if (p.detail) box.appendChild(el("div", { class: "hint-line" }, p.detail));
    if (p.hint) box.appendChild(el("div", { class: "hint-line" }, p.hint));
  }
}
function countBlock(n, label) {
  return el("div", {}, [el("b", {}, String(n)), label]);
}

/* ------------------------------------------------------------------ */
/* Misc                                                                */
/* ------------------------------------------------------------------ */
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function resetAll() {
  state.document = null;
  state.preview = null;
  state.jobId = "";
  state.dirtyExtraction = false;
  state.dirtyPreview = false;
  $("#selected-book").hidden = true;
  $("#to-extract").disabled = true;
  setUploadStatus("", "");
  goToStep(1);
}

/* ------------------------------------------------------------------ */
/* Extraction history                                                  */
/* ------------------------------------------------------------------ */
async function openHistory() {
  const modal = $("#history-modal");
  const list = $("#history-list");
  modal.hidden = false;
  list.innerHTML = '<p class="history-empty">Loading…</p>';
  try {
    const data = await api("/api/attributes");
    const books = data.existing_books || [];
    list.innerHTML = "";
    if (!books.length) {
      list.appendChild(el("p", { class: "history-empty" }, "No textbooks have been extracted yet."));
      return;
    }
    books.forEach((b) => list.appendChild(historyRow(b)));
  } catch (e) {
    list.innerHTML = "";
    list.appendChild(el("div", { class: "error-box" }, "Could not load history: " + e.message));
  }
}

function historyRow(b) {
  const g = b.guess || {};
  const tags = [`${b.topic_count} topic${b.topic_count === 1 ? "" : "s"}`];
  if (g.subject) tags.push(g.subject);
  if (g.class) tags.push("Class " + g.class);

  const meta = el("div", { class: "hist-meta" });
  tags.forEach((t) => meta.appendChild(el("span", { class: "tag" }, t)));
  meta.appendChild(el("span", { class: "tag" + (b.has_qa_table ? "" : " warn") },
    b.has_qa_table ? "Preview ready" : "Not previewed yet"));

  const main = el("div", { class: "hist-main" }, [
    el("div", { class: "hist-name" }, b.book),
    meta,
  ]);
  const open = el("button", { class: "btn btn-small btn-primary" }, "Open →");
  open.addEventListener("click", () => openFromHistory(b));
  return el("div", { class: "history-row" }, [main, open]);
}

function closeHistory() {
  $("#history-modal").hidden = true;
}


async function openFromHistory(b) {
  closeHistory();
  state.book = b.book;
  state.pdfFilename = b.book + ".pdf";
  state.document = null;
  state.preview = null;
  state.dirtyExtraction = false;
  state.dirtyPreview = false;
  const g = b.guess || {};
  state.attributes = { board: g.board || "", subject: g.subject || "", class: g.class || "" };
  // Reflect into the step-1 selectors so slug/recap stay consistent.
  if ($("#attr-board")) $("#attr-board").value = state.attributes.board;
  if ($("#attr-subject")) $("#attr-subject").value = state.attributes.subject;
  if ($("#attr-class")) $("#attr-class").value = state.attributes.class;
  updateSlug();
  $("#save-extraction").disabled = true;
  $("#extraction-save-note").textContent = "";
  try {
    await initReview();
    toast(`Opened “${b.book}”`, "ok");
  } catch (e) {
    toast("Could not open: " + e.message, "err");
  }
}

/* ------------------------------------------------------------------ */
/* Wire-up                                                             */
/* ------------------------------------------------------------------ */
function wire() {
  // Step 1
  $("#browse-btn").addEventListener("click", () => $("#file-input").click());
  $("#file-input").addEventListener("change", (e) => uploadFile(e.target.files[0]));
  const dz = $("#dropzone");
  dz.addEventListener("click", (e) => { if (e.target === dz || e.target.closest(".dz-inner") && e.target.tagName !== "BUTTON") $("#file-input").click(); });
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => uploadFile(e.dataTransfer.files[0]));

  $("#to-extract").addEventListener("click", startExtraction);

  // History
  $("#history-btn").addEventListener("click", openHistory);
  $("#history-close").addEventListener("click", closeHistory);
  $("#history-modal").addEventListener("click", (e) => {
    if (e.target === $("#history-modal")) closeHistory();
  });

  // Step 2
  $("#extract-back").addEventListener("click", () => goToStep(1));
  $("#to-review").addEventListener("click", initReview);

  // Step 3
  $("#review-back").addEventListener("click", () => goToStep(2));
  $("#save-extraction").addEventListener("click", saveExtraction);
  $("#to-preview").addEventListener("click", initPreview);

  // Step 4
  $("#preview-back").addEventListener("click", () => goToStep(3));
  $("#save-preview").addEventListener("click", savePreview);
  $("#to-insert").addEventListener("click", initInsert);

  // Step 5
  $("#insert-back").addEventListener("click", () => goToStep(4));
  $("#do-insert").addEventListener("click", doInsert);
  $("#start-over").addEventListener("click", resetAll);
}

document.addEventListener("DOMContentLoaded", () => {
  wire();
  goToStep(1);
  initStep1().catch((e) => toast("Failed to load: " + e.message, "err"));
});
