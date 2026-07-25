// Online Exams — student routes (Slice 1).
// Routes: /login, /exams (list), /exams/take/:id (runner), /exams/result/:id.
// Auth-gated: views redirect to /login when no token is present.

import { renderLogin } from "./views/login.view.js";
import { renderExamList } from "./views/exam-list.view.js";
import { createRunner } from "./views/runner.view.js";
import { renderResult } from "./views/result.view.js";
import { renderAnalytics } from "./views/analytics.view.js";
import { renderCreate } from "./views/create.view.js";
import { renderManage } from "./views/manage.view.js";
import { renderTeacherReports, renderTeacherReport } from "./views/teacher-report.view.js";
import { renderDashboard } from "./views/dashboard.view.js";

export function createExamModules({ store }) {
  let runner = null;
  let node = null; // captured at mount (router passes content on mount, not update)
  function killRunner() { if (runner) { try { runner.destroy(); } catch (_) {} runner = null; } }

  const dashboard = {
    id: "dashboard", pattern: "/dashboard", label: "Dashboard", navSection: "Menu", navIcon: "📊", navOrder: 0,
    mount(n, ctx) { renderDashboard(n, { store, navigate: ctx.navigate }); },
  };

  const login = {
    id: "login", pattern: "/login", label: "Sign in", navGroup: "Online Exams", navHidden: true,
    mount(n, ctx) { renderLogin(n, { store, navigate: ctx.navigate, next: ctx.query.next }); },
  };

  const list = {
    id: "exams", pattern: "/exams", label: "Take Test", navSection: "Academics", navParent: "Online Exams", navIcon: "📝", navOrder: 4, roles: ["student"],
    mount(n, ctx) { renderExamList(n, { store, navigate: ctx.navigate }); },
  };

  const runnerMod = {
    id: "exam-runner", pattern: "/exams/take/:id", label: "Take Test", navGroup: "Online Exams", navHidden: true,
    mount(n, ctx) { node = n; killRunner(); runner = createRunner(n, { examId: ctx.params.id, navigate: ctx.navigate }); },
    update(ctx) { killRunner(); runner = createRunner(node, { examId: ctx.params.id, navigate: ctx.navigate }); },
    unmount() { killRunner(); },
  };

  const result = {
    id: "exam-result", pattern: "/exams/result/:id", label: "Result", navGroup: "Online Exams", navHidden: true,
    mount(n, ctx) { node = n; renderResult(n, { navigate: ctx.navigate, attemptId: ctx.params.id }); },
    update(ctx) { renderResult(node, { navigate: ctx.navigate, attemptId: ctx.params.id }); },
  };

  const reports = {
    id: "exam-reports", pattern: "/reports", label: "My Reports", navSection: "Academics", navParent: "Online Exams", navIcon: "📈", navOrder: 5, roles: ["student"],
    mount(n, ctx) { renderAnalytics(n, { store, navigate: ctx.navigate }); },
  };

  const create = {
    id: "exam-create", pattern: "/exams/create", label: "Create Exam", navSection: "Academics", navParent: "Online Exams", navIcon: "✏️", navOrder: 1, roles: ["teacher"],
    mount(n, ctx) { renderCreate(n, { store, navigate: ctx.navigate }); },
  };

  const manage = {
    id: "exam-manage", pattern: "/exams/manage", label: "Manage Exams", navSection: "Academics", navParent: "Online Exams", navIcon: "🗂", navOrder: 2, roles: ["teacher"],
    mount(n, ctx) { renderManage(n, { store, navigate: ctx.navigate }); },
  };

  const treports = {
    id: "exam-treports", pattern: "/exams/reports", label: "Test Reports", navSection: "Academics", navParent: "Online Exams", navIcon: "📊", navOrder: 3, roles: ["teacher"],
    mount(n, ctx) { renderTeacherReports(n, { store, navigate: ctx.navigate }); },
  };

  const treport = {
    id: "exam-treport", pattern: "/exams/reports/:id", label: "Test Report", navGroup: "Online Exams", navHidden: true,
    mount(n, ctx) { node = n; renderTeacherReport(n, { store, navigate: ctx.navigate, examId: ctx.params.id }); },
    update(ctx) { renderTeacherReport(node, { store, navigate: ctx.navigate, examId: ctx.params.id }); },
  };

  return [dashboard, login, list, runnerMod, result, reports, create, manage, treports, treport];
}

export function registerExams(registry, deps) {
  createExamModules(deps).forEach((m) => registry.register(m));
}
