// Question Bank state slice (T3).
//
// Owns the shape of the bank's screen state and the pure functions that map
// between the URL query and that state.  The URL is the source of truth: the
// module rehydrates the slice from the URL on every route event (queryFromUrl),
// and serializes state back to the URL when navigating (urlFromQuery).
//
// Only the *query* portion (filters/q/sort/page/pageSize) lives in the URL.
// Transient state (results/facets/loading/error/selection) does not.

export const BANK_SLICE = "bank";

// Multi-value (OR-within-group) filter dimensions.  Serialized comma-joined,
// matching the T1/T2 backend contract.
export const MULTI_KEYS = ["subject", "class", "board", "type", "book", "chapter"];

export const DEFAULT_PAGE = 1;
export const DEFAULT_PAGE_SIZE = 25;
export const PAGE_SIZES = [25, 50, 100];

function splitMulti(v) {
  if (v == null) return [];
  const raw = Array.isArray(v) ? v : [v];
  return raw
    .flatMap((x) => String(x).split(","))
    .map((s) => s.trim())
    .filter((s) => s !== "");
}

function toInt(v, d) {
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : d;
}

export function emptyFilters() {
  const f = {};
  for (const k of MULTI_KEYS) f[k] = [];
  return f;
}

export function initialBankState() {
  return {
    filters: emptyFilters(),
    q: "",
    sort: "",
    page: DEFAULT_PAGE,
    pageSize: DEFAULT_PAGE_SIZE,
    // transient (not URL-backed)
    results: [],
    facets: {},
    total: 0,
    // derived pagination snapshot (read-model; page/pageSize above stay
    // authoritative + URL-driven). Populated on each successful load.
    pagination: { page: DEFAULT_PAGE, pageSize: DEFAULT_PAGE_SIZE, total: 0, totalPages: 0 },
    loading: "idle", // idle | loading | done | error
    error: null,
    selectedItemId: null,
    selectedItem: null,
    lastFetchedAt: null,
  };
}

// URL query (strings, as parsed by the router) -> normalized query state.
export function queryFromUrl(query = {}) {
  const filters = emptyFilters();
  for (const k of MULTI_KEYS) filters[k] = splitMulti(query[k]);
  // chapter values are numeric ids
  filters.chapter = filters.chapter.filter((x) => /^\d+$/.test(x));

  const page = Math.max(1, toInt(query.page, DEFAULT_PAGE));
  let pageSize = toInt(query.pageSize, DEFAULT_PAGE_SIZE);
  if (!PAGE_SIZES.includes(pageSize)) pageSize = DEFAULT_PAGE_SIZE;

  return {
    filters,
    q: String(query.q || "").trim(),
    sort: String(query.sort || "").trim(),
    page,
    pageSize,
  };
}

// Query state -> minimal URL object for router.buildHash (drops defaults and
// empties; arrays are left for the router/client to comma-join).
export function urlFromQuery(state = {}) {
  const out = {};
  const f = state.filters || {};
  for (const k of MULTI_KEYS) {
    const arr = (f[k] || []).filter(Boolean);
    if (arr.length) out[k] = arr;
  }
  if (state.q) out.q = state.q;
  if (state.sort) out.sort = state.sort;
  if (state.page && state.page !== DEFAULT_PAGE) out.page = state.page;
  if (state.pageSize && state.pageSize !== DEFAULT_PAGE_SIZE) out.pageSize = state.pageSize;
  return out;
}

// Query state -> params for bank.api.searchItems (always includes page/pageSize;
// filters flattened to top-level arrays).
export function apiParamsFromQuery(state = {}) {
  const f = state.filters || {};
  const out = {
    q: state.q || "",
    sort: state.sort || "",
    page: state.page || DEFAULT_PAGE,
    pageSize: state.pageSize || DEFAULT_PAGE_SIZE,
  };
  for (const k of MULTI_KEYS) out[k] = (f[k] || []).filter(Boolean);
  return out;
}
