// Question Bank module (T3 wiring + T4 Browse UI).
//
// Registers both bank routes and keeps the URL as the source of truth for the
// bank slice.  The search route now renders the real Browse view (SearchBar +
// table + count + pagination + loading/error/empty); the detail route is still
// a temporary debug stub (its real screen is a later task).
//
// Unidirectional flow:
//   URL (router) --mount/update--> queryFromUrl --> store.setState(bank) --> view.render
//   UI intent --handlers--> applyQuery --> router.navigate(URL)  (then the loop above)

import {
  BANK_SLICE,
  initialBankState,
  emptyFilters,
  queryFromUrl,
  urlFromQuery,
  apiParamsFromQuery,
  DEFAULT_PAGE,
  DEFAULT_PAGE_SIZE,
} from "../../state/slices/bank.slice.js";
import { createBrowseView } from "./browse.js";
import { createDetailView } from "./detail.js";

export function createBankModules({ store, api } = {}) {
  if (store.getState(BANK_SLICE) == null) {
    store.setState(BANK_SLICE, initialBankState());
  }

  let navigate = null;
  let reqId = 0;
  let view = null;
  let unsubscribe = null;

  function syncFromUrl(ctx) {
    navigate = ctx.navigate;
    store.setState(BANK_SLICE, queryFromUrl(ctx.query)); // URL -> State
  }

  async function loadResults() {
    if (!api || typeof api.searchItems !== "function") return;
    const myReq = ++reqId;
    store.setState(BANK_SLICE, { loading: "loading", error: null });
    const s = store.getState(BANK_SLICE);
    try {
      const data = await api.searchItems(apiParamsFromQuery(s));
      if (myReq !== reqId) return; // superseded by a newer request
      const total = data.total || 0;
      const pageSize = s.pageSize || DEFAULT_PAGE_SIZE;
      store.setState(BANK_SLICE, {
        results: data.items || [],
        facets: data.facets || {},
        total,
        pagination: {
          page: s.page,
          pageSize,
          total,
          totalPages: Math.max(1, Math.ceil(total / pageSize)),
        },
        loading: "done",
        lastFetchedAt: Date.now(),
      });
    } catch (e) {
      if (myReq !== reqId) return;
      store.setState(BANK_SLICE, {
        loading: "error",
        error: { message: e.message, status: e.status, retryable: e.retryable },
      });
    }
  }

  // UI intents always route THROUGH the URL so the slice is never written
  // out-of-band.
  function applyQuery(patch = {}) {
    const s = store.getState(BANK_SLICE);
    const next = {
      filters: { ...s.filters, ...(patch.filters || {}) },
      q: patch.q !== undefined ? patch.q : s.q,
      sort: patch.sort !== undefined ? patch.sort : s.sort,
      page: patch.page !== undefined ? patch.page : s.page,
      pageSize: patch.pageSize !== undefined ? patch.pageSize : s.pageSize,
    };
    if (navigate) navigate("/bank/search", urlFromQuery(next));
  }

  // --- filter intents (T5). All derive from the slice and route through the URL. ---
  function currentFilter(dim) {
    return ((store.getState(BANK_SLICE).filters || {})[dim] || []).map(String);
  }
  // Changing Book invalidates Chapter (chapter ids belong to a book), so a book
  // change always resets the chapter selection.
  function filterPatch(dim, nextValues) {
    const patch = { [dim]: nextValues };
    if (dim === "book") patch.chapter = [];
    return patch;
  }
  function toggleFacet(dim, value) {
    const cur = currentFilter(dim);
    const v = String(value);
    const next = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v];
    applyQuery({ filters: filterPatch(dim, next), page: DEFAULT_PAGE });
  }
  function removeFilter(dim, value) {
    const v = String(value);
    applyQuery({ filters: filterPatch(dim, currentFilter(dim).filter((x) => x !== v)), page: DEFAULT_PAGE });
  }
  function clearGroup(dim) {
    applyQuery({ filters: filterPatch(dim, []), page: DEFAULT_PAGE });
  }
  // Clear All: drops every filter + the query, but preserves sort + pageSize.
  function clearAll() {
    applyQuery({ filters: emptyFilters(), q: "", page: DEFAULT_PAGE });
  }

  const handlers = {
    onSearch: (q) => applyQuery({ q, page: DEFAULT_PAGE }),
    onPage: (p) => applyQuery({ page: p }),
    onPageSize: (n) => applyQuery({ pageSize: n, page: DEFAULT_PAGE }),
    onRetry: () => loadResults(),
    onToggleFacet: toggleFacet,
    onRemoveFilter: removeFilter,
    onClearGroup: clearGroup,
    onRemoveQuery: () => applyQuery({ q: "", page: DEFAULT_PAGE }),
    onClearAll: clearAll,
  };

  const search = {
    id: "bank",
    pattern: "/bank/search",
    label: "Question Bank",
    navSection: "Content",
    navIcon: "📚",
    navOrder: 2,
    mount(node, ctx) {
      syncFromUrl(ctx);
      view = createBrowseView({ node, handlers });
      unsubscribe = store.subscribe(BANK_SLICE, (s) => view && view.render(s));
      view.render(store.getState(BANK_SLICE));
      loadResults();
    },
    update(ctx) {
      syncFromUrl(ctx); // setState triggers the subscription -> view.render
      loadResults();
    },
    unmount() {
      if (unsubscribe) unsubscribe();
      unsubscribe = null;
      if (view) view.destroy();
      view = null;
    },
  };

  // --- Item Detail (T6, read-only) ---
  let detailView = null;
  let detailReq = 0;

  function backToResults() {
    if (navigate) navigate("/bank/search", urlFromQuery(store.getState(BANK_SLICE)));
  }

  function loadDetail(id) {
    const myReq = ++detailReq;
    store.setState(BANK_SLICE, { selectedItemId: id, selectedItem: null, error: null });
    if (detailView) detailView.render({ status: "loading", id });
    if (!api || typeof api.getItem !== "function") {
      if (detailView) detailView.render({ status: "error", id, error: { message: "Bank API unavailable" } });
      return;
    }
    api
      .getItem(id)
      .then((d) => {
        if (myReq !== detailReq) return;
        const item = d.item || null;
        store.setState(BANK_SLICE, { selectedItem: item });
        if (detailView) detailView.render({ status: "success", id, item });
      })
      .catch((e) => {
        if (myReq !== detailReq) return;
        store.setState(BANK_SLICE, {
          selectedItem: null,
          error: { message: e.message, status: e.status, notFound: e.notFound },
        });
        if (!detailView) return;
        const notFound = e.notFound || e.status === 404;
        detailView.render(notFound ? { status: "notfound", id } : { status: "error", id, error: e });
      });
  }

  const detail = {
    id: "bank-item",
    pattern: "/bank/item/:id",
    label: "Question Detail",
    navGroup: "Bank",
    navHidden: true,
    mount(node, ctx) {
      navigate = ctx.navigate;
      detailView = createDetailView({
        node,
        onBack: backToResults,
        onRetry: () => loadDetail(ctx.params.id),
      });
      loadDetail(ctx.params.id);
    },
    update(ctx) {
      navigate = ctx.navigate;
      loadDetail(ctx.params.id); // navigating between item ids re-fetches
    },
    unmount() {
      if (detailView) detailView.destroy();
      detailView = null;
    },
  };

  return { modules: [search, detail], applyQuery };
}

// Centralized route registration for the bank domain.
export function registerBank(registry, deps) {
  const { modules, applyQuery } = createBankModules(deps);
  modules.forEach((m) => registry.register(m));
  return { applyQuery };
}
