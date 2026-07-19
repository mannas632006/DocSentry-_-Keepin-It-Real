/* API client.
 *
 * The base URL is resolved at runtime rather than baked in at build time: the
 * dashboard is deployed to Vercel before the Render API URL is necessarily
 * known, and a user should be able to repoint it without a rebuild.
 *
 * Order: localStorage override > VITE_API_URL at build > same origin (when the
 * API serves the built dashboard itself) > localhost for dev.
 */

const LS_API = "docsentry.apiUrl";
const LS_TOKEN = "docsentry.adminToken";

function defaultBase() {
  const built = import.meta.env.VITE_API_URL;
  if (built) return built.replace(/\/$/, "");
  // Served by FastAPI's StaticFiles mount: the API is this same origin.
  if (typeof window !== "undefined" && !import.meta.env.DEV) return window.location.origin;
  return "http://localhost:8000";
}

export function getApiBase() {
  const stored = localStorage.getItem(LS_API);
  return (stored || defaultBase()).replace(/\/$/, "");
}

export function setApiBase(url) {
  const clean = (url || "").trim().replace(/\/$/, "");
  if (clean) localStorage.setItem(LS_API, clean);
  else localStorage.removeItem(LS_API);
}

export function getToken() {
  return localStorage.getItem(LS_TOKEN) || "";
}

export function setToken(token) {
  if (token) localStorage.setItem(LS_TOKEN, token);
  else localStorage.removeItem(LS_TOKEN);
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = "GET", body, signal } = {}) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers["X-Admin-Token"] = token;

  let res;
  try {
    res = await fetch(`${getApiBase()}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    // fetch rejects on DNS/CORS/offline, all of which look identical here.
    throw new ApiError(
      `Cannot reach the API at ${getApiBase()}. Is it running, and does its ` +
      `cors_origins allow this page?`,
      0,
    );
  }

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (data.detail) {
        detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      /* non-JSON error body; the status line is all we have */
    }
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return null;
  return res.json();
}

const qs = (params) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== "" && v != null) p.set(k, v);
  }
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  health: (signal) => request("/health", { signal }),
  config: (signal) => request("/api/config", { signal }),
  stats: (signal) => request("/api/stats", { signal }),
  runs: (params, signal) => request(`/api/runs${qs(params)}`, { signal }),
  run: (id, signal) => request(`/api/runs/${id}`, { signal }),
  analyze: (body) => request("/api/analyze", { method: "POST", body }),
  clearRuns: () => request("/api/runs", { method: "DELETE" }),
};
