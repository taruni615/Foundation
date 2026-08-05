// Practice runner -- one question at a time with immediate formative feedback.
//
// Practice differs from a test: the correct option is revealed as soon as the
// student answers, because the point is to learn rather than to be measured.
// The server still withholds the key until the answer is posted, so the client
// never holds it in advance.

import { el, clear } from "../../../ui/el.js";
import * as practice from "../../../api/practice.api.js";

function fmtClock(s) {
  s = Math.max(0, s | 0);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function createPracticeRunner(node, { sessionId, navigate }) {
  let session = null;
  let idx = 0;
  let askedAt = Date.now();
  let ticker = null;
  let remaining = 0;
  let finishing = false;
  const feedback = {};   // index -> answer response

  const root = el("div", { class: "pr-run" });
  clear(node);
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Loading practice set…"));

  practice.getSession(sessionId).then((d) => {
    session = d.session;
    if (session.status !== "active") { navigate("/practice/report/" + sessionId); return; }
    idx = Math.min(session.answered, session.total - 1);
    if (session.time_limit_sec) {
      const elapsed = Math.floor(Date.now() / 1000) - session.started_at;
      remaining = Math.max(0, session.time_limit_sec - elapsed);
      startTimer();
    }
    render();
  }).catch((e) => {
    clear(root);
    root.appendChild(el("div", { class: "ex-error" }, e.message || "Could not load this practice set."));
  });

  function startTimer() {
    ticker = setInterval(() => {
      remaining -= 1;
      const t = root.querySelector(".pr-timer");
      if (t) t.textContent = fmtClock(remaining);
      if (remaining <= 0) { stopTimer(); finish(); }
    }, 1000);
  }
  function stopTimer() { if (ticker) { clearInterval(ticker); ticker = null; } }

  async function choose(choice) {
    if (feedback[idx]) return;                      // already answered
    const spent = Math.round((Date.now() - askedAt) / 1000);
    try {
      feedback[idx] = await practice.answer(sessionId, { index: idx, choice, time_sec: spent });
    } catch (e) {
      const err = root.querySelector(".pr-err");
      if (err) { err.textContent = e.message || "Could not record that answer."; err.hidden = false; }
      return;
    }
    render();
  }

  function next() {
    if (idx < session.total - 1) { idx += 1; askedAt = Date.now(); render(); }
    else finish();
  }

  async function finish() {
    if (finishing) return;
    finishing = true;
    stopTimer();
    try { await practice.finish(sessionId); } catch (_) { /* report still renders */ }
    navigate("/practice/report/" + sessionId);
  }

  function render() {
    const q = session.questions[idx];
    const fb = feedback[idx];
    clear(root);

    const answered = Object.keys(feedback).length;
    root.appendChild(el("div", { class: "pr-run-head" }, [
      el("div", {}, [
        el("strong", {}, session.label),
        el("div", { class: "ex-muted" },
          `${session.chapter_name || "Mixed"} · Question ${idx + 1} of ${session.total}`),
      ]),
      session.time_limit_sec
        ? el("span", { class: "pr-timer" }, fmtClock(remaining))
        : el("span", { class: "ex-muted" }, `${answered}/${session.total} answered`),
    ]));

    root.appendChild(el("div", { class: "pr-progress" },
      el("div", { class: "pr-progress-fill", style: `width:${Math.round(100 * answered / session.total)}%` })));

    root.appendChild(el("div", { class: "pr-tags" }, [
      el("span", { class: "pr-tag pr-diff-" + (q.difficulty || "Moderate").toLowerCase() }, q.difficulty),
      q.cognitive_level ? el("span", { class: "pr-tag" }, q.cognitive_level) : null,
      q.subtopic ? el("span", { class: "pr-tag" }, q.subtopic) : null,
    ].filter(Boolean)));

    // Text node, not innerHTML -- stems come from the bank and are untrusted.
    root.appendChild(el("div", { class: "pr-stem" }, q.stem));

    const opts = el("div", { class: "pr-options" });
    q.options.forEach((text, i) => {
      let cls = "pr-option";
      if (fb) {
        if (i === fb.correct_index) cls += " pr-option-correct";
        else if (i === fb.chosen_index) cls += " pr-option-wrong";
      }
      const btn = el("button", { class: cls, type: "button" }, [
        el("span", { class: "pr-option-key" }, String.fromCharCode(65 + i)),
        el("span", {}, text),
      ]);
      if (!fb) btn.addEventListener("click", () => choose(i));
      else btn.disabled = true;
      opts.appendChild(btn);
    });
    root.appendChild(opts);

    root.appendChild(el("div", { class: "pr-err", hidden: true }));

    if (fb) {
      root.appendChild(el("div", { class: "pr-feedback " + (fb.is_correct ? "pr-ok" : "pr-no") }, [
        el("strong", {}, fb.is_correct ? "✓ Correct" : "✗ Not quite"),
        fb.learning_objective ? el("div", { class: "ex-muted" }, fb.learning_objective) : null,
      ].filter(Boolean)));
    }

    const actions = el("div", { class: "pr-actions" });
    if (!fb) {
      const skip = el("button", { class: "ex-btn" }, "Skip");
      skip.addEventListener("click", () => choose(null));
      actions.appendChild(skip);
    } else {
      const nextBtn = el("button", { class: "ex-btn ex-btn-primary" },
        idx < session.total - 1 ? "Next question →" : "Finish & see results");
      nextBtn.addEventListener("click", next);
      actions.appendChild(nextBtn);
    }
    const end = el("button", { class: "ex-link" }, "End session");
    end.addEventListener("click", finish);
    actions.appendChild(end);
    root.appendChild(actions);
  }

  return { destroy: stopTimer };
}
