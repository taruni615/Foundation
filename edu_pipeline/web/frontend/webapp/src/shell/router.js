// Hash router (Phase 0 runtime, T0-A).
//
// Parses `#/path?query`, resolves the owning module via the registry, and drives
// the mount/unmount lifecycle.  The query is the source of truth for screen
// state (T3): `buildHash` serializes it (arrays comma-joined to match the T1/T2
// backend contract), `parseHash` rehydrates it.
//
// Lifecycle rule: navigating to a DIFFERENT module unmounts the old one and
// mounts the new one; navigating within the SAME module (e.g. a query change on
// /bank/search) calls the module's optional update(ctx) instead of remounting --
// so a module mounts once and reacts to query changes via its slice.

// --- pure helpers (exported for reuse + tests) ---------------------------
export function parseHash(raw) {
  let h = String(raw || "");
  if (h.startsWith("#")) h = h.slice(1);
  const qi = h.indexOf("?");
  let path = qi >= 0 ? h.slice(0, qi) : h;
  const qs = qi >= 0 ? h.slice(qi + 1) : "";
  if (!path) path = "/";
  if (!path.startsWith("/")) path = "/" + path;
  const query = {};
  if (qs) {
    for (const [k, v] of new URLSearchParams(qs)) query[k] = v;
  }
  return { path, query };
}

export function buildHash(path, query) {
  const p = String(path).startsWith("/") ? path : "/" + path;
  const usp = new URLSearchParams();
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v == null) continue;
      if (Array.isArray(v)) {
        const parts = v.map((x) => String(x).trim()).filter((x) => x !== "");
        if (parts.length) usp.set(k, parts.join(","));
      } else {
        const s = String(v).trim();
        if (s !== "") usp.set(k, s);
      }
    }
  }
  const tail = usp.toString();
  return "#" + p + (tail ? "?" + tail : "");
}

// --- controller ----------------------------------------------------------
export function createRouter({
  registry,
  content = null,
  win = globalThis,
  fallback = "/",
  onRoute = () => {},
} = {}) {
  if (!registry) throw new TypeError("createRouter: registry is required");

  let activeEntry = null;
  let lastHash = null;

  function apply() {
    const raw = (win.location && win.location.hash) || "";
    if (raw === lastHash) return; // de-dupe navigate()+hashchange double-fire
    lastHash = raw;

    const { path, query } = parseHash(raw);
    let m = registry.match(path);
    if (!m) {
      if (path !== fallback) {
        navigate(fallback); // redirect unknown -> fallback
        return;
      }
      m = registry.match(fallback);
    }
    if (!m) {
      onRoute({ path, query, params: {}, module: null, changedModule: false });
      return;
    }

    const ctx = { path, query, params: m.params, navigate };
    const changedModule = activeEntry !== m.entry;
    if (changedModule) {
      if (activeEntry && typeof activeEntry.unmount === "function") {
        try { activeEntry.unmount(); } catch (_) { /* isolate module errors */ }
      }
      activeEntry = m.entry;
      m.entry.mount(content, ctx);
    } else if (typeof m.entry.update === "function") {
      m.entry.update(ctx);
    }
    onRoute({ path, query, params: m.params, module: m.entry.id, changedModule });
  }

  function navigate(path, query) {
    const hash = buildHash(path, query);
    if (win.location) win.location.hash = hash;
    apply(); // explicit, so it works even when location.hash assignment is silent
  }

  function start() {
    if (win.addEventListener) win.addEventListener("hashchange", apply);
    apply();
  }

  function stop() {
    if (win.removeEventListener) win.removeEventListener("hashchange", apply);
  }

  return {
    start,
    stop,
    navigate,
    parseHash,
    buildHash,
    current: () => ({ module: activeEntry ? activeEntry.id : null, hash: lastHash }),
  };
}
