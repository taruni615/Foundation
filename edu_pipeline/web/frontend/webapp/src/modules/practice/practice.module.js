// Practice Engine routes (PRD Phase 1 MVP).
//   /practice                 mode picker + recent sessions
//   /practice/run/:id         the runner
//   /practice/report/:id      result analysis
//
// Student-only: teachers author exams through the existing Online Exams module.

import { renderPracticeHome } from "./views/practice-home.view.js";
import { createPracticeRunner } from "./views/practice-runner.view.js";
import { renderPracticeReport } from "./views/practice-report.view.js";

export function createPracticeModules({ store }) {
  let runner = null;
  let node = null;
  function killRunner() {
    if (runner) { try { runner.destroy(); } catch (_) {} runner = null; }
  }

  const home = {
    id: "practice",
    pattern: "/practice",
    label: "Practice",
    navSection: "Academics",
    navIcon: "🎯",
    navOrder: 2,
    roles: ["student"],
    mount(n, ctx) { renderPracticeHome(n, { store, navigate: ctx.navigate }); },
  };

  const run = {
    id: "practice-run",
    pattern: "/practice/run/:id",
    label: "Practice",
    navGroup: "Practice",
    navHidden: true,
    mount(n, ctx) {
      node = n;
      killRunner();
      runner = createPracticeRunner(n, { sessionId: ctx.params.id, navigate: ctx.navigate });
    },
    update(ctx) {
      killRunner();
      runner = createPracticeRunner(node, { sessionId: ctx.params.id, navigate: ctx.navigate });
    },
    unmount() { killRunner(); },
  };

  const report = {
    id: "practice-report",
    pattern: "/practice/report/:id",
    label: "Practice results",
    navGroup: "Practice",
    navHidden: true,
    mount(n, ctx) {
      node = n;
      renderPracticeReport(n, { sessionId: ctx.params.id, navigate: ctx.navigate });
    },
    update(ctx) {
      renderPracticeReport(node, { sessionId: ctx.params.id, navigate: ctx.navigate });
    },
  };

  return [home, run, report];
}

export function registerPractice(registry, deps) {
  createPracticeModules(deps).forEach((m) => registry.register(m));
}
