// Result + per-test performance analysis (Slice 1).
import { el, clear } from "../../../ui/el.js";
import * as assess from "../../../api/assess.api.js";
import { mathSpan, setRich, typeset } from "../../../ui/rich.js";

function tile(label, value, accent) {
  return el("div", { class: "ex-tile ex-tile-" + (accent || "blue") }, [
    el("div", { class: "ex-tile-val" }, String(value)),
    el("div", { class: "ex-tile-lbl" }, label),
  ]);
}

function bar(pct, accent) {
  return el("div", { class: "ex-bar" }, [el("div", { class: "ex-bar-fill ex-bar-" + (accent || "blue"), style: `width:${Math.max(0, Math.min(100, pct))}%` })]);
}

export async function renderResult(node, { navigate, attemptId }) {
  clear(node);
  const root = el("div", { class: "ex-page" });
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Loading report…"));

  let attempt;
  try {
    await assess.ensureSession({ setState() {} });
    attempt = (await assess.getAttempt(attemptId)).attempt;
  }
  catch (e) {
    clear(root);
    root.appendChild(el("div", { class: "ex-error" }, e.message || "Could not load report."));
    return;
  }
  clear(root);

  const r = attempt.result;
  const back = el("button", { class: "ex-link" }, "‹ Back to tests");
  back.addEventListener("click", () => navigate("/exams"));
  root.appendChild(el("div", { class: "ex-page-head" }, [
    el("div", {}, [el("h2", {}, attempt.exam_title), el("p", { class: "ex-muted" }, "Performance report")]),
    back,
  ]));

  // KPI tiles
  root.appendChild(el("div", { class: "ex-tiles" }, [
    tile("Score", `${r.score}/${r.max_marks}`, "blue"),
    tile("Percentage", `${r.percentage}%`, "green"),
    tile("Accuracy", `${r.accuracy}%`, "pink"),
    tile("Correct", `${r.counts.correct}/${r.counts.total}`, "teal"),
  ]));

  // subject breakdown
  root.appendChild(el("h3", { class: "ex-section-title" }, "Subject-wise performance"));
  const subjWrap = el("div", { class: "ex-subj-list" });
  for (const [subject, v] of Object.entries(r.per_subject || {})) {
    subjWrap.appendChild(el("div", { class: "ex-subj-row" }, [
      el("div", { class: "ex-subj-name" }, subject),
      bar(v.accuracy, "green"),
      el("div", { class: "ex-subj-stat" }, `${v.accuracy}%  ·  ${v.correct}✓ ${v.incorrect}✗ ${v.unattempted}—`),
    ]));
  }
  root.appendChild(subjWrap);

  // per-question review
  root.appendChild(el("h3", { class: "ex-section-title" }, "Question review"));
  const key = attempt.answer_key || {};
  const models = attempt.model_answers || {};
  const review = el("div", { class: "ex-review" });
  (attempt.exam ? attempt.exam.questions : []).forEach((q, i) => {
    if (q.type === "written") {
      const resp = attempt.answers[q.id];
      const answered = resp != null && String(resp).trim() !== "";
      review.appendChild(el("div", { class: "ex-rev-card ex-rev-review" }, [
        el("div", { class: "ex-rev-head" }, [
          el("span", {}, [`Q${i + 1}. `, mathSpan(q.stem)]),
          el("span", { class: "ex-rev-badge ex-rev-review" }, "For review"),
        ]),
        el("div", { class: "ex-rev-written" }, [
          el("div", { class: "ex-muted" }, "Your answer:"),
          el("div", { class: "ex-detail-text" }, answered ? String(resp) : "—"),
          ...(models[q.id] ? [el("div", { class: "ex-muted", style: "margin-top:8px" }, "Model answer:"), (() => { const d = el("div", { class: "ex-detail-text" }); setRich(d, models[q.id]); return d; })()] : []),
        ]),
      ]));
      return;
    }
    const chosen = attempt.answers[q.id];
    const chosenIdx = chosen == null || chosen === "" ? null : Number(chosen);
    const correctIdx = key[q.id];
    const state = chosenIdx == null ? "skip" : chosenIdx === correctIdx ? "right" : "wrong";
    const opts = (q.options || []).map((opt, oi) =>
      el("div", { class: "ex-rev-opt" + (oi === correctIdx ? " correct" : "") + (oi === chosenIdx && state === "wrong" ? " chosen-wrong" : "") }, [
        el("span", { class: "ex-option-key" }, String.fromCharCode(65 + oi)), mathSpan(opt),
      ]));
    review.appendChild(el("div", { class: "ex-rev-card ex-rev-" + state }, [
      el("div", { class: "ex-rev-head" }, [
        el("span", {}, [`Q${i + 1}. `, mathSpan(q.stem)]),
        el("span", { class: "ex-rev-badge ex-rev-" + state }, state === "right" ? "Correct" : state === "wrong" ? "Wrong" : "Skipped"),
      ]),
      el("div", { class: "ex-rev-opts" }, opts),
    ]));
  });
  root.appendChild(review);
  typeset(root);
}
