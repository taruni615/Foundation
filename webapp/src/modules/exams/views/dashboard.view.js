// Dashboard — role-aware: students get a student dashboard, teachers/admins get
// the management dashboard.
import { el, clear } from "../../../ui/el.js";
import * as assess from "../../../api/assess.api.js";

function statCard(icon, label, value, accent, sub) {
  return el("div", { class: "dash-card dash-" + (accent || "blue") }, [
    el("div", { class: "dash-card-top" }, [el("span", { class: "dash-label" }, label), el("span", { class: "dash-icon" }, icon)]),
    el("div", { class: "dash-value" }, String(value)),
    el("div", { class: "dash-sub" }, sub || ""),
  ]);
}
function quick(title, sub, route, navigate) {
  const c = el("div", { class: "dash-quick-card" }, [el("strong", {}, title), el("div", { class: "ex-muted" }, sub)]);
  c.addEventListener("click", () => navigate(route));
  return c;
}
function fmtDate(ts) { try { return new Date(ts * 1000).toLocaleDateString(); } catch { return ""; } }

export async function renderDashboard(node, { store, navigate }) {
  clear(node);
  const root = el("div", { class: "dash" });
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Loading dashboard…"));

  const user = await assess.ensureSession(store);
  if (!user) { clear(root); root.appendChild(el("div", { class: "ex-error" }, "Could not start a session.")); return; }

  if (user.role === "student") return renderStudent(root, user, navigate);
  return renderTeacher(root, user, navigate);
}

// ---- Teacher / admin dashboard ----
async function renderTeacher(root, user, navigate) {
  let exams = [];
  try { exams = (await assess.listMyExams()).exams || []; } catch (_) {}
  clear(root);

  const hosted = exams.filter((e) => e.status === "hosted").length;
  const drafts = exams.filter((e) => e.status !== "hosted").length;
  const attempts = exams.reduce((a, e) => a + (e.attempt_count || 0), 0);

  const createBtn = el("button", { class: "ex-btn ex-btn-primary" }, "+ Create Exam");
  createBtn.addEventListener("click", () => navigate("/exams/create"));
  root.appendChild(el("div", { class: "dash-head" }, [
    el("div", {}, [el("h2", {}, "Teacher Dashboard"), el("p", { class: "ex-muted" }, `Welcome back, ${user.name || "Teacher"}`)]),
    createBtn,
  ]));

  root.appendChild(el("div", { class: "dash-cards" }, [
    statCard("📄", "TOTAL EXAMS", exams.length, "blue", `${hosted} hosted`),
    statCard("🟢", "HOSTED · LIVE", hosted, "green", "visible to students"),
    statCard("📝", "DRAFTS", drafts, "amber", "not yet hosted"),
    statCard("👥", "TOTAL ATTEMPTS", attempts, "pink", "across all exams"),
  ]));

  root.appendChild(el("h3", { class: "ex-section-title" }, "Recent exams"));
  if (!exams.length) root.appendChild(el("div", { class: "ex-empty-card" }, "No exams yet — create your first test."));
  else {
    const list = el("div", { class: "ex-manage-list" });
    exams.slice(0, 6).forEach((ex) => {
      const view = el("button", { class: "ex-link" }, ex.attempt_count ? "View report" : "Manage");
      view.addEventListener("click", () => navigate(ex.attempt_count ? "/exams/reports/" + ex.id : "/exams/manage"));
      list.appendChild(el("div", { class: "ex-manage-row" }, [
        el("div", {}, [el("strong", {}, ex.title), el("div", { class: "ex-muted" }, `${ex.exam_type} · ${ex.total_questions} Q · ${ex.attempt_count} attempts`)]),
        el("span", { class: "ex-badge ex-badge-" + (ex.status === "hosted" ? "live" : "draft") }, ex.status === "hosted" ? "Hosted" : "Draft"),
        view,
      ]));
    });
    root.appendChild(list);
  }

  root.appendChild(el("h3", { class: "ex-section-title" }, "Quick actions"));
  root.appendChild(el("div", { class: "dash-quick" }, [
    quick("Create Exam", "Build a new test", "/exams/create", navigate),
    quick("Manage & Host", "Publish to students", "/exams/manage", navigate),
    quick("Test Reports", "Class-wide analytics", "/exams/reports", navigate),
  ]));
}

// ---- Student dashboard ----
async function renderStudent(root, user, navigate) {
  let exams = [], attempts = [], analytics = null;
  try {
    [exams, attempts, analytics] = await Promise.all([
      assess.listExams().then((d) => d.exams || []),
      assess.listAttempts().then((d) => d.attempts || []),
      assess.analytics().then((d) => d.analytics).catch(() => null),
    ]);
  } catch (_) {}
  clear(root);

  const takeBtn = el("button", { class: "ex-btn ex-btn-primary" }, "Take a Test →");
  takeBtn.addEventListener("click", () => navigate("/exams"));
  root.appendChild(el("div", { class: "dash-head" }, [
    el("div", {}, [el("h2", {}, "Student Dashboard"), el("p", { class: "ex-muted" }, `Welcome, ${user.name || "Student"}`)]),
    takeBtn,
  ]));

  const avg = analytics ? analytics.avg_percentage : 0;
  const best = analytics ? analytics.best_percentage : 0;
  root.appendChild(el("div", { class: "dash-cards" }, [
    statCard("📝", "TESTS AVAILABLE", exams.length, "blue", "hosted now"),
    statCard("✅", "TESTS TAKEN", attempts.length, "green", "your attempts"),
    statCard("📊", "AVERAGE", `${avg}%`, "pink", "across attempts"),
    statCard("🏆", "BEST", `${best}%`, "amber", "personal best"),
  ]));

  root.appendChild(el("h3", { class: "ex-section-title" }, "Available tests"));
  if (!exams.length) root.appendChild(el("div", { class: "ex-empty-card" }, "No tests hosted right now."));
  else {
    const grid = el("div", { class: "ex-card-grid" });
    exams.slice(0, 6).forEach((ex) => {
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
        el("div", { class: "ex-card-meta" }, [el("span", {}, `${ex.total_questions} questions`), el("span", {}, `${ex.duration_min} min`)]),
        action,
      ]));
    });
    root.appendChild(grid);
  }

  root.appendChild(el("h3", { class: "ex-section-title" }, "Recent results"));
  if (!attempts.length) root.appendChild(el("div", { class: "ex-empty-card" }, "You haven't taken any tests yet."));
  else {
    const list = el("div", { class: "ex-result-list" });
    attempts.slice(0, 5).forEach((a) => {
      const open = el("button", { class: "ex-link" }, "View report");
      open.addEventListener("click", () => navigate("/exams/result/" + a.id));
      list.appendChild(el("div", { class: "ex-result-row" }, [
        el("div", {}, [el("strong", {}, a.exam_title), el("div", { class: "ex-muted" }, fmtDate(a.submitted_at))]),
        el("div", { class: "ex-result-score" }, `${a.score}/${a.max_marks} · ${a.percentage}%`),
        open,
      ]));
    });
    root.appendChild(list);
  }

  root.appendChild(el("h3", { class: "ex-section-title" }, "Quick actions"));
  root.appendChild(el("div", { class: "dash-quick" }, [
    quick("Take a Test", "Attempt a hosted test", "/exams", navigate),
    quick("My Reports", "Your overall performance", "/reports", navigate),
  ]));
}
