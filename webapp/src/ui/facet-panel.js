// Facet panel (T5).  Renders one collapsible group per dimension with
// checkbox options + counts.  Stateless: it reads `selected` (from the slice,
// which derives from the URL) and emits toggle/clear intents only.
//
// - Multi-select within a group (OR); AND across groups -- enforced by the
//   backend, the panel just reflects/sets the slice arrays.
// - Selected-but-now-zero options stay visible (sticky) so they can be removed.
// - Chapter depends on Book: the Chapter group is inert until a Book is selected.

import { el } from "./el.js";

const GROUPS = [
  { dim: "board", label: "Board" },
  { dim: "class", label: "Class" },
  { dim: "subject", label: "Subject" },
  { dim: "type", label: "Type" },
  { dim: "book", label: "Book" },
  { dim: "chapter", label: "Chapter" },
];

export function createFacetPanel({ facets = {}, selected = {}, onToggle, onClearGroup } = {}) {
  const panel = el("aside", { class: "qb-facets", "aria-label": "Filters" });
  for (const g of GROUPS) {
    panel.appendChild(
      facetGroup(g, facets[g.dim] || [], (selected[g.dim] || []).map(String), selected, onToggle, onClearGroup)
    );
  }
  return panel;
}

function facetGroup(g, options, selectedVals, selected, onToggle, onClearGroup) {
  const wrap = el("div", { class: "qb-facet-group", dataset: { dim: g.dim } });
  wrap.appendChild(
    el("div", { class: "qb-facet-head" }, [
      el("span", { class: "qb-facet-title" }, g.label),
      selectedVals.length
        ? el("button", { type: "button", class: "qb-facet-clear", onclick: () => onClearGroup(g.dim) }, "clear")
        : null,
    ])
  );

  // Book -> Chapter dependency
  if (g.dim === "chapter" && (!selected.book || selected.book.length === 0)) {
    wrap.appendChild(el("div", { class: "qb-facet-hint" }, "Select a book to filter by chapter"));
    return wrap;
  }

  const list = el("div", { class: "qb-facet-options" });
  const seen = new Set();
  for (const o of options) {
    seen.add(String(o.value));
    list.appendChild(facetOption(g.dim, o, selectedVals.includes(String(o.value)), onToggle));
  }
  // sticky: selected values absent from the latest counts -> show with count 0
  for (const v of selectedVals) {
    if (!seen.has(String(v))) {
      list.appendChild(facetOption(g.dim, { value: v, count: 0 }, true, onToggle));
    }
  }
  if (!options.length && !selectedVals.length) {
    list.appendChild(el("div", { class: "qb-facet-empty" }, "—"));
  }
  wrap.appendChild(list);
  return wrap;
}

function facetOption(dim, o, isSelected, onToggle) {
  const cb = el("input", { type: "checkbox" });
  cb.checked = !!isSelected;
  cb.addEventListener("change", () => onToggle(dim, String(o.value)));
  const label = o.label != null ? o.label : String(o.value);
  return el(
    "label",
    { class: "qb-facet-opt" + (isSelected ? " selected" : ""), dataset: { dim, value: String(o.value) } },
    [cb, el("span", { class: "qb-opt-label" }, label), el("span", { class: "qb-opt-count" }, String(o.count ?? 0))]
  );
}
