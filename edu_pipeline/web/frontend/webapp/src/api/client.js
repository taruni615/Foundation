// Typed fetch client for the Question Bank frontend (Phase 1).
//
// Mirrors the legacy webapp/app.js `api()` convention -- parse JSON or text,
// take the message from `payload.error` -- but normalizes every failure into a
// single `ApiError` shape so callers can branch on `.status` (e.g. 404) and on
// `.retryable` (whether to offer a "Retry" action).
//
// Native ES module: imported by the new bank module, never by the legacy
// non-module app.js.

export const BASE = "";

export class ApiError extends Error {
  constructor(message, { status = 0, retryable = false, payload = null, kind = "http" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;       // HTTP status, or 0 for a network failure
    this.retryable = retryable; // network / 5xx / 429 -> true; other 4xx -> false
    this.payload = payload;     // parsed error body, when present
    this.kind = kind;           // "network" | "http" | "parse"
    this.notFound = status === 404;
  }
}

// Network failures (status 0) and transient server errors are worth retrying;
// deterministic client errors (4xx) are not -- except 429 (rate limited).
function isRetryable(status) {
  return status === 0 || status >= 500 || status === 429;
}

// Serialize a params object into a query string.  Arrays are comma-joined to
// match the backend's `bank_filters_from_qs` (which splits values on commas);
// empty strings, empty arrays, and null/undefined are omitted entirely.
export function buildQuery(params = {}) {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value == null) continue;
    if (Array.isArray(value)) {
      const parts = value.map((v) => String(v).trim()).filter((v) => v !== "");
      if (parts.length) usp.set(key, parts.join(","));
    } else {
      const s = String(value).trim();
      if (s !== "") usp.set(key, s);
    }
  }
  const qs = usp.toString();
  return qs ? "?" + qs : "";
}

export async function request(path, { method = "GET", headers = {}, body, signal } = {}) {
  let res;
  try {
    res = await fetch(BASE + path, { method, headers, body, signal });
  } catch (e) {
    if (e && e.name === "AbortError") throw e; // let callers ignore cancellations
    throw new ApiError(e && e.message ? e.message : "Network error", {
      status: 0,
      retryable: true,
      kind: "network",
    });
  }

  const ct = res.headers.get("content-type") || "";
  let data;
  try {
    data = ct.includes("application/json") ? await res.json() : await res.text();
  } catch (e) {
    throw new ApiError("Malformed server response", {
      status: res.status,
      retryable: isRetryable(res.status),
      kind: "parse",
    });
  }

  if (!res.ok) {
    const msg =
      (data && data.error) ||
      (typeof data === "string" && data) ||
      `Request failed (${res.status})`;
    throw new ApiError(msg, {
      status: res.status,
      retryable: isRetryable(res.status),
      payload: data,
      kind: "http",
    });
  }
  return data;
}

export function get(path, params, opts = {}) {
  return request(path + buildQuery(params), { ...opts, method: "GET" });
}
