// Test-taking engine (Slice 1): question navigation, palette, timer, submit.
import { el, clear } from "../../../ui/el.js";
import * as assess from "../../../api/assess.api.js";
import { mathSpan, typeset } from "../../../ui/rich.js";

function fmtTime(s) {
  s = Math.max(0, s | 0);
  const m = Math.floor(s / 60), r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

export function createRunner(node, { examId, navigate }) {
  let exam = null, idx = 0, submitted = false, timer = null, timeLeft = 0;
  const answers = {};            // qid -> chosen index
  const marked = new Set();
  const root = el("div", { class: "ex-runner" });
  clear(node);
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Loading test…"));

  assess.ensureSession({ setState() {} }).then(() => assess.getExam(examId)).then((d) => {
    exam = d.exam;
    if (exam.phase && exam.phase !== "live") {
      clear(root);
      root.appendChild(el("div", { class: "ex-empty-card" },
        exam.phase === "upcoming" ? "This test hasn’t started yet." : "This test has closed."));
      return;
    }
    timeLeft = (exam.duration_min || 10) * 60;
    startTimer();
    render();
  }).catch((e) => {
    clear(root);
    root.appendChild(el("div", { class: "ex-error" }, e.message || "Could not load the test."));
  });

  function startTimer() {
    timer = setInterval(() => {
      timeLeft -= 1;
      const t = root.querySelector(".ex-timer");
      if (t) t.textContent = fmtTime(timeLeft);
      if (timeLeft <= 0) submit();
    }, 1000);
  }
  function stopTimer() { if (timer) clearInterval(timer); timer = null; }

  function answered(qid) {
    const v = answers[qid];
    return v != null && String(v).trim() !== "";
  }
  function statusOf(i) {
    const qid = exam.questions[i].id;
    if (marked.has(qid)) return "marked";
    if (answered(qid)) return "answered";
    return "unseen";
  }

  async function submit() {
    if (submitted) return;
    submitted = true;
    stopTimer();
    const spent = (exam.duration_min || 10) * 60 - timeLeft;
    try {
      const { attempt_id } = await assess.submitAttempt(examId, { answers, time_spent_sec: spent });
      navigate("/exams/result/" + attempt_id);
    } catch (e) {
      submitted = false;
      clear(root);
      root.appendChild(el("div", { class: "ex-error" }, "Submit failed: " + (e.message || "error")));
    }
  }

  function render() {
    if (!exam) return;
    clear(root);
    const q = exam.questions[idx];

    // header
    root.appendChild(el("div", { class: "ex-runner-head" }, [
      el("div", {}, [el("strong", {}, exam.title), el("span", { class: "ex-card-tag" }, exam.exam_type || "")]),
      el("div", { class: "ex-timer-wrap" }, [el("span", { class: "ex-muted" }, "Time left "), el("span", { class: "ex-timer" }, fmtTime(timeLeft))]),
    ]));

    // body: question + palette
    let answerArea;
    if (q.type === "written") {
      const ta = el("textarea", { class: "ex-input ex-ta ex-written-input", placeholder: "Type your answer…" });
      ta.value = answers[q.id] != null ? String(answers[q.id]) : "";
      ta.addEventListener("input", () => { answers[q.id] = ta.value; }); // no re-render (keep focus)
      answerArea = el("div", { class: "ex-written" }, [ta]);
    } else {
      const opts = el("div", { class: "ex-options" });
      (q.options || []).forEach((opt, oi) => {
        const chosen = answers[q.id] === oi;
        const row = el("label", { class: "ex-option" + (chosen ? " selected" : "") }, [
          el("span", { class: "ex-option-key" }, String.fromCharCode(65 + oi)),
          mathSpan(opt),
        ]);
        row.addEventListener("click", () => { answers[q.id] = oi; render(); });
        opts.appendChild(row);
      });
      answerArea = opts;
    }

    const qpanel = el("div", { class: "ex-qpanel" }, [
      el("div", { class: "ex-qmeta" }, [
        el("span", {}, `Question ${idx + 1} of ${exam.questions.length}`),
        el("span", { class: "ex-card-tag" }, `${q.subject || ""}${q.type === "written" ? " · Written" : ""}`),
      ]),
      el("div", { class: "ex-qstem" }, [mathSpan(q.stem)]),
      answerArea,
      el("div", { class: "ex-runner-nav" }, [
        navBtn("‹ Prev", () => { if (idx > 0) { idx--; render(); } }, idx === 0),
        markBtn(q),
        clearBtn(q),
        navBtn(idx === exam.questions.length - 1 ? "Next ›" : "Next ›",
          () => { if (idx < exam.questions.length - 1) { idx++; render(); } }, idx === exam.questions.length - 1),
      ]),
    ]);

    // palette
    const pal = el("div", { class: "ex-palette" });
    exam.questions.forEach((_, i) => {
      const b = el("button", { class: "ex-pal-btn ex-pal-" + statusOf(i) + (i === idx ? " current" : "") }, String(i + 1));
      b.addEventListener("click", () => { idx = i; render(); });
      pal.appendChild(b);
    });
    const submitBtn = el("button", { class: "ex-btn ex-btn-primary ex-btn-block" }, "Submit test");
    submitBtn.addEventListener("click", () => {
      const blanks = exam.questions.filter((qq) => !answered(qq.id)).length;
      if (blanks === 0 || confirm(`${blanks} question(s) unanswered. Submit anyway?`)) submit();
    });
    const sidebar = el("div", { class: "ex-sidebar" }, [
      el("div", { class: "ex-pal-legend" }, [
        legend("answered", "Answered"), legend("marked", "Marked"), legend("unseen", "Not answered"),
      ]),
      pal,
      submitBtn,
    ]);

    root.appendChild(el("div", { class: "ex-runner-body" }, [qpanel, sidebar]));
    typeset(root);
  }

  function navBtn(label, fn, disabled) {
    const b = el("button", { class: "ex-btn", disabled: !!disabled }, label);
    b.addEventListener("click", fn);
    return b;
  }
  function markBtn(q) {
    const on = marked.has(q.id);
    const b = el("button", { class: "ex-btn" }, on ? "Unmark" : "Mark for review");
    b.addEventListener("click", () => { on ? marked.delete(q.id) : marked.add(q.id); render(); });
    return b;
  }
  function clearBtn(q) {
    const b = el("button", { class: "ex-btn" }, "Clear");
    b.addEventListener("click", () => { delete answers[q.id]; render(); });
    return b;
  }
  function legend(kind, label) {
    return el("span", { class: "ex-legend" }, [el("span", { class: "ex-dot ex-pal-" + kind }), label]);
  }

  return { destroy: stopTimer };
}
