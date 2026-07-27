// Manage Exams (teacher) — Rizee reference: General/Adaptive tabs, 4 stat tiles,
// full sortable exam table with host/unhost + report actions.
import { el, clear } from "../../../ui/el.js";
import * as assess from "../../../api/assess.api.js";

function statCard(icon, label, value, accent) {
  return el("div", { class: "dash-card dash-" + accent }, [
    el("div", { class: "dash-card-top" }, [el("span", { class: "dash-label" }, label), el("span", { class: "dash-icon" }, icon)]),
    el("div", { class: "dash-value" }, String(value)),
  ]);
}
const PAD = (n) => String(n).padStart(2, "0");
function fmtDate(ts) { const d = new Date((ts || 0) * 1000); return `${d.getFullYear()}/${PAD(d.getMonth() + 1)}/${PAD(d.getDate())}`; }
function fmtTime(ts) { const d = new Date((ts || 0) * 1000); let h = d.getHours(); const ap = h >= 12 ? "PM" : "AM"; h = h % 12 || 12; return `${h}:${PAD(d.getMinutes())} ${ap}`; }

export async function renderManage(node, { store, navigate }) {
  clear(node);
  const root = el("div", { class: "dash" });
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Loading…"));

  const user = await assess.ensureSession(store);
  if (!user) { clear(root); root.appendChild(el("div", { class: "ex-error" }, "Could not start a session.")); return; }
  if (user.role !== "teacher") { clear(root); root.appendChild(el("div", { class: "ex-empty-card" }, "Manage Exams is for teacher accounts.")); return; }

  let exams = [];
  let tab = "general";
  let sort = { key: "created_at", dir: -1 };

  async function reload() {
    try { exams = (await assess.listMyExams()).exams || []; }
    catch (e) { clear(root); root.appendChild(el("div", { class: "ex-error" }, e.message || "Could not load exams.")); return; }
    render();
  }

  function sorted() {
    const v = (e) => {
      if (sort.key === "exam_type") return e.exam_type || "";
      if (sort.key === "title") return e.title || "";
      return e.created_at || 0;
    };
    return exams.slice().sort((a, b) => { const x = v(a), y = v(b); return (x < y ? -1 : x > y ? 1 : 0) * sort.dir; });
  }

  function th(label, key) {
    if (!key) return el("th", {}, label);
    const active = sort.key === key;
    const cell = el("th", { class: "mg-sort" + (active ? " active" : "") }, [label, el("span", { class: "mg-arrow" }, active ? (sort.dir === 1 ? " ↑" : " ↓") : " ↕")]);
    cell.addEventListener("click", () => { if (active) sort.dir = -sort.dir; else { sort.key = key; sort.dir = 1; } render(); });
    return cell;
  }

  function render() {
    clear(root);

    const create = el("button", { class: "ex-btn ex-btn-primary" }, "+ Create Exam");
    create.addEventListener("click", () => navigate("/exams/create"));
    root.appendChild(el("div", { class: "dash-head" }, [
      el("div", {}, [el("h2", {}, "Manage Exams"), el("p", { class: "ex-muted" }, "Host, unhost and review your tests")]),
      create,
    ]));

    // tabs
    const t1 = el("button", { class: "ec-tab" + (tab === "general" ? " active" : "") }, "📄 General Exam");
    const t2 = el("button", { class: "ec-tab" + (tab === "adaptive" ? " active" : "") }, "◐ Adaptive Exam");
    t1.addEventListener("click", () => { tab = "general"; render(); });
    t2.addEventListener("click", () => { tab = "adaptive"; render(); });
    root.appendChild(el("div", { class: "ec-tabs", style: "margin-bottom:16px" }, [t1, t2]));

    if (tab === "adaptive") {
      root.appendChild(el("div", { class: "ex-empty-card" }, "Adaptive exams are coming soon."));
      return;
    }

    // stat tiles
    const total = exams.length;
    const ongoing = exams.filter((e) => e.phase === "live").length;
    const completed = exams.filter((e) => e.phase === "ended").length;
    const future = exams.filter((e) => e.phase === "upcoming").length;
    root.appendChild(el("div", { class: "dash-cards" }, [
      statCard("📄", "TOTAL EXAMS", total, "blue"),
      statCard("🔄", "ONGOING EXAMS", ongoing, "green"),
      statCard("✅", "COMPLETED EXAMS", completed, "pink"),
      statCard("🕒", "FUTURE SCHEDULE EXAMS", future, "amber"),
    ]));

    if (!exams.length) { root.appendChild(el("div", { class: "ex-empty-card" }, "No exams yet — create your first test.")); return; }

    // table
    const head = el("tr", {}, [
      el("th", {}, "#"), th("Exam Type", "exam_type"), th("Exam", "title"),
      el("th", {}, "Branch"), el("th", {}, "Class"), el("th", {}, "Section"),
      th("Conducted On", "created_at"), el("th", {}, "Time"), el("th", {}, "Status"), el("th", {}, "Actions"),
    ]);
    const body = el("tbody", {});
    sorted().forEach((ex, i) => {
      const isHosted = ex.status === "hosted";
      const view = el("button", { class: "mg-act", title: "View report", disabled: !ex.attempt_count }, "👁");
      if (ex.attempt_count) view.addEventListener("click", () => navigate("/exams/reports/" + ex.id));
      const toggle = el("button", { class: "mg-act mg-act-toggle" + (isHosted ? " on" : ""), title: isHosted ? "Unhost" : "Host" }, isHosted ? "■" : "▶");
      toggle.addEventListener("click", async () => { toggle.disabled = true; try { await assess.setExamStatus(ex.id, isHosted ? "draft" : "hosted"); await reload(); } catch (e) { toggle.disabled = false; alert(e.message || "Failed"); } });
      const phase = ex.phase || (isHosted ? "live" : "draft");
      const PHASE_LABEL = { live: "Live", upcoming: "Upcoming", ended: "Closed", draft: "Draft" };
      body.appendChild(el("tr", {}, [
        el("td", {}, String(i + 1)),
        el("td", {}, ex.exam_type || "—"),
        el("td", { class: "mg-exam" }, ex.title),
        el("td", {}, "Foundation"),
        el("td", {}, (ex.target_classes && ex.target_classes.length) ? ex.target_classes.join(", ") : "All"),
        el("td", {}, (ex.target_sections && ex.target_sections.length) ? ex.target_sections.join(", ") : "All"),
        el("td", {}, ex.start_at ? fmtDate(ex.start_at) : fmtDate(ex.created_at)),
        el("td", {}, ex.start_at ? fmtTime(ex.start_at) : fmtTime(ex.created_at)),
        el("td", {}, el("span", { class: "ex-badge ex-badge-" + phase }, PHASE_LABEL[phase])),
        el("td", { class: "mg-actions" }, [view, toggle]),
      ]));
    });
    root.appendChild(el("div", { class: "mg-table-wrap" }, [el("table", { class: "mg-table" }, [el("thead", {}, head), body])]));
  }

  await reload();
}
