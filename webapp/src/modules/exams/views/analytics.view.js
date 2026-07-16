// Overall performance dashboard (Slice 1): KPIs + score trend + subject strengths.
import { el, clear } from "../../../ui/el.js";
import * as assess from "../../../api/assess.api.js";

function tile(label, value, accent) {
  return el("div", { class: "ex-tile ex-tile-" + (accent || "blue") }, [
    el("div", { class: "ex-tile-val" }, String(value)),
    el("div", { class: "ex-tile-lbl" }, label),
  ]);
}

function accAccent(p) { return p >= 60 ? "green" : p >= 35 ? "blue" : "pink"; }

export async function renderAnalytics(node, { store, navigate }) {
  clear(node);
  const root = el("div", { class: "ex-page" });
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Loading reports…"));

  const user = await assess.ensureSession(store);
  if (!user) { clear(root); root.appendChild(el("div", { class: "ex-error" }, "Could not start a session.")); return; }

  let a;
  try { a = (await assess.analytics()).analytics; }
  catch (e) {
    clear(root);
    root.appendChild(el("div", { class: "ex-error" }, e.message || "Could not load reports."));
    return;
  }
  clear(root);

  const take = el("button", { class: "ex-btn ex-btn-primary" }, "Take a test →");
  take.addEventListener("click", () => navigate("/exams"));
  root.appendChild(el("div", { class: "ex-page-head" }, [
    el("div", {}, [el("h2", {}, "My Performance"),
      el("p", { class: "ex-muted" }, `Across ${a.exams_taken} test${a.exams_taken === 1 ? "" : "s"}`)]),
    take,
  ]));

  if (!a.exams_taken) {
    root.appendChild(el("div", { class: "ex-empty-card" }, "No attempts yet — take a test to see your performance report."));
    return;
  }

  // overall accuracy across attempts
  let correct = 0, attempted = 0;
  for (const v of Object.values(a.per_subject || {})) { correct += v.correct; attempted += v.correct + v.incorrect; }
  const overallAcc = attempted ? Math.round(1000 * correct / attempted) / 10 : 0;

  root.appendChild(el("div", { class: "ex-tiles" }, [
    tile("Tests taken", a.exams_taken, "blue"),
    tile("Average", `${a.avg_percentage}%`, "green"),
    tile("Best", `${a.best_percentage}%`, "pink"),
    tile("Accuracy", `${overallAcc}%`, "teal"),
  ]));

  // score trend
  root.appendChild(el("h3", { class: "ex-section-title" }, "Score trend"));
  const chart = el("div", { class: "ex-chart" });
  (a.trend || []).forEach((t) => {
    chart.appendChild(el("div", { class: "ex-chart-col" }, [
      el("div", { class: "ex-chart-barwrap" }, [
        el("div", { class: "ex-chart-bar", style: `height:${Math.max(2, t.percentage)}%`, title: `${t.percentage}%` }),
      ]),
      el("div", { class: "ex-chart-pct" }, `${t.percentage}%`),
      el("div", { class: "ex-chart-lbl", title: t.exam_title }, t.exam_title),
    ]));
  });
  root.appendChild(chart);

  // subject strengths (best -> weakest)
  root.appendChild(el("h3", { class: "ex-section-title" }, "Subject strengths"));
  const subjWrap = el("div", { class: "ex-subj-list" });
  const subs = Object.entries(a.per_subject || {}).sort((x, y) => y[1].accuracy - x[1].accuracy);
  for (const [s, v] of subs) {
    subjWrap.appendChild(el("div", { class: "ex-subj-row" }, [
      el("div", { class: "ex-subj-name" }, s),
      el("div", { class: "ex-bar" }, [el("div", { class: "ex-bar-fill ex-bar-" + accAccent(v.accuracy), style: `width:${v.accuracy}%` })]),
      el("div", { class: "ex-subj-stat" }, `${v.accuracy}%  ·  ${v.correct}✓ ${v.incorrect}✗ ${v.unattempted}—`),
    ]));
  }
  root.appendChild(subjWrap);
}
