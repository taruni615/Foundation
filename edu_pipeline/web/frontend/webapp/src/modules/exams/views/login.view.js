// Login / Register view (Slice 1).
import { el, clear } from "../../../ui/el.js";
import * as assess from "../../../api/assess.api.js";

export function renderLogin(node, { store, navigate, next }) {
  let mode = "login"; // login | register
  const root = el("div", { class: "ex-auth" });
  clear(node);
  node.appendChild(root);

  function field(label, attrs) {
    const input = el("input", { class: "ex-input", ...attrs });
    return { wrap: el("label", { class: "ex-field" }, [el("span", {}, label), input]), input };
  }

  function render() {
    clear(root);
    const isLogin = mode === "login";
    const name = field("Full name", { type: "text", placeholder: "Asha Rao" });
    const roll = field("Roll no. (optional)", { type: "text", placeholder: "NEET-001" });
    const username = field("Username", { type: "text", placeholder: "asha" });
    const password = field("Password", { type: "password", placeholder: "••••••" });
    const roleSel = el("select", { class: "ex-input" }, [
      el("option", { value: "student" }, "Student"),
      el("option", { value: "teacher" }, "Teacher"),
    ]);
    const roleWrap = el("label", { class: "ex-field" }, [el("span", {}, "I am a"), roleSel]);
    const classSel = el("select", { class: "ex-input" }, [el("option", { value: "" }, "—"), ...["6", "7", "8", "9", "10"].map((c) => el("option", { value: c }, "Class " + c))]);
    const sectionInp = el("input", { class: "ex-input", type: "text", placeholder: "A" });
    const classWrap = el("label", { class: "ex-field" }, [el("span", {}, "Class"), classSel]);
    const sectionWrap = el("label", { class: "ex-field" }, [el("span", {}, "Section (optional)"), sectionInp]);
    const studentExtras = el("div", {}, [classWrap, sectionWrap]);
    const syncExtras = () => { studentExtras.hidden = roleSel.value !== "student"; };
    roleSel.addEventListener("change", syncExtras);
    syncExtras();
    const err = el("div", { class: "ex-auth-err" });

    const submit = el("button", { class: "ex-btn ex-btn-primary ex-btn-block" }, isLogin ? "Sign in" : "Create account");
    submit.addEventListener("click", async () => {
      err.textContent = "";
      submit.disabled = true;
      try {
        const payload = isLogin
          ? { username: username.input.value.trim(), password: password.input.value }
          : { name: name.input.value.trim(), roll: roll.input.value.trim(), role: roleSel.value,
              klass: classSel.value, section: sectionInp.value.trim(),
              username: username.input.value.trim(), password: password.input.value };
        const fn = isLogin ? assess.login : assess.register;
        const { token, user } = await fn(payload);
        assess.setSession(store, { token, user });
        navigate(next || "/exams");
      } catch (e) {
        err.textContent = e.message || "Something went wrong.";
        submit.disabled = false;
      }
    });

    const toggle = el("button", { class: "ex-link" }, isLogin ? "New here? Create an account" : "Have an account? Sign in");
    toggle.addEventListener("click", () => { mode = isLogin ? "register" : "login"; render(); });

    root.appendChild(
      el("div", { class: "ex-auth-card" }, [
        el("div", { class: "ex-auth-head" }, [
          el("div", { class: "ex-auth-logo" }, "◆"),
          el("h2", {}, isLogin ? "Student sign in" : "Create student account"),
          el("p", { class: "ex-muted" }, "Take hosted tests and track your performance."),
        ]),
        ...(isLogin ? [] : [name.wrap, roll.wrap, roleWrap, studentExtras]),
        username.wrap,
        password.wrap,
        err,
        submit,
        toggle,
      ])
    );
  }

  render();
}
