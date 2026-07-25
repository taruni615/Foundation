// Side navigation (Rizee-style): brand, ordered sections, expandable parent
// groups with sub-items, per-item icons, and ROLE-AWARE filtering.
//
// Module nav metadata (all optional):
//   navSection / navParent / navIcon / navOrder / navHidden
//   roles  array of roles allowed to see the item; omitted = everyone

const SECTION_ORDER = ["Menu", "Academics", "Content"];
const PARENT_ICONS = { "Online Exams": "📝" };

function mk(doc, tag, cls, txt) {
  const e = doc.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
}
function leaf(doc, it, cls) {
  const a = doc.createElement("a");
  a.className = cls;
  a.href = "#" + it.pattern;
  a.dataset.module = it.id;
  a.appendChild(mk(doc, "span", "nav-ic", it.icon));
  a.appendChild(mk(doc, "span", "nav-txt", it.label));
  return a;
}

export function renderSidenav({ nav, registry, store }) {
  if (!nav) return;
  const doc = nav.ownerDocument;
  let currentActive = null;

  const roleOf = () => {
    const a = store && store.getState && store.getState("auth");
    return (a && a.user && a.user.role) || null;
  };
  const roleOk = (m, role) => {
    if (!m.roles || !m.roles.length) return true; // visible to everyone
    if (!role) return true;                        // role unknown yet -> show
    return m.roles.includes(role);
  };

  function build() {
    const role = roleOf();
    const items = registry.list().filter((m) => !m.navHidden && roleOk(m, role)).map((m) => ({
      id: m.id, label: m.label || m.id, pattern: m.pattern,
      section: m.navSection || m.navGroup || "Other",
      parent: m.navParent || null, icon: m.navIcon || "•",
      order: m.navOrder == null ? 100 : m.navOrder,
    }));

    const sections = [];
    for (const it of items) if (!sections.includes(it.section)) sections.push(it.section);
    sections.sort((a, b) => {
      const ia = SECTION_ORDER.indexOf(a), ib = SECTION_ORDER.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });

    nav.innerHTML = "";
    const brand = mk(doc, "div", "nav-brand");
    brand.appendChild(mk(doc, "span", "nav-brand-mark", "◆"));
    brand.appendChild(mk(doc, "span", "nav-brand-word", "IIT Foundation"));
    nav.appendChild(brand);

    for (const section of sections) {
      const secItems = items.filter((i) => i.section === section).sort((a, b) => a.order - b.order);
      const secEl = mk(doc, "div", "nav-group");
      secEl.appendChild(mk(doc, "div", "nav-group-title", section.toUpperCase()));
      const groups = {};
      for (const it of secItems) {
        if (it.parent) {
          let g = groups[it.parent];
          if (!g) {
            g = mk(doc, "div", "nav-parent-group");
            const head = mk(doc, "button", "nav-parent");
            head.appendChild(mk(doc, "span", "nav-ic", PARENT_ICONS[it.parent] || "📁"));
            head.appendChild(mk(doc, "span", "nav-parent-label", it.parent));
            head.appendChild(mk(doc, "span", "nav-chev", "▾"));
            head.addEventListener("click", () => g.classList.toggle("collapsed"));
            const kids = mk(doc, "div", "nav-children");
            g._kids = kids;
            g.appendChild(head);
            g.appendChild(kids);
            groups[it.parent] = g;
            secEl.appendChild(g);
          }
          g._kids.appendChild(leaf(doc, it, "nav-sub"));
        } else {
          secEl.appendChild(leaf(doc, it, "nav-item"));
        }
      }
      nav.appendChild(secEl);
    }
    applyActive(currentActive);
  }

  function applyActive(active) {
    currentActive = active;
    const links = [...nav.querySelectorAll(".nav-item"), ...nav.querySelectorAll(".nav-sub")];
    links.forEach((a) => {
      const on = a.dataset.module === active;
      a.classList.toggle("active", on);
      if (on) {
        let p = a.parentNode;
        while (p) { if (p.classList && p.classList.contains("nav-parent-group")) { p.classList.remove("collapsed"); break; } p = p.parentNode; }
      }
    });
  }

  build();
  if (store) {
    store.subscribe("shell", (s) => applyActive(s && s.module));
    store.subscribe("auth", () => build()); // re-filter nav when the user/role changes
  }
}
