// Available Tests + recent results (Slice 1).
import { el, clear } from "../../../ui/el.js";
import * as assess from "../../../api/assess.api.js";

function fmtDate(ts) {
  try { return new Date(ts * 1000).toLocaleString(); } catch { return ""; }
}

export async function renderExamList(node, { store, navigate }) {
  clear(node);
  const root = el("div", { class: "ex-page" });
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Loading…"));

  const user = await assess.ensureSession(store);
  if (!user) { clear(root); root.appendChild(el("div", { class: "ex-error" }, "Could not start a session.")); return; }

  let exams = [], attempts = [];
  try {
    [exams, attempts] = await Promise.all([
      assess.listExams().then((d) => d.exams || []),
      assess.listAttempts().then((d) => d.attempts || []),
    ]);
  } catch (e) {
    clear(root);
    root.appendChild(el("div", { class: "ex-error" }, e.message || "Could not load tests."));
    return;
  }

  clear(root);

  // header with user + sign out
  const signout = el("button", { class: "ex-link" }, "Sign out");
  signout.addEventListener("click", () => { assess.clearSession(store); navigate("/login"); });
  root.appendChild(el("div", { class: "ex-page-head" }, [
    el("div", {}, [el("h2", {}, "Available Tests"), el("p", { class: "ex-muted" }, `Signed in as ${user.name || user.username}`)]),
    signout,
  ]));

  // exam cards
  const grid = el("div", { class: "ex-card-grid" });
  if (!exams.length) grid.appendChild(el("div", { class: "ex-muted" }, "No tests are hosted right now."));
  for (const ex of exams) {
    const phase = ex.phase || "live";
    const canStart = phase === "live" && (!ex.attempted || ex.allow_retake);
    let action;
    if (canStart) {
      action = el("button", { class: "ex-btn ex-btn-primary" }, ex.attempted ? "Retake →" : "Start test →");
      action.addEventListener("click", () => navigate("/exams/take/" + ex.id));
    } else if (ex.attempted) {
      action = el("button", { class: "ex-btn" }, "View result");
      action.addEventListener("click", () => navigate("/exams/result/" + ex.attempt_id));
    } else if (phase === "upcoming") {
      action = el("button", { class: "ex-btn", disabled: true }, "Starts " + assess.fmtWhen(ex.start_at));
    } else {
      action = el("button", { class: "ex-btn", disabled: true }, "Closed");
    }
    grid.appendChild(el("div", { class: "ex-card" }, [
      el("div", { class: "ex-card-head-row" }, [
        el("span", { class: "ex-card-tag" }, ex.exam_type || "Test"),
        el("span", { class: "ex-phase ex-phase-" + phase }, assess.PHASE_LABEL[phase] || phase),
      ]),
      el("h3", {}, ex.title),
      el("div", { class: "ex-card-meta" }, [
        el("span", {}, `${ex.total_questions} questions`),
        el("span", {}, `${ex.duration_min} min`),
        ...(ex.start_at ? [el("span", {}, assess.fmtWhen(ex.start_at))] : []),
      ]),
      action,
    ]));
  }
  root.appendChild(grid);

  // recent results
  root.appendChild(el("h3", { class: "ex-section-title" }, "Recent results"));
  if (!attempts.length) {
    root.appendChild(el("div", { class: "ex-muted" }, "You haven't taken any tests yet."));
  } else {
    const list = el("div", { class: "ex-result-list" });
    for (const a of attempts) {
      const open = el("button", { class: "ex-link" }, "View report");
      open.addEventListener("click", () => navigate("/exams/result/" + a.id));
      list.appendChild(el("div", { class: "ex-result-row" }, [
        el("div", {}, [el("strong", {}, a.exam_title), el("div", { class: "ex-muted" }, fmtDate(a.submitted_at))]),
        el("div", { class: "ex-result-score" }, `${a.score}/${a.max_marks} · ${a.percentage}%`),
        open,
      ]));
    }
    root.appendChild(list);
  }
}
