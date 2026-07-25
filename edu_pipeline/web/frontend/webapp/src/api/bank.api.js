// Read-only Question Bank API (Phase 1).
//
// Thin, typed wrappers over the /api/bank/* endpoints added in T1.  All return
// parsed data or throw an `ApiError` (see ./client.js).  `filters` accepts the
// bank slice's filter shape directly: arrays (subject/class/board/type/book/
// chapter) plus scalars (q/sort/page/pageSize); `buildQuery` handles both.

import { get } from "./client.js";

// -> { items, total, page, pageSize, sort, facets }
export function searchItems(filters = {}, opts = {}) {
  return get("/api/bank/items", filters, opts);
}

// -> { subject, class, board, type, book, chapter }
export function getFacets(filters = {}, opts = {}) {
  return get("/api/bank/facets", filters, opts);
}

// -> { item, chapter, source }.  Missing id throws ApiError with
// .status === 404 and .notFound === true.
export function getItem(id, opts = {}) {
  return get(`/api/bank/items/${encodeURIComponent(id)}`, undefined, opts);
}

// -> { db_ok, total_items } (or { db_ok:false, error }).  Resolves even when the
// database is down -- the server returns 200 -- so the UI can show a distinct
// "bank unreachable" state instead of treating it as a request failure.
export function getHealth(opts = {}) {
  return get("/api/bank/health", undefined, opts);
}
