// Create Exam — two tabs: General Exam (pick from the bank, key answers) and
// Adaptive Exam (generate a personalized paper for a class/section from
// performance). Mirrors the Rizee reference.
import { el, clear } from "../../../ui/el.js";
import * as assess from "../../../api/assess.api.js";
import { searchItems, getFacets } from "../../../api/bank.api.js";
import { mathSpan, setRich, typeset } from "../../../ui/rich.js";

let SEQ = 0;
const CLASSES = ["6", "7", "8", "9", "10"];
const SUBJECTS = ["Physics", "Chemistry", "Mathematics", "Biology", "Science"];
const PICK_PAGE = 25;

function fieldRow(label, control) { return el("label", { class: "ex-field" }, [el("span", {}, label), control]); }

function createQuestionEditor(prefill, onRemove) {
  const grp = "correct-" + ++SEQ;
  const typeSel = el("select", { class: "ex-input ex-qtype" }, [el("option", { value: "mcq" }, "Multiple choice"), el("option", { value: "written" }, "Written answer")]);
  typeSel.value = prefill.type === "written" ? "written" : "mcq";
  const stem = el("textarea", { class: "ex-input ex-ta", placeholder: "Question text" });
  stem.value = prefill.stem || "";
  const preview = el("div", { class: "ex-q-preview" });
  setRich(preview, stem.value);
  stem.addEventListener("input", () => setRich(preview, stem.value));
  const subject = el("input", { class: "ex-input", placeholder: "Subject", value: prefill.subject || "" });
  const marks = el("input", { class: "ex-input ex-marks", type: "number", value: String(prefill.marks || 4) });
  const opt = [], rows = [];
  for (let i = 0; i < 4; i++) {
    const radio = el("input", { type: "radio", name: grp });
    if ((prefill.correct_index ?? -1) === i) radio.checked = true;
    const inp = el("input", { class: "ex-input", placeholder: "Option " + String.fromCharCode(65 + i), value: (prefill.options || [])[i] || "" });
    opt.push({ radio, inp });
    rows.push(el("label", { class: "ex-opt-edit" }, [radio, inp]));
  }
  const optsBlock = el("div", { class: "ex-opts-block" }, [el("div", { class: "ex-muted ex-opt-hint" }, "Add the options and tick the correct one:"), ...rows]);
  const modelAns = el("textarea", { class: "ex-input ex-ta", placeholder: "Model answer (optional)" });
  modelAns.value = prefill.answer || "";
  const writtenBlock = el("div", { class: "ex-written-block" }, [el("div", { class: "ex-muted" }, "No options — students type their answer (collected for review)."), modelAns]);
  function applyType() { const w = typeSel.value === "written"; optsBlock.hidden = w; writtenBlock.hidden = !w; }
  typeSel.addEventListener("change", applyType);

  // Fill the option fields + tick the correct one from a generated MCQ.
  function applyMcq(mcq) {
    if (!mcq || !Array.isArray(mcq.options)) return;
    if (mcq.stem) { stem.value = mcq.stem; setRich(preview, stem.value); }
    for (let i = 0; i < 4; i++) opt[i].inp.value = (mcq.options[i] || "").trim();
    const ci = Number(mcq.correct_index);
    opt.forEach((o, i) => { o.radio.checked = i === ci; });
    if (mcq.explanation && !modelAns.value.trim()) modelAns.value = mcq.explanation;
    typeSel.value = "mcq"; applyType();
  }

  const aiBtn = el("button", { class: "ex-link", title: "Generate 4 options with AI (Ollama)" }, "✨ AI options");
  const aiStatus = el("span", { class: "ex-muted", style: "margin-left:6px" });
  aiBtn.addEventListener("click", async () => {
    const q = stem.value.trim();
    if (!q) { aiStatus.textContent = "Add the question text first."; return; }
    aiBtn.disabled = true; aiStatus.textContent = "Generating…";
    try {
      const res = await assess.generateMcq({ items: [{ question: q, answer: modelAns.value.trim(), subject: subject.value.trim() }] });
      const mcq = (res.mcqs || [])[0];
      if (mcq) { applyMcq(mcq); aiStatus.textContent = "Generated — review the options."; }
      else { aiStatus.textContent = (res.errors && res.errors[0] && res.errors[0].reason) || "Could not convert this one."; }
    } catch (e) { aiStatus.textContent = e.message || "AI unavailable."; }
    aiBtn.disabled = false;
  });

  const remove = el("button", { class: "ex-link" }, "Remove");
  remove.addEventListener("click", onRemove);
  const node = el("div", { class: "ex-q-editor" }, [
    el("div", { class: "ex-q-editor-head" }, [el("strong", {}, "Question"), el("label", { class: "ex-qtype-wrap" }, [el("span", { class: "ex-muted" }, "Type:"), typeSel]), aiBtn, remove]),
    stem,
    aiStatus,
    el("div", { class: "ex-q-preview-wrap" }, [el("span", { class: "ex-muted" }, "Preview:"), preview]),
    el("div", { class: "ex-q-meta-row" }, [fieldRow("Subject", subject), fieldRow("Marks", marks)]),
    optsBlock, writtenBlock,
  ]);
  applyType();
  function read() {
    const common = { stem: stem.value.trim(), subject: subject.value.trim(), marks: Number(marks.value) || 4, chapter: prefill.chapter || "", source_uid: prefill.source_uid || null };
    if (typeSel.value === "written") return { ...common, type: "written", answer: modelAns.value.trim() };
    return { ...common, type: "mcq", options: opt.map((o) => o.inp.value.trim()), correct_index: opt.findIndex((o) => o.radio.checked) };
  }
  return { node, read };
}

