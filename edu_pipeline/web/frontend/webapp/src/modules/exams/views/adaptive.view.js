// Adaptive Exam (teacher): generate a personalized test for a student from their
// performance profile — weighted toward weak (or strong) subjects, at a
// difficulty matched to their level — then host it assigned to that student.
import { el, clear } from "../../../ui/el.js";
import * as assess from "../../../api/assess.api.js";
import { mathSpan, typeset } from "../../../ui/rich.js";

const DIFF_CLASS = { Easy: "easy", Moderate: "blue", Difficult: "pink" };

export async function renderAdaptive(node, { store, navigate }) {
  clear(node);
  const root = el("div", { class: "dash" });
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Loading…"));

  const user = await assess.ensureSession(store);
  clear(root);
  if (!user) { root.appendChild(el("div", { class: "ex-error" }, "Could not start a session.")); return; }
  if (user.role !== "teacher") { root.appendChild(el("div", { class: "ex-empty-card" }, "Adaptive exams are created by teachers.")); return; }

  let students = [];
  try { students = (await assess.listStudents()).students || []; } catch (_) {}

  const studentSel = el("select", { class: "ex-input" }, [
    el("option", { value: "" }, students.length ? "Select a student" : "No students yet"),
    ...students.map((s) => el("option", { value: s.id }, `${s.name || s.username} — Class ${s.klass || "?"}${s.section ? "/" + s.section : ""} · ${s.attempts} attempt${s.attempts === 1 ? "" : "s"}`)),
  ]);
  const modeSel = el("select", { class: "ex-input" }, [
    el("option", { value: "weak" }, "Target weak areas (remediation)"),
    el("option", { value: "strong" }, "Challenge strengths"),
  ]);
  const total = el("input", { class: "ex-input ex-marks", type: "number", value: "10" });
  const genBtn = el("button", { class: "ex-btn ex-btn-primary" }, "Analyze & generate");
  const status = el("div", { class: "ex-muted" });
  const out = el("div", {});

  let generated = null;

  genBtn.addEventListener("click", async () => {
    const sid = studentSel.value;
    if (!sid) { status.textContent = "Pick a student first."; return; }
    status.textContent = "Analyzing performance and selecting questions…";
    genBtn.disabled = true;
    clear(out);
    try {
      generated = await assess.generateAdaptive({ student_id: sid, mode: modeSel.value, total: Number(total.value) || 10 });
      renderResult();
      status.textContent = "";
    } catch (e) {
      status.textContent = e.message || "Could not generate.";
    }
    genBtn.disabled = false;
  });

  function bar(pct, accent) { return el("div", { class: "ex-bar" }, [el("div", { class: "ex-bar-fill ex-bar-" + (accent || "blue"), style: `width:${Math.max(0, Math.min(100, pct))}%` })]); }

  function renderResult() {
    clear(out);
    const g = generated;
    const p = g.profile;

    // performance profile
    out.appendChild(el("h3", { class: "ex-section-title" }, `Performance profile — ${g.student.name}`));
    out.appendChild(el("div", { class: "dash-cards" }, [
      el("div", { class: "dash-card dash-blue" }, [el("div", { class: "dash-card-top" }, [el("span", { class: "dash-label" }, "ATTEMPTS"), el("span", { class: "dash-icon" }, "📝")]), el("div", { class: "dash-value" }, String(p.attempts))]),
      el("div", { class: "dash-card dash-green" }, [el("div", { class: "dash-card-top" }, [el("span", { class: "dash-label" }, "OVERALL ACCURACY"), el("span", { class: "dash-icon" }, "🎯")]), el("div", { class: "dash-value" }, `${p.overall_accuracy}%`)]),
      el("div", { class: "dash-card dash-amber" }, [el("div", { class: "dash-card-top" }, [el("span", { class: "dash-label" }, "FOCUS"), el("span", { class: "dash-icon" }, "🧠")]), el("div", { class: "dash-value", style: "font-size:18px" }, g.mode === "weak" ? "Weak areas" : "Strengths")]),
      el("div", { class: "dash-card dash-pink" }, [el("div", { class: "dash-card-top" }, [el("span", { class: "dash-label" }, "DIFFICULTY"), el("span", { class: "dash-icon" }, "📈")]), el("div", { class: "dash-value", style: "font-size:18px" }, g.plan.target_level)]),
    ]));

    const subs = Object.entries(p.per_subject || {});
    if (subs.length) {
      const wrap = el("div", { class: "ex-subj-list" });
      subs.sort((a, b) => a[1].accuracy - b[1].accuracy).forEach(([s, v]) => {
        const weak = (p.weak_subjects || []).includes(s);
        wrap.appendChild(el("div", { class: "ex-subj-row" }, [
          el("div", { class: "ex-subj-name" }, [s, weak ? el("span", { class: "ex-phase ex-phase-upcoming", style: "margin-left:6px" }, "weak") : null]),
          bar(v.accuracy, v.accuracy >= 60 ? "green" : "pink"),
          el("div", { class: "ex-subj-stat" }, `${v.accuracy}%`),
        ]));
      });
      out.appendChild(wrap);
    } else {
      out.appendChild(el("div", { class: "ex-empty-card" }, "No attempt history yet — generating a balanced starter test."));
    }

    // generated questions
    out.appendChild(el("h3", { class: "ex-section-title" }, `Generated test — ${g.questions.length} questions`));
    out.appendChild(el("p", { class: "ex-muted" }, "Personalized selection from the question bank. Written questions (students type answers; collected with the model answer for review)."));
    const list = el("div", { class: "pick-list" });
    g.questions.forEach((q, i) => {
      list.appendChild(el("div", { class: "pick-row" }, [
        el("span", { class: "ex-muted", style: "flex:0 0 24px" }, String(i + 1)),
        mathSpan(q.stem),
        el("span", { class: "pick-meta" }, [
          el("span", { class: "ex-phase ex-phase-" + (DIFF_CLASS[q.difficulty] === "easy" ? "live" : DIFF_CLASS[q.difficulty] === "pink" ? "ended" : "upcoming") }, q.difficulty),
          " ", q.subject,
        ]),
      ]));
    });
    out.appendChild(list);
    typeset(list);

    const hostBtn = el("button", { class: "ex-btn ex-btn-primary" }, `Host for ${g.student.name}`);
    hostBtn.addEventListener("click", () => hostAdaptive());
    out.appendChild(el("div", { class: "ex-form-actions" }, [hostBtn]));
  }

  async function hostAdaptive() {
    const g = generated;
    try {
      const { exam_id } = await assess.createExam({
        title: `Adaptive — ${g.student.name} (${g.mode === "weak" ? "weak areas" : "strengths"})`,
        exam_type: "Adaptive", adaptive: true, duration_min: 30,
        marking: { correct: 4, wrong: -1, unattempted: 0 },
        target_students: [g.student.id],
        questions: g.questions.map((q) => ({ type: "written", stem: q.stem, answer: q.answer, subject: q.subject, chapter: q.chapter, marks: q.marks, source_uid: q.source_uid })),
      });
      await assess.setExamStatus(exam_id, "hosted");
      navigate("/exams/manage");
    } catch (e) { status.textContent = e.message || "Could not host."; }
  }

  root.appendChild(el("div", { class: "dash-head" }, [el("div", {}, [el("h2", {}, "Adaptive Exam"), el("p", { class: "ex-muted" }, "Generate a personalized test from a student’s performance.")])]));
  root.appendChild(el("div", { class: "ex-form-card" }, [
    el("div", { class: "ex-q-meta-row" }, [
      el("div", { class: "ex-field" }, [el("span", {}, "Student"), studentSel]),
      el("div", { class: "ex-field" }, [el("span", {}, "Focus"), modeSel]),
      el("div", { class: "ex-field" }, [el("span", {}, "Questions"), total]),
      el("div", { class: "ex-field tr-field-btn" }, [genBtn]),
    ]),
    status,
  ]));
  root.appendChild(out);
}
