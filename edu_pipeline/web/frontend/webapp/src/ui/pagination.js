// Pagination (T4).  Prev / "Page X of N" / Next + page-size selector.
// Emits page / pageSize intents; the module routes them through the URL.

import { el } from "./el.js";

export function createPagination({
  page = 1,
  pageSize = 25,
  total = 0,
  onPage,
  onPageSize,
  pageSizes = [25, 50, 100],
} = {}) {
  const totalPages = Math.max(1, Math.ceil((total || 0) / (pageSize || 25)));
  const atStart = page <= 1;
  const atEnd = page >= totalPages;

  const prev = el("button", { type: "button", class: "qb-page-prev", disabled: atStart }, "‹ Prev");
  const next = el("button", { type: "button", class: "qb-page-next", disabled: atEnd }, "Next ›");
  prev.addEventListener("click", () => { if (!atStart && onPage) onPage(page - 1); });
  next.addEventListener("click", () => { if (!atEnd && onPage) onPage(page + 1); });

  const label = el("span", { class: "qb-page-label" }, `Page ${page} of ${totalPages}`);

  const sizeSel = el(
    "select",
    { class: "qb-page-size", "aria-label": "Results per page" },
    pageSizes.map((n) => el("option", { value: String(n), selected: n === pageSize }, `${n} / page`))
  );
  sizeSel.addEventListener("change", () => {
    if (onPageSize) onPageSize(parseInt(sizeSel.value, 10));
  });

  return el("div", { class: "qb-pager" }, [prev, label, next, sizeSel]);
}
