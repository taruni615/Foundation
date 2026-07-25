// Application shell (Phase 0, T0-B).  Minimal by design: side navigation +
// content region only.  No top bar, command palette, notifications, or user
// menu (explicitly out of scope).
//
// The content region contains one root per module.  Modules with a static root
// (`#<id>-root`, e.g. the legacy wizard's `#extraction-root`) are shown/hidden
// in place -- never re-rendered, so app.js keeps its element bindings.  Modules
// without a static root render into the shared dynamic node `#module-content`,
// which is the content region future modules (T4+) mount into.
//
// Visibility is driven by the `shell` store slice (set by the router on every
// route change), so exactly the active module's view is shown.

import { renderSidenav } from "./sidenav.js";
import { createTopbar } from "./topbar.js";

export function createShell({ root, registry, store, win = globalThis }) {
  const doc = (root && root.ownerDocument) || win.document;

  const nav = doc.getElementById("app-nav");
  renderSidenav({ nav, registry, store });

  // Global top bar pinned above the content region.
  const appContent = doc.getElementById("app-content");
  if (appContent && !appContent.querySelector(".app-topbar")) {
    const topbar = createTopbar({ store, doc });
    appContent.insertBefore(topbar, appContent.firstChild);
  }

  // The dynamic mount point for modules that have no static root.
  const content = doc.getElementById("module-content");

  function updateVisibility(activeId) {
    let activeHasStaticRoot = false;
    for (const m of registry.list()) {
      const el = doc.getElementById(m.id + "-root");
      if (!el) continue;
      const show = m.id === activeId;
      el.hidden = !show;
      if (show) activeHasStaticRoot = true;
    }
    // Dynamic content is visible only when the active module has no static root.
    if (content) content.hidden = activeHasStaticRoot;
  }

  store.subscribe("shell", (s) => updateVisibility(s && s.module));

  return { content, nav, updateVisibility };
}
