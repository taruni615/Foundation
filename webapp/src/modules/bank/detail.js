// Item Detail view (T6).  Read-only.  Renders loading / error / not-found /
// success from a view-model the module supplies, plus a "Back to Results" link
// that returns to the preserved search URL.
//
// No editing / versions / AI / review / collections / compare / usage — those
// are later tasks.

import { el, clear } from "../../ui/el.js";

const META_FIELDS = [
  { key: "board", label: "Board" },
  { key: "class", label: "Class" },
  { key: "subject", label: "Subject" },
  { key: "book", label: "Book" },
  { key: "chapter", label: "Chapter" },
];

export function createDetailView({ node, onBack, onRetry } = {}) {
  const root = el("div", { class: "qb-detail" });
  clear(node);
  node.appendChild(root);

  function backBar() {
    const back = el("button", { type: "button", class: "qb-back" }, "‹ Back to Results");
    back.addEventListener("click", () => onBack && onBack());
    return el("div", { class: "qb-detail-bar" }, [back]);
  }

  function metaValue(item, key) {
    if (key === "book") return item.book_slug || "—";
    if (key === "chapter") return item.chapter_name || "—";
    return item[key] || "—";
  }

  function success(vm) {
    const item = vm.item || {};
    const head = el("div", { class: "qb-detail-head" }, [
      el("span", { class: "qb-detail-id" }, "#" + item.id),
      el("span", { class: "qb-badge" }, item.question_type || "—"),
    ]);
    const question = el("section", { class: "qb-detail-section" }, [
      el("div", { class: "qb-detail-label" }, "Question"),
      el("div", { class: "qb-detail-text" }, String(item.stem || "—")),
    ]);
    const answer = el("section", { class: "qb-detail-section" }, [
      el("div", { class: "qb-detail-label" }, "Answer"),
      el("div", { class: "qb-detail-text" }, item.has_answer ? String(item.answer || "") : "—"),
    ]);
    const meta = el(
      "section",
      { class: "qb-detail-section" },
      [el("div", { class: "qb-detail-label" }, "Source")].concat(
        META_FIELDS.map((f) =>
          el("div", { class: "qb-meta-row", dataset: { key: f.key } }, [
            el("span", { class: "qb-meta-key" }, f.label),
            el("span", { class: "qb-meta-val" }, metaValue(item, f.key)),
          ])
        )
      )
    );
    return el("div", { class: "qb-detail-body" }, [head, question, answer, meta]);
  }

  function render(vm) {
    clear(root);
    root.appendChild(backBar());
    if (vm.status === "loading") {
      root.appendChild(el("div", { class: "qb-loading" }, "Loading…"));
    } else if (vm.status === "notfound") {
      root.appendChild(el("div", { class: "qb-empty" }, `Question #${vm.id} not found.`));
    } else if (vm.status === "error") {
      const retry = el("button", { type: "button", class: "qb-retry" }, "Retry");
      retry.addEventListener("click", () => onRetry && onRetry());
      root.appendChild(
        el("div", { class: "qb-error" }, [
          el("p", { class: "qb-error-title" }, "Couldn’t load this question."),
          el("p", { class: "qb-error-detail" }, (vm.error && vm.error.message) || "Something went wrong."),
          retry,
        ])
      );
    } else {
      root.appendChild(success(vm));
    }
  }

  return { render, destroy: () => clear(node) };
}
