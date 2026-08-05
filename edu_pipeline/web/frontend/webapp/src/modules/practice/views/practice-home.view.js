// Practice home -- pick a mode, pick a chapter, start a session.
import { el, clear } from "../../../ui/el.js";
import * as assess from "../../../api/assess.api.js";
import * as practice from "../../../api/practice.api.js";

const MODE_ICON = {
  topic: "🎯", chapter: "📗", mixed: "🔀", sprint: "⏱",
  adaptive: "🧠", mistake: "🔁", daily: "⭐", chapter_test: "📋",
};

// The Daily Challenge is launched from the dashboard widget (one per day), so
// it is not offered as a free-choice mode here.
const HIDDEN_MODES = new Set(["daily"]);

function modeCard(m, onPick) {
  const meta = [];
  meta.push(m.is_test ? "Mastery score" : `${m.size} questions`);
  if (m.time_limit_sec) meta.push(`${Math.round(m.time_limit_sec / 60)} min limit`);
  if (m.needs_chapter) meta.push("needs a chapter");

  const card = el("div", { class: "pr-mode-card", tabindex: "0", role: "button" }, [
    el("div", { class: "pr-mode-top" }, [
      el("span", { class: "pr-mode-icon" }, MODE_ICON[m.mode] || "📝"),
      el("strong", {}, m.label),
    ]),
    el("div", { class: "ex-muted" }, m.purpose),
    el("div", { class: "pr-mode-meta" }, meta.join(" · ")),
  ]);
  const go = () => onPick(m);
  card.addEventListener("click", go);
  card.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
  });
  return card;
}

export async function renderPracticeHome(node, { store, navigate }) {
  clear(node);
  const root = el("div", { class: "pr" });
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Loading practice modes…"));

  // Populate the auth slice even when this route is opened directly, otherwise
  // the top bar shows "Guest" and the sidenav's role gating falls open.
  if (store) await assess.ensureSession(store).catch(() => null);

  let modes = [];
  let chapters = [];
  let bank = { ok: false, gradable: 0 };
  try {
    const [mRes, hRes] = await Promise.all([practice.modes(), practice.health()]);
    modes = (mRes.modes || []).filter((m) => !HIDDEN_MODES.has(m.mode));
    bank = hRes || bank;
  } catch (e) {
    clear(root);
    root.appendChild(el("div", { class: "ex-error" }, e.message || "Could not load practice modes."));
    return;
  }

  clear(root);
  root.appendChild(el("div", { class: "dash-head" }, [
    el("div", {}, [
      el("h2", {}, "Practice"),
      el("p", { class: "ex-muted" }, "Choose how you want to practise. Every set is auto-graded and feeds your analytics."),
    ]),
  ]));

  if (!bank.ok) {
    root.appendChild(el("div", { class: "ex-error" },
      "The question bank is unavailable, so practice cannot start right now." +
      (bank.error ? ` (${bank.error})` : "")));
    return;
  }

  // --- chapter picker (loaded lazily; only some modes need it) ---
  const chapterWrap = el("div", { class: "pr-chapter-row", hidden: true });
  const select = el("select", { class: "ex-input" });
  const status = el("span", { class: "ex-muted" }, "Loading chapters…");
  chapterWrap.appendChild(el("label", {}, "Chapter"));
  chapterWrap.appendChild(select);
  chapterWrap.appendChild(status);

  let chaptersLoaded = false;
  async function ensureChapters() {
    if (chaptersLoaded) return;
    chaptersLoaded = true;
    try {
      const d = await practice.chapters({ min: 5 });
      chapters = d.chapters || [];
      clear(select);
      chapters.forEach((c) => {
        select.appendChild(el("option", { value: String(c.chapter_id) },
          `${c.chapter_name} — ${c.count} questions`));
      });
      status.textContent = chapters.length
        ? `${chapters.length} chapters ready`
        : "No chapter has enough auto-gradable questions yet.";
    } catch (e) {
      status.textContent = e.message || "Could not load chapters.";
    }
  }

  const error = el("div", { class: "ex-error", hidden: true });

  async function start(m) {
    error.hidden = true;
    const body = { mode: m.mode };
    if (m.needs_chapter) {
      await ensureChapters();
      chapterWrap.hidden = false;
      if (!select.value) {
        error.textContent = "Pick a chapter first, then choose the mode again.";
        error.hidden = false;
        chapterWrap.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }
      body.chapter_id = Number(select.value);
    }
    try {
      const d = await practice.startSession(body);
      navigate("/practice/run/" + d.session.id);
    } catch (e) {
      error.textContent = e.message || "Could not start that practice set.";
      error.hidden = false;
    }
  }

  const grid = el("div", { class: "pr-mode-grid" });
  modes.forEach((m) => grid.appendChild(modeCard(m, start)));
  root.appendChild(grid);
  root.appendChild(chapterWrap);
  root.appendChild(error);

  // Pre-load chapters so the picker is ready before a chapter mode is clicked.
  ensureChapters().then(() => { chapterWrap.hidden = false; });

  // --- recent sessions ---
  root.appendChild(el("h3", { class: "ex-section-title" }, "Recent practice"));
  const recent = el("div", { class: "ex-manage-list" }, el("div", { class: "ex-muted" }, "Loading…"));
  root.appendChild(recent);
  try {
    const d = await practice.listSessions();
    const rows = (d.sessions || []).slice(0, 8);
    clear(recent);
    if (!rows.length) {
      recent.appendChild(el("div", { class: "ex-empty-card" }, "No practice yet — pick a mode above."));
    } else {
      rows.forEach((s) => {
        const open = el("button", { class: "ex-link" },
          s.status === "finished" ? "View report" : "Resume");
        open.addEventListener("click", () =>
          navigate(s.status === "finished" ? "/practice/report/" + s.id : "/practice/run/" + s.id));
        recent.appendChild(el("div", { class: "ex-manage-row" }, [
          el("div", {}, [
            el("strong", {}, s.label),
            el("div", { class: "ex-muted" },
              `${s.chapter_name || "Mixed"} · ${s.answered}/${s.total} answered`),
          ]),
          el("span", { class: "ex-badge ex-badge-" + (s.status === "finished" ? "live" : "draft") },
            s.status === "finished" ? "Done" : "In progress"),
          open,
        ]));
      });
    }
  } catch (e) {
    clear(recent);
    recent.appendChild(el("div", { class: "ex-muted" }, "Could not load recent practice."));
  }
}
