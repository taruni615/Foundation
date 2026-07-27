// Results Table (T4).  Read-only, renders item summaries from the bank slice.
// No sorting / selection / row navigation yet (later tasks).

import { el } from "./el.js";

function trunc(s, n = 160) {
  s = String(s || "");
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export function createQuestionTable(items = []) {
  const head = el("tr", { class: "qt-head" }, [
    el("th", {}, "ID"),
    el("th", {}, "Question"),
    el("th", {}, "Type"),
    el("th", {}, "Chapter"),
    el("th", {}, "Book"),
    el("th", {}, "Class"),
    el("th", { title: "Has answer" }, "Ans"),
  ]);

  const rows = items.map((it) =>
    el("tr", { class: "qt-row", dataset: { id: String(it.id) } }, [
      el("td", { class: "qt-id" }, String(it.id)),
      el("td", { class: "qt-stem" }, trunc(it.stem)),
      el("td", {}, el("span", { class: "qb-badge" }, it.question_type || "—")),
      el("td", {}, it.chapter_name || "—"),
      el("td", {}, it.book_slug || "—"),
      el("td", {}, it.class || "—"),
      el("td", { class: "qt-ans" }, it.has_answer ? "✓" : "—"),
    ])
  );

  return el("table", { class: "qb-table" }, [
    el("thead", {}, head),
    el("tbody", { class: "qt-body" }, rows),
  ]);
}
