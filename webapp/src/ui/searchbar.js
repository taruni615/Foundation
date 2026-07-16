// SearchBar (T4).  Debounced full-text input that emits the trimmed query.
// `setValue` syncs the input from the slice (e.g. on refresh/back) without
// clobbering the user mid-type (skips while the input is focused).

import { el } from "./el.js";

export function createSearchBar({
  value = "",
  placeholder = "Search questions…",
  onChange,
  onSubmit,
  debounceMs = 300,
} = {}) {
  let timer = null;
  const input = el("input", { type: "search", class: "qb-search-input", placeholder, value });
  const spinner = el("span", { class: "qb-search-spin", hidden: true });
  const clearBtn = el("button", { type: "button", class: "qb-search-clear", "aria-label": "Clear search" }, "✕");

  function fire() {
    if (onChange) onChange(input.value.trim());
  }

  input.addEventListener("input", () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(fire, debounceMs);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      if (timer) clearTimeout(timer);
      (onSubmit || fire)(input.value.trim());
    }
  });
  clearBtn.addEventListener("click", () => {
    input.value = "";
    fire();
  });

  const root = el("div", { class: "qb-searchbar" }, [
    el("span", { class: "qb-search-icon" }, "🔍"),
    input,
    spinner,
    clearBtn,
  ]);

  return {
    el: root,
    setValue(v) {
      const focused = typeof document !== "undefined" && document.activeElement === input;
      if (!focused && input.value !== v) input.value = v;
    },
    setLoading(on) {
      spinner.hidden = !on;
    },
  };
}
