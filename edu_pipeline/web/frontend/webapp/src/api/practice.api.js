// Practice Engine + Dashboard API client.
// Wraps /api/practice/* and /api/dashboard with the same bearer-token auth the
// assessment client uses -- token handling is imported rather than duplicated.

import { request, buildQuery } from "./client.js";
import { getToken } from "./assess.api.js";

function authHeaders(extra = {}) {
  const t = getToken();
  return t ? { Authorization: "Bearer " + t, ...extra } : { ...extra };
}
const JSON_H = { "Content-Type": "application/json" };

// --- catalog ---
export function modes() {
  return request("/api/practice/modes", { headers: authHeaders() });
}
export function health() {
  return request("/api/practice/health", { headers: authHeaders() });
}
export function chapters({ book = "", min = 5 } = {}) {
  return request("/api/practice/chapters" + buildQuery({ book, min }), { headers: authHeaders() });
}

// --- sessions ---
export function startSession(body) {
  return request("/api/practice/sessions", {
    method: "POST", headers: authHeaders(JSON_H), body: JSON.stringify(body),
  });
}
export function getSession(id) {
  return request("/api/practice/sessions/" + encodeURIComponent(id), { headers: authHeaders() });
}
export function listSessions() {
  return request("/api/practice/sessions", { headers: authHeaders() });
}
export function answer(id, body) {
  return request("/api/practice/sessions/" + encodeURIComponent(id) + "/answer", {
    method: "POST", headers: authHeaders(JSON_H), body: JSON.stringify(body),
  });
}
export function finish(id) {
  return request("/api/practice/sessions/" + encodeURIComponent(id) + "/finish", {
    method: "POST", headers: authHeaders(JSON_H), body: "{}",
  });
}
export function report(id) {
  return request("/api/practice/sessions/" + encodeURIComponent(id) + "/report", {
    headers: authHeaders(),
  });
}
export function history() {
  return request("/api/practice/history", { headers: authHeaders() });
}

// --- dashboard ---
export function dashboard() {
  return request("/api/dashboard", { headers: authHeaders() });
}
export function setGoal(goal) {
  return request("/api/dashboard/goal", {
    method: "POST", headers: authHeaders(JSON_H), body: JSON.stringify({ goal }),
  });
}
export function startDailyChallenge() {
  return request("/api/practice/daily-challenge", {
    method: "POST", headers: authHeaders(JSON_H), body: "{}",
  });
}

// Seconds -> "3m 20s" / "45s", used by the runner and report views.
export function fmtDuration(sec) {
  const s = Math.max(0, Math.round(sec || 0));
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60);
  return m + "m " + (s % 60) + "s";
}
