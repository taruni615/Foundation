// Top bar (Rizee-style): sidebar toggle, brand, notifications, user chip with a
// role menu (demo role switch + sign out until real auth lands).
import * as assess from "../api/assess.api.js";

function mk(doc, tag, cls, txt) {
  const e = doc.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}

export function createTopbar({ store, doc }) {
  const bar = mk(doc, "header", "app-topbar");

  const burger = mk(doc, "button", "tb-burger", "☰");
  burger.addEventListener("click", () => { const app = doc.getElementById("app"); if (app) app.classList.toggle("nav-collapsed"); });

  const title = mk(doc, "div", "tb-title");
  title.appendChild(mk(doc, "span", "tb-logo", "◆"));
  title.appendChild(mk(doc, "span", "tb-name", "IIT Foundation"));

  const spacer = mk(doc, "div", "tb-spacer");
  const bell = mk(doc, "button", "tb-bell", "🔔");

  // user chip + dropdown menu
  const userWrap = mk(doc, "div", "tb-user");
  const userName = mk(doc, "span", "tb-username", "Guest");
  userWrap.appendChild(mk(doc, "span", "tb-avatar", "◍"));
  userWrap.appendChild(userName);
  userWrap.appendChild(mk(doc, "span", "tb-caret", "▾"));

  const menu = mk(doc, "div", "tb-menu");
  menu.hidden = true;

  const reload = () => { if (typeof location !== "undefined" && location.reload) location.reload(); };
  function buildMenu() {
    menu.innerHTML = "";
    const a = store.getState("auth");
    const role = (a && a.user && a.user.role) || "—";
    menu.appendChild(mk(doc, "div", "tb-menu-head", `Signed in as ${(a && a.user && (a.user.name || a.user.username)) || "Guest"} (${role})`));
    const toStudent = mk(doc, "button", "tb-menu-item", "Switch to Student");
    toStudent.addEventListener("click", async () => { await assess.switchDemo(store, "student"); reload(); });
    const toTeacher = mk(doc, "button", "tb-menu-item", "Switch to Teacher");
    toTeacher.addEventListener("click", async () => { await assess.switchDemo(store, "teacher"); reload(); });
    if (role !== "student") menu.appendChild(toStudent);
    if (role !== "teacher") menu.appendChild(toTeacher);
    const out = mk(doc, "button", "tb-menu-item tb-menu-danger", "Sign out");
    out.addEventListener("click", () => { assess.clearSession(store); reload(); });
    menu.appendChild(out);
  }
  userWrap.addEventListener("click", () => { buildMenu(); menu.hidden = !menu.hidden; });

  const userBox = mk(doc, "div", "tb-userbox");
  userBox.appendChild(userWrap);
  userBox.appendChild(menu);

  bar.appendChild(burger);
  bar.appendChild(title);
  bar.appendChild(spacer);
  bar.appendChild(bell);
  bar.appendChild(userBox);

  const setUser = () => {
    const a = store.getState("auth");
    userName.textContent = (a && a.user && (a.user.name || a.user.username)) || "Guest";
  };
  setUser();
  store.subscribe("auth", setUser);

  return bar;
}
