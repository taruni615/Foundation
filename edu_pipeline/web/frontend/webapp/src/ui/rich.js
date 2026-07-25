// Render rich question content (formulas).
// The extracted bank stores MathML (<math>…</math>), which browsers render
// natively when injected as HTML.  If MathJax is loaded (see index.html) it also
// typesets LaTeX ($…$, \(…\)) and normalizes MathML across browsers.
//
// Content is trusted (our own extraction DB), so innerHTML is acceptable here.

export function mathSpan(content) {
  const s = document.createElement("span");
  s.className = "rich";
  s.innerHTML = content == null ? "" : String(content);
  return s;
}

export function setRich(node, content) {
  if (!node) return;
  node.innerHTML = content == null ? "" : String(content);
  typeset(node);
}

export function typeset(node) {
  try {
    if (typeof window !== "undefined" && window.MathJax && typeof window.MathJax.typesetPromise === "function") {
      window.MathJax.typesetPromise(node ? [node] : undefined);
    }
  } catch (_) { /* MathML still renders natively without MathJax */ }
}
