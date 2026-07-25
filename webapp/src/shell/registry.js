// Module + route registry (Phase 0 runtime, T0-A).
//
// Each module declares which route it owns plus its lifecycle hooks.  The router
// consults the registry to decide which module owns an incoming path.  Patterns
// support `:param` segments (e.g. "/bank/item/:id") so the same registry serves
// T3's dynamic detail route.
//
// A module entry:
//   { id, pattern, label?, navGroup?, mount(content, ctx), unmount?(), update?(ctx) }

function compilePattern(pattern) {
  const keys = [];
  const body = String(pattern).replace(/:[^/]+/g, (seg) => {
    keys.push(seg.slice(1));
    return "([^/]+)";
  });
  return { keys, regex: new RegExp("^" + body + "$") };
}

export function createRegistry() {
  const entries = [];

  function register(mod) {
    if (!mod || !mod.id || !mod.pattern || typeof mod.mount !== "function") {
      throw new TypeError("register(mod): id, pattern and mount() are required");
    }
    if (entries.some((e) => e.id === mod.id)) {
      throw new Error(`Module already registered: ${mod.id}`);
    }
    const { keys, regex } = compilePattern(mod.pattern);
    entries.push({ ...mod, _keys: keys, _regex: regex });
    return mod;
  }

  // Resolve a path to its owning module + extracted params, or null.
  function match(path) {
    for (const e of entries) {
      const m = e._regex.exec(path);
      if (m) {
        const params = {};
        e._keys.forEach((k, i) => {
          params[k] = decodeURIComponent(m[i + 1]);
        });
        return { entry: e, params };
      }
    }
    return null;
  }

  function list() {
    return entries.slice();
  }

  return { register, match, list };
}
