// Practice result analysis -- the PRD's post-submission report.
// Overall score, accuracy by topic / difficulty / cognitive level, time spent,
// every question with the correct solution, and the recommended next action.

import { el, clear } from "../../../ui/el.js";
import * as practice from "../../../api/practice.api.js";

function stat(label, value, sub, accent) {
  return el("div", { class: "dash-card dash-" + (accent || "blue") }, [
    el("div", { class: "dash-card-top" }, [el("span", { class: "dash-label" }, label)]),
    el("div", { class: "dash-value" }, String(value)),
    el("div", { class: "dash-sub" }, sub || ""),
  ]);
}

// A labelled accuracy bar; used for the topic / difficulty / Bloom breakdowns.
function breakdown(title, obj) {
  const rows = Object.entries(obj || {});
  if (!rows.length) return null;
  const list = el("div", { class: "pr-bars" });
  rows.sort((a, b) => a[1].accuracy - b[1].accuracy).forEach(([key, b]) => {
    list.appendChild(el("div", { class: "pr-bar-row" }, [
      el("div", { class: "pr-bar-label" }, key),
      el("div", { class: "pr-bar" },
        el("div", { class: "pr-bar-fill", style: `width:${b.accuracy}%` })),
      el("div", { class: "pr-bar-num" }, `${b.accuracy}% (${b.correct}/${b.answered})`),
    ]));
  });
  return el("div", { class: "pr-breakdown" }, [
    el("h3", { class: "ex-section-title" }, title), list,
  ]);
}

export async function renderPracticeReport(node, { sessionId, navigate }) {
  clear(node);
  const root = el("div", { class: "pr" });
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Building your report…"));

  let rep;
  try {
    rep = (await practice.report(sessionId)).report;
  } catch (e) {
    clear(root);
    root.appendChild(el("div", { class: "ex-error" }, e.message || "Could not load the report."));
    return;
  }

  clear(root);
  const again = el("button", { class: "ex-btn ex-btn-primary" }, "Practise again →");
  again.addEventListener("click", () => navigate("/practice"));
  root.appendChild(el("div", { class: "dash-head" }, [
    el("div", {}, [
      el("h2", {}, rep.label + " — results"),
      el("p", { class: "ex-muted" }, rep.chapter_name || "Mixed practice"),
    ]),
    again,
  ]));

  const c = rep.counts;
  const cards = [
    stat("SCORE", `${rep.score_pct}%`, `${c.correct} of ${c.total} correct`, "blue"),
    stat("ACCURACY", `${rep.accuracy}%`, `of ${c.attempted} attempted`, "green"),
    stat("SKIPPED", c.skipped, "not attempted", "amber"),
    stat("AVG TIME", practice.fmtDuration(rep.avg_time_sec), `${practice.fmtDuration(rep.time_spent_sec)} total`, "pink"),
  ];
  if (rep.mastery) {
    cards.push(stat("MASTERY", rep.mastery.band, `${rep.mastery.score}% chapter score`,
      rep.mastery.passed ? "green" : "amber"));
  }
  root.appendChild(el("div", { class: "dash-cards" }, cards));

  if (rep.recommendation) {
    const act = el("button", { class: "ex-btn" }, "Do this next →");
    act.addEventListener("click", () => navigate("/practice"));
    root.appendChild(el("div", { class: "pr-reco" }, [
      el("div", {}, [
        el("strong", {}, "Recommended next"),
        el("div", { class: "ex-muted" }, rep.recommendation.text),
      ]),
      act,
    ]));
  }

  [
    breakdown("Accuracy by topic", rep.per_topic),
    breakdown("Accuracy by difficulty", rep.per_difficulty),
    breakdown("Accuracy by cognitive level", rep.per_cognitive_level),
  ].filter(Boolean).forEach((b) => root.appendChild(b));

  // --- question-by-question review ---
  root.appendChild(el("h3", { class: "ex-section-title" }, "Question review"));
  const list = el("div", { class: "pr-review" });
  rep.questions.forEach((q) => {
    const verdict = q.is_correct === null ? "Skipped" : (q.is_correct ? "Correct" : "Incorrect");
    const cls = q.is_correct === null ? "draft" : (q.is_correct ? "live" : "closed");
    const opts = el("div", { class: "pr-review-options" });
    q.options.forEach((text, i) => {
      let k = "pr-review-opt";
      if (i === q.correct_index) k += " pr-option-correct";
      else if (i === q.chosen) k += " pr-option-wrong";
      opts.appendChild(el("div", { class: k }, `${String.fromCharCode(65 + i)}. ${text}`));
    });
    list.appendChild(el("details", { class: "pr-review-item" }, [
      el("summary", {}, [
        el("span", { class: "ex-badge ex-badge-" + cls }, verdict),
        el("span", { class: "pr-review-stem" }, `${q.index + 1}. ${q.stem}`),
        el("span", { class: "ex-muted" }, practice.fmtDuration(q.time_sec)),
      ]),
      opts,
      q.learning_objective ? el("div", { class: "ex-muted pr-review-obj" }, q.learning_objective) : null,
    ].filter(Boolean)));
  });
  root.appendChild(list);
}
