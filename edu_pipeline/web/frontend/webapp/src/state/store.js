// Tiny namespaced pub/sub store (Phase 0 runtime, T0-A).
//
// Replaces the legacy single global `state` object with isolated slices, so the
// extraction, bank, and shell modules can own their own state without stepping
// on each other.  No framework, no DOM.
//
// Contract:
//   getState(slice)        -> the slice's current state (or whole state if omitted)
//   setState(slice, patch) -> shallow-merge patch into slice, notify subscribers
//   subscribe(slice, fn)   -> fn(next, prev) on changes to THAT slice; returns an
//                             unsubscribe function

export function createStore(initial = {}) {
  const state = { ...initial };
  const subs = new Map(); // slice -> Set<fn>

  function getState(slice) {
    return slice == null ? state : state[slice];
  }

  function setState(slice, patch) {
    const prev = state[slice];
    let next;
    if (patch && typeof patch === "object" && !Array.isArray(patch)) {
      next = { ...(prev || {}), ...patch };
    } else {
      next = patch; // allow non-object slice values too
    }
    state[slice] = next;
    const set = subs.get(slice);
    if (set) {
      for (const fn of [...set]) fn(next, prev);
    }
    return next;
  }

  function subscribe(slice, fn) {
    if (typeof fn !== "function") {
      throw new TypeError("subscribe(slice, fn): fn must be a function");
    }
    let set = subs.get(slice);
    if (!set) {
      set = new Set();
      subs.set(slice, set);
    }
    set.add(fn);
    return () => {
      const s = subs.get(slice);
      if (s) s.delete(fn);
    };
  }

  return { getState, setState, subscribe };
}

// Shared singleton for the live runtime (tests use createStore() for isolation).
export const store = createStore();
