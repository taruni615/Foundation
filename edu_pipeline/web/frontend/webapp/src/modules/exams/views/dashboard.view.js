// Dashboard — role-aware: students get a student dashboard, teachers/admins get
// the management dashboard.
import { el, clear } from "../../../ui/el.js";
import * as assess from "../../../api/assess.api.js";
import * as practice from "../../../api/practice.api.js";

// ---- PRD dashboard widgets -------------------------------------------------
// Each builder takes the widget payload and returns a card, or null when the
// widget says it has nothing to show.

function widgetShell(title, icon, body, extraClass) {
  return el("div", { class: "dash-widget " + (extraClass || "") }, [
    el("div", { class: "dash-widget-head" }, [
      el("span", { class: "dash-widget-icon" }, icon),
      el("strong", {}, title),
    ]),
    body,
  ]);
}

function unavailable(title, icon, message) {
  return widgetShell(title, icon, el("div", { class: "ex-muted" }, message), "dash-widget-muted");
}

function dailyGoalCard(g, summary) {
  if (!g || !g.ok) return unavailable("Daily Goal", "🎯", "Goal tracking is unavailable.");
  const bar = el("div", { class: "pr-progress" },
    el("div", { class: "pr-progress-fill", style: `width:${g.pct}%` }));
  return widgetShell("Daily Goal", "🎯", el("div", {}, [
    el("div", { class: "dash-value" }, `${g.done} / ${g.goal}`),
    el("div", { class: "dash-sub" }, g.met ? "Goal met — well done." : `${g.remaining} questions to go`),
    bar,
    el("div", { class: "dash-sub" },
      `🔥 ${g.streak}-day streak${g.best_streak > g.streak ? ` · best ${g.best_streak}` : ""}` +
      (summary.accuracy ? ` · ${summary.accuracy}% overall accuracy` : "")),
  ]));
}

function continueLearningCard(c, navigate) {
  // The PRD hides this widget once the chapter is complete.
  if (!c || !c.ok || !c.show) return null;
  const btn = el("button", { class: "ex-btn ex-btn-primary" }, "Resume →");
  btn.addEventListener("click", () => navigate("/practice"));
  return widgetShell("Continue Learning", "📖", el("div", {}, [
    el("div", { class: "dash-value dash-value-sm" }, c.chapter_name || "Last chapter"),
    el("div", { class: "dash-sub" }, `${c.pct}% covered · ${c.accuracy}% accuracy`),
    el("div", { class: "pr-progress" },
      el("div", { class: "pr-progress-fill", style: `width:${c.pct}%` })),
    btn,
  ]));
}

function dailyChallengeCard(d, navigate) {
  if (!d || !d.ok) return unavailable("Daily Challenge", "⭐", "Challenge unavailable.");
  const body = el("div", {});
  if (d.status === "completed") {
    body.appendChild(el("div", { class: "dash-value" }, `${d.score}/${d.size}`));
    body.appendChild(el("div", { class: "dash-sub" }, "Done for today — back tomorrow."));
  } else {
    body.appendChild(el("div", { class: "dash-sub" },
      `${d.size} questions · resets daily`));
    const btn = el("button", { class: "ex-btn ex-btn-primary" },
      d.status === "in_progress" ? "Continue challenge →" : "Start challenge →");
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const r = await practice.startDailyChallenge();
        navigate("/practice/run/" + r.session.id);
      } catch (e) {
        btn.disabled = false;
        body.appendChild(el("div", { class: "ex-error" }, e.message || "Could not start."));
      }
    });
    body.appendChild(btn);
  }
  return widgetShell("Daily Challenge", "⭐", body);
}

function recommendationCard(r, navigate) {
  if (!r || !r.ok) return unavailable("AI Recommendation", "🧠", "No recommendation yet.");
  const btn = el("button", { class: "ex-btn" }, "Do this →");
  btn.addEventListener("click", () => navigate("/practice"));
  return widgetShell("AI Recommendation", "🧠", el("div", {}, [
    el("div", { class: "dash-value dash-value-sm" }, r.title),
    el("div", { class: "dash-sub" }, r.why),
    btn,
  ]));
}

function weeklyProgressCard(p) {
  if (!p || !p.ok) return unavailable("Weekly Progress", "📈", "Trend unavailable.");
  const peak = Math.max(1, ...p.series.map((d) => d.answered));
  const chart = el("div", { class: "dash-spark" });
  p.series.forEach((d) => {
    const h = Math.round(100 * d.answered / peak);
    chart.appendChild(el("div", { class: "dash-spark-col", title: `${d.day}: ${d.answered} answered` }, [
      el("div", { class: "dash-spark-bar", style: `height:${Math.max(4, h)}%` }),
      el("span", { class: "dash-spark-day" }, d.day.slice(8)),
    ]));
  });
  return widgetShell("Weekly Progress", "📈", el("div", {}, [
    el("div", { class: "dash-value" }, `${p.total_answered}`),
    el("div", { class: "dash-sub" },
      `questions this week · ${p.accuracy}% accuracy · ${p.active_days}/7 active days`),
    chart,
  ]));
}

function savedContentCard(s) {
  if (!s || !s.ok) return null;
  if (!s.available) {
    return unavailable("Saved Content", "🔖",
      s.note || "Snippets and bookmarks arrive with the Learn Module.");
  }
  return widgetShell("Saved Content", "🔖", el("div", {}, [
    el("div", { class: "dash-value" }, String(s.items.length)),
    el("div", { class: "dash-sub" },
      `${s.counts.snippets} snippets · ${s.counts.bookmarks} bookmarks`),
  ]));
}

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

// ---- Student dashboard (the PRD command centre) ----
// Every widget is fetched with its own catch and rendered from its own `ok`
// flag, so one unavailable source degrades a single card instead of blanking
// the page — the PRD's "widgets should load independently" note.
async function renderStudent(root, user, navigate) {
  let dash = null, exams = [], attempts = [];
  [dash, exams, attempts] = await Promise.all([
    practice.dashboard().catch(() => null),
    assess.listExams().then((d) => d.exams || []).catch(() => []),
    assess.listAttempts().then((d) => d.attempts || []).catch(() => []),
  ]);
  clear(root);

  const w = (dash && dash.widgets) || {};
  const sum = (dash && dash.summary) || {};

  const practiseBtn = el("button", { class: "ex-btn ex-btn-primary" }, "Practise now →");
  practiseBtn.addEventListener("click", () => navigate("/practice"));
  root.appendChild(el("div", { class: "dash-head" }, [
    el("div", {}, [
      el("h2", {}, `Welcome back, ${user.name || "Student"}`),
      el("p", { class: "ex-muted" }, "Here is what to focus on today."),
    ]),
    practiseBtn,
  ]));

  if (!dash) {
    root.appendChild(el("div", { class: "ex-error" },
      "Your learning widgets are unavailable right now. Tests are still listed below."));
  }

  root.appendChild(el("div", { class: "dash-widgets" }, [
    dailyGoalCard(w.daily_goal, sum),
    continueLearningCard(w.continue_learning, navigate),
    dailyChallengeCard(w.daily_challenge, navigate),
    recommendationCard(w.ai_recommendation, navigate),
    weeklyProgressCard(w.weekly_progress),
    savedContentCard(w.saved_content),
  ].filter(Boolean)));

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
