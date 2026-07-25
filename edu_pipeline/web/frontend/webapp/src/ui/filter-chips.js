// Filter chips (T5).  Shows one removable chip per active filter value plus a
// search-query chip and a Clear All button.  Stateless: emits remove/clear
// intents only.  Chapter chips resolve to the chapter name via the facet labels.

import { el } from "./el.js";

const DIM_LABELS = {
  board: "Board",
  class: "Class",
  subject: "Subject",
  type: "Type",
  book: "Book",
  chapter: "Chapter",
};
const DIM_ORDER = ["board", "class", "subject", "type", "book", "chapter"];

export function createFilterChips({ filters = {}, q = "", facets = {}, onRemove, onRemoveQuery, onClearAll } = {}) {
  const wrap = el("div", { class: "qb-chips" });
  const chips = [];

  if (q) chips.push(chip(`Search: “${q}”`, () => onRemoveQuery()));
  for (const dim of DIM_ORDER) {
    for (const v of filters[dim] || []) {
      chips.push(chip(`${DIM_LABELS[dim]}: ${labelFor(dim, v, facets)}`, () => onRemove(dim, String(v))));
    }
  }

  if (!chips.length) {
    wrap.hidden = true;
    return wrap;
  }
  chips.forEach((c) => wrap.appendChild(c));
  wrap.appendChild(el("button", { type: "button", class: "qb-clear-all", onclick: () => onClearAll() }, "Clear all"));
  return wrap;
}

function labelFor(dim, v, facets) {
  if (dim === "chapter") {
    const opt = (facets.chapter || []).find((o) => String(o.value) === String(v));
    return opt ? opt.label : String(v);
  }
  return String(v);
}

function chip(text, onX) {
  const x = el("button", { type: "button", class: "qb-chip-x", "aria-label": "Remove filter" }, "✕");
  x.addEventListener("click", onX);
  return el("span", { class: "qb-chip" }, [el("span", { class: "qb-chip-text" }, text), x]);
}
