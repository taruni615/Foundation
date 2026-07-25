// Teacher / class-wide result analytics (Slice 1): exam list -> class report.
import { el, clear } from "../../../ui/el.js";
import * as assess from "../../../api/assess.api.js";

function tile(label, value, accent) {
  return el("div", { class: "ex-tile ex-tile-" + (accent || "blue") }, [
    el("div", { class: "ex-tile-val" }, String(value)),
    el("div", { class: "ex-tile-lbl" }, label),
  ]);
}
function fmtTime(s) { s = s | 0; return `${Math.floor(s / 60)}m ${s % 60}s`; }

async function gateTeacher(node, root, store, navigate) {
  const user = await assess.ensureSession(store);
  if (!user) { clear(root); root.appendChild(el("div", { class: "ex-error" }, "Could not start a session.")); return null; }
  if (user.role !== "teacher") {
    clear(root);
    root.appendChild(el("div", { class: "ex-empty-card" }, "Test Reports are for teacher accounts."));
    return null;
  }
  return user;
}

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function cardDate(ts) { const d = new Date((ts || 0) * 1000); return `${MON[d.getMonth()]} ${d.getDate()} ${d.getFullYear()}`; }
function rangeLabel(exams) {
  const ts = exams.map((e) => e.created_at || 0).filter(Boolean);
  if (!ts.length) return "";
  const f = (t) => { const d = new Date(t * 1000); return `${String(d.getDate()).padStart(2, "0")}-${String(d.getMonth() + 1).padStart(2, "0")}-${d.getFullYear()}`; };
  return `${f(Math.min(...ts))} - ${f(Math.max(...ts))}`;
}

