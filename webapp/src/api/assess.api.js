// Assessment + auth API client (Slice 1).
// Wraps /api/auth/* and /api/exams|attempts|analytics with bearer-token auth.
// Token persists in localStorage; the `auth` store slice mirrors the user for UI.

import { request } from "./client.js";

export const AUTH_SLICE = "auth";
const TOKEN_KEY = "qip.auth.token";

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}
export function setToken(t) {
  try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch {}
}
function authHeaders(extra = {}) {
  const t = getToken();
  return t ? { Authorization: "Bearer " + t, ...extra } : { ...extra };
}
const JSON_H = { "Content-Type": "application/json" };

// --- auth ---
export function register(body) {
  return request("/api/auth/register", { method: "POST", headers: JSON_H, body: JSON.stringify(body) });
}
export function login(body) {
  return request("/api/auth/login", { method: "POST", headers: JSON_H, body: JSON.stringify(body) });
}
export function me() {
  return request("/api/auth/me", { headers: authHeaders() });
}

// --- exams / attempts / analytics ---
export function listExams() {
  return request("/api/exams", { headers: authHeaders() });
}
export function getExam(id) {
  return request("/api/exams/" + encodeURIComponent(id), { headers: authHeaders() });
}
export function submitAttempt(id, payload) {
  return request("/api/exams/" + encodeURIComponent(id) + "/attempts",
    { method: "POST", headers: authHeaders(JSON_H), body: JSON.stringify(payload) });
}
export function listAttempts() {
  return request("/api/attempts/me", { headers: authHeaders() });
}
export function getAttempt(id) {
  return request("/api/attempts/" + encodeURIComponent(id), { headers: authHeaders() });
}
export function analytics() {
  return request("/api/analytics/me", { headers: authHeaders() });
}

// --- teacher: exam authoring ---
export function createExam(body) {
  return request("/api/exams", { method: "POST", headers: authHeaders(JSON_H), body: JSON.stringify(body) });
}
export function listMyExams() {
  return request("/api/exams/mine", { headers: authHeaders() });
}
export function setExamStatus(id, status) {
  return request("/api/exams/" + encodeURIComponent(id) + "/status",
    { method: "POST", headers: authHeaders(JSON_H), body: JSON.stringify({ status }) });
}
export function examReport(id) {
  return request("/api/exams/" + encodeURIComponent(id) + "/report", { headers: authHeaders() });
}

// --- scheduling helpers ---
export function epochFromLocal(v) {
  if (!v) return null;
  const t = Date.parse(v);
  return Number.isFinite(t) ? Math.floor(t / 1000) : null;
}
export function fmtWhen(ts) {
  try { return ts ? new Date(ts * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : ""; }
  catch { return ""; }
}
export const PHASE_LABEL = { live: "Live", upcoming: "Upcoming", ended: "Closed", draft: "Draft" };

// --- adaptive ---
export function listStudents() {
  return request("/api/students", { headers: authHeaders() });
}
export function generateAdaptive(body) {
  return request("/api/adaptive/generate", { method: "POST", headers: authHeaders(JSON_H), body: JSON.stringify(body) });
}
// --- theory -> MCQ conversion (Ollama) ---
export function mcqHealth() {
  return request("/api/mcq/health", { headers: authHeaders() });
}
export function generateMcq(body) {
  return request("/api/mcq/generate", { method: "POST", headers: authHeaders(JSON_H), body: JSON.stringify(body) });
}

export function overallReport({ exam_type = "", klass = "" } = {}) {
  const q = [];
  if (exam_type) q.push("exam_type=" + encodeURIComponent(exam_type));
  if (klass) q.push("class=" + encodeURIComponent(klass));
  return request("/api/reports/overall" + (q.length ? "?" + q.join("&") : ""), { headers: authHeaders() });
}

// --- session helpers (mirror auth state into the store slice) ---
export function setSession(store, { token, user }) {
  setToken(token);
  store.setState(AUTH_SLICE, { user });
}
export function clearSession(store) {
  setToken("");
  store.setState(AUTH_SLICE, { user: null });
}
export async function loadSession(store) {
  if (!getToken()) { store.setState(AUTH_SLICE, { user: null }); return null; }
  try {
    const { user } = await me();
    store.setState(AUTH_SLICE, { user });
    return user;
  } catch {
    setToken("");
    store.setState(AUTH_SLICE, { user: null });
    return null;
  }
}

// Auth is deferred for now: ensure a working session without a login screen by
// auto-using demo accounts (login, else register). Real auth/roles replace this.
const DEMO_TEACHER = { name: "Demo Teacher", username: "demo", password: "demo1234", role: "teacher" };
const DEMO_STUDENT = { name: "Demo Student", username: "demostudent", password: "demo1234", role: "student", klass: "10", section: "A" };

async function loginOrRegister(store, acct) {
  setToken("");
  try {
    const { token, user } = await login({ username: acct.username, password: acct.password });
    setSession(store, { token, user });
    return user;
  } catch {
    try {
      const { token, user } = await register(acct);
      setSession(store, { token, user });
      return user;
    } catch {
      store.setState(AUTH_SLICE, { user: null });
      return null;
    }
  }
}

export async function ensureSession(store) {
  if (getToken()) {
    const u = await loadSession(store);
    if (u) return u;
  }
  return loginOrRegister(store, DEMO_TEACHER); // default demo role
}

// Demo-only role switcher (used by the top-bar menu until real auth lands).
export function switchDemo(store, role) {
  return loginOrRegister(store, role === "student" ? DEMO_STUDENT : DEMO_TEACHER);
}
