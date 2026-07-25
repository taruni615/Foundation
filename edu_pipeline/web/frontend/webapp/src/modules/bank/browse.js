// Browse view (T4).  Renders the read-only search screen from the bank slice:
// SearchBar + results count + results table + pagination, with loading / error /
// empty states.  Builds a persistent skeleton once; each render() updates only
// the dynamic regions so the search input keeps focus while typing.

import { el, clear } from "../../ui/el.js";
import { createSearchBar } from "../../ui/searchbar.js";
import { createQuestionTable } from "../../ui/question-table.js";
import { createPagination } from "../../ui/pagination.js";
import { createFacetPanel } from "../../ui/facet-panel.js";
import { createFilterChips } from "../../ui/filter-chips.js";

export function createBrowseView({ node, handlers = {} }) {
  const search = createSearchBar({ onChange: (q) => handlers.onSearch && handlers.onSearch(q) });
  const count = el("span", { class: "qb-count" }, "");
  const toolbar = el("div", { class: "qb-toolbar" }, [search.el, count]);
  const chipsRegion = el("div", { class: "qb-chips-wrap" });
  const facetsRegion = el("div", { class: "qb-facets-wrap" });
  const results = el("div", { class: "qb-results" });
  const pager = el("div", { class: "qb-pager-wrap" });
  const body = el("div", { class: "qb-body" }, [facetsRegion, el("div", { class: "qb-main" }, [results, pager])]);
  const root = el("div", { class: "qb-browse" }, [toolbar, chipsRegion, body]);

  clear(node);
  node.appendChild(root);

  function render(state) {
    search.setValue(state.q || "");
    search.setLoading(state.loading === "loading");

    // count
    if (state.loading === "loading") count.textContent = "Searching…";
    else if (state.loading === "error") count.textContent = "";
    else count.textContent = `${state.total} result${state.total === 1 ? "" : "s"}`;

    // filter chips (active filters + query)
    clear(chipsRegion);
    chipsRegion.appendChild(
      createFilterChips({
        filters: state.filters || {},
        q: state.q || "",
        facets: state.facets || {},
        onRemove: handlers.onRemoveFilter,
        onRemoveQuery: handlers.onRemoveQuery,
        onClearAll: handlers.onClearAll,
      })
    );

    // facet panel (counts from the slice's facets)
    clear(facetsRegion);
    facetsRegion.appendChild(
      createFacetPanel({
        facets: state.facets || {},
        selected: state.filters || {},
        onToggle: handlers.onToggleFacet,
        onClearGroup: handlers.onClearGroup,
      })
    );

    // results region
    clear(results);
    const hasResults = state.results && state.results.length > 0;
    if (state.loading === "loading" && !hasResults) {
      results.appendChild(el("div", { class: "qb-loading" }, "Loading…"));
    } else if (state.loading === "error") {
      const retry = el("button", { type: "button", class: "qb-retry" }, "Retry");
      retry.addEventListener("click", () => handlers.onRetry && handlers.onRetry());
      results.appendChild(
        el("div", { class: "qb-error" }, [
          el("p", { class: "qb-error-title" }, "Couldn’t load questions."),
          el("p", { class: "qb-error-detail" }, (state.error && state.error.message) || "Something went wrong."),
          retry,
        ])
      );
    } else if (!hasResults) {
      const anyFilter =
        !!state.q || Object.values(state.filters || {}).some((a) => a && a.length);
      results.appendChild(
        el("div", { class: "qb-empty" },
          anyFilter ? "No questions match your search." : "No questions in the bank yet.")
      );
    } else {
      results.appendChild(createQuestionTable(state.results));
    }

    // pager (only with results)
    clear(pager);
    if (state.loading !== "error" && state.total > 0) {
      pager.appendChild(
        createPagination({
          page: state.page,
          pageSize: state.pageSize,
          total: state.total,
          onPage: handlers.onPage,
          onPageSize: handlers.onPageSize,
        })
      );
    }
  }

  function destroy() {
    clear(node);
  }

  return { render, destroy };
}
