// Runtime bootstrap (Phase 0 runtime, T0-A).
//
// Wires the store + registry + router together and registers the two Phase-1
// modules: the existing extraction wizard and a placeholder Question Bank
// module (real UI arrives in T4+).
//
// IMPORTANT (T0-A scope): this file is NOT yet referenced by index.html.  There
// is no app-shell / content region yet (that is T0-B), so boot() only runs when
// a `#app-content` mount point exists in the document.  Until then the runtime
// is dormant and the legacy wizard (loaded directly by index.html) is untouched.

import { createStore, store as sharedStore } from "./state/store.js";
import { createRegistry } from "./shell/registry.js";
import { createRouter } from "./shell/router.js";
import { registerExams } from "./modules/exams/exams.module.js";

// The extraction module wraps the legacy wizard.  In T0-A there is no wizard
// root inside a shell, so mount/unmount only toggle a `#extraction-root`
// element IF present (forward-compatible no-op today).  The real wizard init()
// hand-off happens in the T0-B migration.
function makeExtractionModule(win) {
  function rootEl() {
    return win.document ? win.document.getElementById("extraction-root") : null;
  }
  return {
    id: "extraction",
    pattern: "/content/extract",
    label: "Extraction",
    navSection: "Content",
    navIcon: "📄",
    navOrder: 1,
    roles: ["teacher"],
    mount() {
      const r = rootEl();
      if (r) r.hidden = false;
    },
    unmount() {
      const r = rootEl();
      if (r) r.hidden = true;
    },
  };
}

export function boot({
  root,
  content = null,
  createShell,
  win = globalThis,
  store = createStore(),
  registry = createRegistry(),
  fallback = "/dashboard",
} = {}) {
  registry.register(makeExtractionModule(win));
  // Online Exams (student + teacher): dashboard, exams, reports, creation.
  registerExams(registry, { store });

  // When a shell root + factory are provided, build the shell (sidenav +
  // content region) and let it own the dynamic mount node.  Otherwise use the
  // `content` passed directly (headless / tests).
  if (!content && root && typeof createShell === "function") {
    content = createShell({ root, registry, store, win }).content;
  }

  const router = createRouter({
    registry,
    content,
    win,
    fallback,
    onRoute: (r) => store.setState("shell", { path: r.path, query: r.query, module: r.module }),
  });
  router.start();

  return { store, registry, router };
}

// Auto-boot when the shell root exists in the page (T0-B migration).
if (typeof document !== "undefined") {
  const root = document.getElementById("app");
  if (root) {
    import("./shell/app-shell.js").then(({ createShell }) => {
      boot({ root, store: sharedStore, createShell });
    });
  }
}