// ---- Test Reports landing (View Test Results) ----
export async function renderTeacherReports(node, { store, navigate }) {
  clear(node);
  const root = el("div", { class: "dash" });
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Loading…"));
  if (!(await gateTeacher(node, root, store, navigate))) return;

  let exams = [];
  try { exams = (await assess.listMyExams()).exams || []; }
  catch (e) { clear(root); root.appendChild(el("div", { class: "ex-error" }, e.message || "Could not load.")); return; }

  let tab = "examwise";
  let typeFilter = "";
  let selectedId = "";

  function render() {
    clear(root);
    // tabs
    const t1 = el("button", { class: "ec-tab" + (tab === "examwise" ? " active" : "") }, "📄 Exam Wise Report");
    const t2 = el("button", { class: "ec-tab" + (tab === "overall" ? " active" : "") }, "👥 Overall Report");
    t1.addEventListener("click", () => { tab = "examwise"; render(); });
    t2.addEventListener("click", () => { tab = "overall"; render(); });
    root.appendChild(el("div", { class: "ec-tabs", style: "margin-bottom:16px" }, [t1, t2]));

    const card = el("div", { class: "tr-card" });
    card.appendChild(el("div", { class: "tr-card-head" }, [
      el("h2", {}, "View Test Results"),
      el("span", { class: "tr-daterange" }, ["🗓 ", rangeLabel(exams) || "—"]),
    ]));
    root.appendChild(card);

    if (tab === "overall") { renderOverall(card); return; }

    // --- Exam Wise: filters ---
    const types = [...new Set(exams.map((e) => e.exam_type).filter(Boolean))];
    const typeSel = el("select", { class: "ex-input" }, [el("option", { value: "" }, "All types"), ...types.map((t) => el("option", { value: t, selected: typeFilter === t }, t))]);
    const patternSel = el("select", { class: "ex-input" }, [el("option", { value: "full" }, "Full Exams")]);
    const filtered = () => exams.filter((e) => !typeFilter || e.exam_type === typeFilter);
    const nameSel = el("select", { class: "ex-input" }, [el("option", { value: "" }, "Test Name"), ...filtered().map((e) => el("option", { value: e.id, selected: selectedId === e.id }, e.title))]);
    const sectionSel = el("select", { class: "ex-input", disabled: true }, [el("option", {}, "No Options")]);
    const getBtn = el("button", { class: "tr-getbtn", disabled: !selectedId }, "Get Report");

    typeSel.addEventListener("change", () => { typeFilter = typeSel.value; selectedId = ""; render(); });
    nameSel.addEventListener("change", () => { selectedId = nameSel.value; getBtn.disabled = !selectedId; getBtn.classList.toggle("on", !!selectedId); });
    getBtn.addEventListener("click", () => { if (selectedId) navigate("/exams/reports/" + selectedId); });

    card.appendChild(el("div", { class: "tr-filters" }, [
      el("div", { class: "tr-field" }, [el("div", { class: "tr-lbl" }, "TEST TYPE"), typeSel]),
      el("div", { class: "tr-field" }, [el("div", { class: "tr-lbl" }, "TEST PATTERN"), patternSel]),
      el("div", { class: "tr-field" }, [el("div", { class: "tr-lbl" }, "TEST NAME"), nameSel]),
      el("div", { class: "tr-field" }, [el("div", { class: "tr-lbl" }, "SECTION"), sectionSel]),
      el("div", { class: "tr-field tr-field-btn" }, [getBtn]),
    ]));

    // --- recent exam cards ---
    const recent = filtered().slice().sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    const grid = el("div", { class: "tr-recent" });
    grid.appendChild(el("div", { class: "tr-recent-lbl" }, "SELECT RECENT EXAM"));
    const cards = el("div", { class: "tr-recent-grid" });
    if (!recent.length) cards.appendChild(el("div", { class: "ex-muted" }, "No exams yet."));
    for (const e of recent) {
      const c = el("button", { class: "tr-recent-card" }, `${e.title} ( ${cardDate(e.created_at)} )`);
      c.addEventListener("click", () => navigate("/exams/reports/" + e.id));
      cards.appendChild(c);
    }
    grid.appendChild(cards);
    card.appendChild(grid);
  }

  function renderOverall(card) {
    const examSel = el("select", { class: "ex-input" }, [el("option", { value: "" }, "All exams")]);
    const classSel = el("select", { class: "ex-input" }, [el("option", { value: "" }, "All classes"), ...["6", "7", "8", "9", "10"].map((c) => el("option", { value: c }, "Class " + c))]);
    const levelSel = el("select", { class: "ex-input" }, [el("option", {}, "Foundation")]);
    const getBtn = el("button", { class: "tr-getbtn on" }, "Get Results");
    const resetBtn = el("button", { class: "ex-btn" }, "Reset");
    card.appendChild(el("div", { class: "tr-filters" }, [
      el("div", { class: "tr-field" }, [el("div", { class: "tr-lbl" }, "SELECT LEVEL"), levelSel]),
      el("div", { class: "tr-field" }, [el("div", { class: "tr-lbl" }, "SELECT EXAM"), examSel]),
      el("div", { class: "tr-field" }, [el("div", { class: "tr-lbl" }, "SELECT CLASS"), classSel]),
      el("div", { class: "tr-field tr-field-btn" }, [getBtn, resetBtn]),
    ]));
    const body = el("div");
    card.appendChild(body);
    let searchTerm = "";

    async function load() {
      clear(body);
      body.appendChild(el("div", { class: "ex-loading" }, "Loading…"));
      let r;
      try { r = (await assess.overallReport({ exam_type: examSel.value, klass: classSel.value })).report; }
      catch (e) { clear(body); body.appendChild(el("div", { class: "ex-error" }, e.message || "Could not load.")); return; }
      // populate exam-type options once
      if (examSel.querySelectorAll("option").length <= 1) (r.exam_types || []).forEach((t) => examSel.appendChild(el("option", { value: t }, t)));
      clear(body);
      body.appendChild(el("div", { class: "dash-cards", style: "margin-top:4px" }, [
        statTile("📄", "TOTAL EXAMS", r.total_exams, "blue"),
        statTile("📊", "AVG SCORE", r.avg_score, "green"),
        statTile("🏆", "BEST SCORE", r.best_score, "amber"),
        statTile("👥", "TOTAL STUDENTS", r.total_students, "pink"),
      ]));
      const search = el("input", { class: "ex-input", placeholder: "Search", style: "max-width:280px" });
      search.value = searchTerm;
      search.addEventListener("input", () => { searchTerm = search.value; renderTable(r.rows); });
      const dl = el("button", { class: "tr-dl", title: "Download CSV" }, "⬇");
      dl.addEventListener("click", () => downloadCsv(r.rows));
      body.appendChild(el("div", { class: "tr-tabletop" }, [search, dl]));
      const tableWrap = el("div", {});
      body.appendChild(tableWrap);
      function renderTable(rows) {
        const filtered = rows.filter((x) => x.exam.toLowerCase().includes(searchTerm.toLowerCase()));
        clear(tableWrap);
        const t = el("div", { class: "ex-table" });
        t.appendChild(el("div", { class: "ex-tr ex-th" }, [el("span", { class: "ex-td-grow" }, "Exam Name"), el("span", {}, "Class"), el("span", {}, "Total Students"), el("span", {}, "Average Score"), el("span", {}, "Max Score"), el("span", {}, "Min Score")]));
        if (!filtered.length) t.appendChild(el("div", { class: "ex-tr" }, [el("span", { class: "ex-muted" }, "No data.")]));
        filtered.forEach((x) => t.appendChild(el("div", { class: "ex-tr" }, [
          el("span", { class: "ex-td-grow" }, x.exam), el("span", {}, x.klass), el("span", {}, String(x.total_students)),
          el("span", {}, String(x.average_score)), el("span", {}, String(x.max_score)), el("span", {}, String(x.min_score)),
        ])));
        tableWrap.appendChild(t);
      }
      renderTable(r.rows);
    }
    function downloadCsv(rows) {
      const head = ["Exam Name", "Class", "Total Students", "Average Score", "Max Score", "Min Score"];
      const lines = [head.join(",")].concat(rows.map((x) => [x.exam, x.klass, x.total_students, x.average_score, x.max_score, x.min_score].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")));
      const blob = new Blob([lines.join("\n")], { type: "text/csv" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "overall-report.csv"; a.click();
    }
    getBtn.addEventListener("click", load);
    resetBtn.addEventListener("click", () => { examSel.value = ""; classSel.value = ""; searchTerm = ""; load(); });
    load();
  }

  function statTile(icon, label, value, accent) {
    return el("div", { class: "dash-card dash-" + accent }, [
      el("div", { class: "dash-card-top" }, [el("span", { class: "dash-label" }, label), el("span", { class: "dash-icon" }, icon)]),
      el("div", { class: "dash-value" }, String(value)),
    ]);
  }

  render();
}

// ---- one exam's class report ----
export async function renderTeacherReport(node, { store, navigate, examId }) {
  clear(node);
  const root = el("div", { class: "ex-page" });
  node.appendChild(root);
  root.appendChild(el("div", { class: "ex-loading" }, "Loading report…"));
  if (!(await gateTeacher(node, root, store, navigate))) return;

  let r;
  try { r = (await assess.examReport(examId)).report; }
  catch (e) { clear(root); root.appendChild(el("div", { class: "ex-error" }, e.message || "Could not load report.")); return; }
  clear(root);

  const back = el("button", { class: "ex-link" }, "‹ All reports");
  back.addEventListener("click", () => navigate("/exams/reports"));
  root.appendChild(el("div", { class: "ex-page-head" }, [
    el("div", {}, [el("h2", {}, r.title), el("p", { class: "ex-muted" }, `${r.exam_type} · ${r.participants} participant${r.participants === 1 ? "" : "s"}`)]),
    back,
  ]));

  if (!r.participants) { root.appendChild(el("div", { class: "ex-empty-card" }, "No attempts yet.")); return; }

  root.appendChild(el("div", { class: "ex-tiles" }, [
    tile("Participants", r.participants, "blue"),
    tile("Average", `${r.avg_percentage}%`, "green"),
    tile("Highest", `${r.high_percentage}%`, "pink"),
    tile("Avg time", fmtTime(r.avg_time_sec), "teal"),
  ]));

  // score distribution
  root.appendChild(el("h3", { class: "ex-section-title" }, "Score distribution"));
  const maxC = Math.max(1, ...r.distribution.map((d) => d.count));
  const chart = el("div", { class: "ex-chart" });
  r.distribution.forEach((d) => {
    chart.appendChild(el("div", { class: "ex-chart-col" }, [
      el("div", { class: "ex-chart-barwrap" }, [el("div", { class: "ex-chart-bar", style: `height:${Math.round(100 * d.count / maxC)}%`, title: `${d.count}` })]),
      el("div", { class: "ex-chart-pct" }, String(d.count)),
      el("div", { class: "ex-chart-lbl" }, d.range + "%"),
    ]));
  });
  root.appendChild(chart);

  // subject-wise class accuracy
  root.appendChild(el("h3", { class: "ex-section-title" }, "Subject-wise class accuracy"));
  const subjWrap = el("div", { class: "ex-subj-list" });
  for (const [s, v] of Object.entries(r.per_subject || {})) {
    subjWrap.appendChild(el("div", { class: "ex-subj-row" }, [
      el("div", { class: "ex-subj-name" }, s),
      el("div", { class: "ex-bar" }, [el("div", { class: "ex-bar-fill ex-bar-" + (v.accuracy >= 60 ? "green" : v.accuracy >= 35 ? "blue" : "pink"), style: `width:${v.accuracy}%` })]),
      el("div", { class: "ex-subj-stat" }, `${v.accuracy}%`),
    ]));
  }
  root.appendChild(subjWrap);

  // per-question analysis
  root.appendChild(el("h3", { class: "ex-section-title" }, "Question analysis (correct rate)"));
  const qtable = el("div", { class: "ex-table" });
  qtable.appendChild(el("div", { class: "ex-tr ex-th" }, [el("span", {}, "#"), el("span", { class: "ex-td-grow" }, "Question"), el("span", {}, "Subject"), el("span", {}, "Correct rate")]));
  r.per_question.forEach((q, i) => {
    const hard = q.correct_rate < 40;
    qtable.appendChild(el("div", { class: "ex-tr" + (hard ? " ex-tr-hard" : "") }, [
      el("span", {}, String(i + 1)),
      el("span", { class: "ex-td-grow ex-td-stem", title: q.stem }, q.stem),
      el("span", {}, q.subject || "—"),
      el("span", { class: "ex-td-rate" }, [
        el("span", { class: "ex-bar ex-bar-inline" }, [el("div", { class: "ex-bar-fill ex-bar-" + (hard ? "pink" : "green"), style: `width:${q.correct_rate}%` })]),
        el("span", {}, `${q.correct_rate}%`),
      ]),
    ]));
  });
  root.appendChild(qtable);

  // leaderboard
  root.appendChild(el("h3", { class: "ex-section-title" }, "Leaderboard"));
  const lb = el("div", { class: "ex-table" });
  lb.appendChild(el("div", { class: "ex-tr ex-th" }, [el("span", {}, "Rank"), el("span", { class: "ex-td-grow" }, "Student"), el("span", {}, "Score"), el("span", {}, "%")]));
  r.leaderboard.forEach((s, i) => {
    lb.appendChild(el("div", { class: "ex-tr" }, [
      el("span", {}, String(i + 1)),
      el("span", { class: "ex-td-grow" }, s.student_name),
      el("span", {}, `${s.score}/${s.max_marks}`),
      el("span", {}, `${s.percentage}%`),
    ]));
  });
  root.appendChild(lb);

  // submissions monitor (who attempted, when)
  root.appendChild(el("h3", { class: "ex-section-title" }, "Submissions"));
  const subs = r.submissions || [];
  if (!subs.length) {
    root.appendChild(el("div", { class: "ex-muted" }, "No submissions yet."));
  } else {
    const tbl = el("div", { class: "ex-table" });
    tbl.appendChild(el("div", { class: "ex-tr ex-th" }, [el("span", { class: "ex-td-grow" }, "Student"), el("span", {}, "Score"), el("span", {}, "%"), el("span", {}, "Submitted")]));
    subs.forEach((s) => {
      tbl.appendChild(el("div", { class: "ex-tr" }, [
        el("span", { class: "ex-td-grow" }, s.student_name),
        el("span", {}, `${s.score}/${s.max_marks}`),
        el("span", {}, `${s.percentage}%`),
        el("span", {}, assess.fmtWhen(s.submitted_at)),
      ]));
    });
    root.appendChild(tbl);
  }
}