export async function renderCreate(node, { store, navigate }) {
  clear(node);
  const root = el("div", { class: "dash" });
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Loading…"));
  const user = await assess.ensureSession(store);
  clear(root);
  if (!user) { root.appendChild(el("div", { class: "ex-error" }, "Could not start a session.")); return; }
  if (user.role !== "teacher") { root.appendChild(el("div", { class: "ex-empty-card" }, "Exam creation is for teacher accounts.")); return; }

  root.appendChild(el("div", { class: "dash-head" }, [el("div", {}, [el("h2", {}, "Create Exam"), el("p", { class: "ex-muted" }, "Build a general test or an adaptive one.")])]));
  const tGen = el("button", { class: "ec-tab active" }, "📄 General Exam");
  const tAd = el("button", { class: "ec-tab" }, "◑ Adaptive Exam");
  root.appendChild(el("div", { class: "ec-tabs", style: "margin-bottom:16px" }, [tGen, tAd]));
  const body = el("div", {});
  root.appendChild(body);

  let tab = "general";
  function show() {
    tGen.classList.toggle("active", tab === "general");
    tAd.classList.toggle("active", tab === "adaptive");
    clear(body);
    if (tab === "general") buildGeneral(body);
    else buildAdaptive(body);
  }
  tGen.addEventListener("click", () => { tab = "general"; show(); });
  tAd.addEventListener("click", () => { tab = "adaptive"; show(); });
  show();

  // ---------------- General Exam ----------------
  function buildGeneral(container) {
    const name = el("input", { class: "ex-input", placeholder: "e.g. Class 8 Physics — Motion Test" });
    const duration = el("input", { class: "ex-input ex-marks", type: "number", value: "30" });
    const mCorrect = el("input", { class: "ex-input ex-marks", type: "number", value: "4" });
    const mWrong = el("input", { class: "ex-input ex-marks", type: "number", value: "-1" });
    const startAt = el("input", { class: "ex-input", type: "datetime-local" });
    const endAt = el("input", { class: "ex-input", type: "datetime-local" });
    const allowRetake = el("input", { type: "checkbox" });
    const targetClasses = new Set();
    const classTargetChips = el("div", { class: "ec-chips" }, CLASSES.map((c) => {
      const chip = el("button", { class: "ec-chip" }, "Class " + c);
      chip.addEventListener("click", () => { targetClasses.has(c) ? (targetClasses.delete(c), chip.classList.remove("on")) : (targetClasses.add(c), chip.classList.add("on")); });
      return chip;
    }));
    const sectionsInp = el("input", { class: "ex-input", placeholder: "e.g. A, B (optional)" });

    const classSel = el("select", { class: "ex-input" }, [el("option", { value: "" }, "Select class"), ...CLASSES.map((c) => el("option", { value: c }, "Class " + c))]);
    const subjectSel = el("select", { class: "ex-input" }, [el("option", { value: "" }, "Select subject"), ...SUBJECTS.map((s) => el("option", { value: s }, s))]);
    const chapterSel = el("select", { class: "ex-input" }, [el("option", { value: "" }, "All chapters")]);
    chapterSel.disabled = true;
    const chapterNote = el("div", { class: "ex-muted" }, "Select a class and subject to load chapters.");

    async function loadChapters() {
      clear(chapterSel); chapterSel.appendChild(el("option", { value: "" }, "All chapters")); chapterSel.disabled = true;
      const cls = classSel.value, subj = subjectSel.value;
      if (!cls || !subj) { chapterNote.textContent = "Select a class and subject to load chapters."; return; }
      chapterNote.textContent = "Loading chapters…";
      try {
        const facets = await getFacets({ class: [cls], subject: [subj] });
        const chapters = facets.chapter || [];
        if (!chapters.length) { chapterNote.textContent = "No chapters found."; return; }
        chapters.forEach((ch) => chapterSel.appendChild(el("option", { value: String(ch.value) }, `${ch.label || "Chapter"} (${ch.count})`)));
        chapterSel.disabled = false; chapterNote.textContent = "Choose a chapter, then load the questions.";
      } catch (e) { chapterNote.textContent = "Question bank unavailable: " + (e.message || "error"); }
    }
    classSel.addEventListener("change", loadChapters);
    subjectSel.addEventListener("change", loadChapters);

    const editors = [];
    const qList = el("div", { class: "ex-q-list" });
    function addQuestion(prefill = {}) {
      let entry;
      const rm = () => { const i = editors.indexOf(entry); if (i >= 0) { editors.splice(i, 1); qList.removeChild(entry.node); } };
      entry = createQuestionEditor(prefill, rm); editors.push(entry); qList.appendChild(entry.node);
    }

    const selected = new Map();
    let curPage = 1, total = 0;
    const pickStatus = el("div", { class: "ex-muted" });
    const pickList = el("div", { class: "pick-list", hidden: true });
    const pickPager = el("div", { class: "pick-pager" });
    const addSelBtn = el("button", { class: "ex-btn ex-btn-primary" }, "Add selected (0)");
    const aiConvert = el("input", { type: "checkbox" });
    const aiConvertLabel = el("label", { class: "ex-check", title: "Use Ollama to turn theory questions into auto-gradable MCQs as they are added" }, [aiConvert, el("span", {}, "✨ Convert to MCQ with AI on add")]);
    const loadBtn = el("button", { class: "ex-btn ex-btn-primary" }, "Load questions");
    function updateAddBtn() { addSelBtn.textContent = `Add selected (${selected.size})`; addSelBtn.disabled = selected.size === 0; }
    function renderRows(items, subj) {
      clear(pickList); pickList.hidden = false;
      items.forEach((it) => {
        const id = String(it.id);
        const cb = el("input", { type: "checkbox" }); cb.checked = selected.has(id);
        cb.addEventListener("change", () => { cb.checked ? selected.set(id, { id: it.id, stem: it.stem, subject: it.subject || subj, chapter: it.chapter_name, uid: it.uid }) : selected.delete(id); updateAddBtn(); });
        pickList.appendChild(el("label", { class: "pick-row" }, [cb, mathSpan(it.stem), el("span", { class: "pick-meta" }, `${it.has_answer ? "ans✓ " : ""}${it.chapter_name || ""}`.trim())]));
      });
      typeset(pickList);
      clear(pickPager);
      const pages = Math.max(1, Math.ceil(total / PICK_PAGE));
      const prev = el("button", { class: "ex-btn", disabled: curPage <= 1 }, "‹ Prev"); prev.addEventListener("click", () => loadQuestions(curPage - 1));
      const next = el("button", { class: "ex-btn", disabled: curPage >= pages }, "Next ›"); next.addEventListener("click", () => loadQuestions(curPage + 1));
      pickPager.appendChild(prev); pickPager.appendChild(el("span", { class: "ex-muted" }, `Page ${curPage} of ${pages}`)); pickPager.appendChild(next); pickPager.appendChild(aiConvertLabel); pickPager.appendChild(addSelBtn);
    }
    async function loadQuestions(page) {
      const cls = classSel.value, subj = subjectSel.value;
      if (!cls || !subj) { pickStatus.textContent = "Select a class and subject first."; return; }
      pickStatus.textContent = "Loading questions…"; loadBtn.disabled = true;
      const chap = chapterSel.value ? [chapterSel.value] : [];
      try {
        const data = await searchItems({ class: [cls], subject: [subj], chapter: chap, page, pageSize: PICK_PAGE });
        total = data.total || 0; curPage = data.page || page;
        renderRows(data.items || [], subj);
        pickStatus.textContent = total ? `${total} questions found — tick the ones to include.` : "No questions found.";
      } catch (e) { pickStatus.textContent = "Question bank unavailable: " + (e.message || "error"); clear(pickList); clear(pickPager); }
      loadBtn.disabled = false;
    }
    loadBtn.addEventListener("click", () => loadQuestions(1));
    addSelBtn.addEventListener("click", async () => {
      const picks = [...selected.values()];
      const n = picks.length;
      if (!n) return;
      const clearPicks = () => { selected.clear(); updateAddBtn(); pickList.querySelectorAll("input").forEach((cb) => { cb.checked = false; }); };

      if (aiConvert.checked) {
        addSelBtn.disabled = true;
        pickStatus.textContent = `Converting ${n} question(s) to MCQ with AI…`;
        try {
          const res = await assess.generateMcq({ item_ids: picks.map((v) => v.id) });
          const byId = new Map((res.mcqs || []).map((m) => [String(m.source_id), m]));
          let made = 0;
          picks.forEach((v) => {
            const m = byId.get(String(v.id));
            if (m) { made++; addQuestion({ type: "mcq", stem: m.stem, options: m.options, correct_index: m.correct_index, subject: v.subject, chapter: v.chapter, answer: m.explanation, source_uid: v.uid }); }
            else { addQuestion({ stem: v.stem, subject: v.subject, chapter: v.chapter, source_uid: v.uid }); }
          });
          clearPicks();
          pickStatus.textContent = `Added ${n} question(s) — ${made} converted to MCQ, ${n - made} kept as written.`;
        } catch (e) {
          // AI failed -> fall back to the original written behaviour, nothing lost.
          picks.forEach((v) => addQuestion({ stem: v.stem, subject: v.subject, chapter: v.chapter, source_uid: v.uid }));
          clearPicks();
          pickStatus.textContent = `AI unavailable (${e.message || "error"}) — added ${n} as written.`;
        }
        addSelBtn.disabled = false;
        return;
      }

      picks.forEach((v) => addQuestion({ stem: v.stem, subject: v.subject, chapter: v.chapter, source_uid: v.uid }));
      clearPicks();
      pickStatus.textContent = `Added ${n} question(s) below.`;
    });
    updateAddBtn();

    const err = el("div", { class: "ex-auth-err" });
    async function create(hostAfter) {
      err.textContent = "";
      const payload = {
        title: name.value.trim() || `${subjectSel.value || "IIT Foundation"} Test`, exam_type: "IIT Foundation",
        duration_min: Number(duration.value) || 30, marking: { correct: Number(mCorrect.value) || 4, wrong: Number(mWrong.value) || 0, unattempted: 0 },
        start_at: assess.epochFromLocal(startAt.value), end_at: assess.epochFromLocal(endAt.value), allow_retake: allowRetake.checked,
        target_classes: [...targetClasses], target_sections: sectionsInp.value.split(",").map((s) => s.trim()).filter(Boolean),
        questions: editors.map((e) => e.read()),
      };
      try { const { exam_id } = await assess.createExam(payload); if (hostAfter) await assess.setExamStatus(exam_id, "hosted"); navigate("/exams/manage"); }
      catch (e) { err.textContent = e.message || "Could not create the exam."; }
    }
    const addBtn = el("button", { class: "ex-btn" }, "+ Add blank question"); addBtn.addEventListener("click", () => addQuestion());
    const saveBtn = el("button", { class: "ex-btn" }, "Save draft"); saveBtn.addEventListener("click", () => create(false));
    const hostBtn = el("button", { class: "ex-btn ex-btn-primary" }, "Create & host"); hostBtn.addEventListener("click", () => create(true));

    container.appendChild(el("div", { class: "ex-form-card" }, [
      el("div", { class: "ex-q-meta-row" }, [fieldRow("Exam name", name), fieldRow("Duration (min)", duration), fieldRow("Marks / correct", mCorrect), fieldRow("Marks / wrong", mWrong)]),
      el("div", { class: "ex-q-meta-row" }, [fieldRow("Starts (optional)", startAt), fieldRow("Ends (optional)", endAt)]),
      el("label", { class: "ex-check" }, [allowRetake, el("span", {}, "Allow students to retake this test")]),
    ]));
    container.appendChild(el("div", { class: "ex-form-card" }, [
      el("strong", {}, "Assign to (optional)"),
      el("div", { class: "ec-syl-row" }, [el("span", { class: "ec-syl-lbl" }, "Classes:"), classTargetChips]),
      el("div", { class: "ex-q-meta-row" }, [fieldRow("Sections", sectionsInp)]),
    ]));
    container.appendChild(el("div", { class: "ex-form-card" }, [
      el("strong", {}, "Browse questions from the DB"),
      el("div", { class: "ex-q-meta-row" }, [fieldRow("Class", classSel), fieldRow("Subject", subjectSel), fieldRow("Chapter", chapterSel), el("div", { class: "ex-field tr-field-btn" }, [loadBtn])]),
      chapterNote, pickStatus, pickList, pickPager,
    ]));
    container.appendChild(el("h3", { class: "ex-section-title" }, "Questions — key the correct answers"));
    container.appendChild(qList);
    container.appendChild(addBtn);
    container.appendChild(err);
    container.appendChild(el("div", { class: "ex-form-actions" }, [saveBtn, hostBtn]));
  }

  // ---------------- Adaptive Exam ----------------
  function buildAdaptive(container) {
    let mode = "weak";
    const MODES = [["Strength Wise", "strong"], ["Previous Paper", "weak"], ["Error Test", "weak"]];
    const radioRow = el("div", { class: "ec-radios" });
    const radioEls = MODES.map(([label, val], i) => {
      const r = el("span", { class: "ec-radio" + (i === 2 ? " on" : "") }, [el("span", { class: "ec-dot" }), label]);
      r.addEventListener("click", () => { mode = val; radioEls.forEach((x, j) => x.classList.toggle("on", j === i)); });
      radioRow.appendChild(r); return r;
    });
    mode = "weak"; // Error Test default

    const name = el("input", { class: "ex-input", placeholder: "Name of the Adaptive Exam" });
    const ef = el("input", { class: "ex-input ex-marks", type: "number", placeholder: "From" });
    const et = el("input", { class: "ex-input ex-marks", type: "number", placeholder: "To" });
    const branch = el("select", { class: "ex-input" }, [el("option", {}, "Foundation")]);
    const examType = el("select", { class: "ex-input" }, ["IIT Foundation", "Foundation Science", "Foundation Maths"].map((t) => el("option", { value: t }, t)));
    const classSel = el("select", { class: "ex-input" }, [el("option", { value: "" }, "Select…"), ...CLASSES.map((c) => el("option", { value: c }, "Class " + c))]);
    const sectionInp = el("input", { class: "ex-input", placeholder: "e.g. A (optional)" });
    const status = el("div", { class: "ex-muted" });
    const submit = el("button", { class: "ec-submit" }, "Submit");

    submit.addEventListener("click", async () => {
      const klass = classSel.value;
      if (!klass) { status.textContent = "Select a class."; return; }
      submit.disabled = true; status.textContent = "Analyzing the cohort and generating the paper…";
      try {
        const g = await assess.generateAdaptive({ mode, klass, section: sectionInp.value.trim(), total: 20, error_from: ef.value, error_to: et.value });
        if (!g.questions.length) { status.textContent = "No questions found for that class/subject mix."; submit.disabled = false; return; }
        const { exam_id } = await assess.createExam({
          title: name.value.trim() || `Adaptive — Class ${klass}`, exam_type: examType.value || "Adaptive", adaptive: true, duration_min: 30,
          marking: { correct: 4, wrong: -1, unattempted: 0 }, target_classes: [klass], target_sections: sectionInp.value.trim() ? [sectionInp.value.trim()] : [],
          questions: g.questions.map((q) => ({ type: "written", stem: q.stem, answer: q.answer, subject: q.subject, chapter: q.chapter, marks: q.marks, source_uid: q.source_uid })),
        });
        await assess.setExamStatus(exam_id, "hosted");
        navigate("/exams/manage");
      } catch (e) { status.textContent = e.message || "Could not generate."; submit.disabled = false; }
    });

    container.appendChild(el("div", { class: "ex-form-card" }, [
      radioRow,
      el("div", { class: "ec-adapt-row" }, [
        el("div", { class: "ex-field ec-grow" }, [el("span", {}, "Name"), name]),
        el("div", { class: "ex-field" }, [el("span", {}, "Error Range (%)"), el("div", { class: "ec-range" }, [ef, el("span", {}, "–"), et])]),
      ]),
      el("div", { class: "ex-q-meta-row" }, [fieldRow("Branch", branch), fieldRow("Exam", examType), fieldRow("Class", classSel), fieldRow("Section", sectionInp)]),
      status,
      el("div", { class: "ec-submit-row" }, [submit]),
    ]));
  }
}
