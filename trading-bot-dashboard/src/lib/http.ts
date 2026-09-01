import axios, { AxiosError } from "axios";
import { AUTH_TOKEN_KEY } from "../apis/auth/auth.api";

export type ApiError = {
  message: string;
  status?: number;
  data?: unknown;
};

// Production: same-origin `/api` (nginx proxies to uvicorn, default 127.0.0.1:6000). Never expose raw API port in browser.
const DEFAULT_API_BASE = "/api";

/** Old builds baked `http://host:8000` or `:6000` — rewrite to same host `/api` so nginx proxy works. */
function normalizeApiBase(raw: string): string {
  const s = raw.trim() || DEFAULT_API_BASE;
  if (!/:8000\/?$/.test(s) && !/:6000\/?$/.test(s)) return s;
  const withoutPort = s.replace(/:(8000|6000)\/?$/, "").replace(/\/$/, "");
  return `${withoutPort}/api`;
}

/**
 * True when env points at a machine-local API (nginx on :80, uvicorn, LAN IP).
 * In that case we must NOT use it in dev — browser Origin (127.0.0.1 vs localhost vs 192.168.x.x)
 * must match the API host or you get CORS. Relative `/api` + Vite proxy fixes all cases.
 */
function isLocalApiUrl(url: string): boolean {
  try {
    const u = new URL(url);
    const h = u.hostname.toLowerCase();
    if (h === "localhost" || h === "127.0.0.1") return true;
    if (h.startsWith("192.168.") || h.startsWith("10.")) return true;
    if (h.startsWith("172.")) {
      const p = h.split(".").map(Number);
      if (p[0] === 172 && p[1] >= 16 && p[1] <= 31) return true;
    }
    return false;
  } catch {
    return false;
  }
}

/**
 * Resolve axios baseURL:
 * - `/api` — relative: Vite dev proxy → backend :6000 (same origin as UI → no CORS).
 * - Full remote URL — production / explicit remote API in dev.
 */
function resolveApiBase(): string {
  const raw = String(import.meta.env.VITE_API_BASE_URL ?? "").trim();
  if (raw.startsWith("/")) {
    return raw;
  }
  if (import.meta.env.DEV) {
    if (!raw || isLocalApiUrl(raw)) {
      return "/api";
    }
  }
  return normalizeApiBase(raw || DEFAULT_API_BASE);
}

const API_BASE = resolveApiBase();

export const http = axios.create({
  baseURL: API_BASE,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export function toApiError(err: unknown): ApiError {
  if (axios.isAxiosError(err)) {
    const e = err as AxiosError<any>;
    const status = e.response?.status;
    const data = e.response?.data;

    let message = e.message || "Request failed";

    if (typeof data === "string") message = data;
    else if (typeof data?.detail === "string") message = data.detail;
    else if (Array.isArray(data?.detail)) {
      message =
        data.detail
          .map((x: any) => x?.msg)
          .filter(Boolean)
          .join("\n") || message;
    } else if (typeof data?.message === "string") message = data.message;

    return { message, status, data };
  }

  return { message: (err as any)?.message || "Unknown error" };
}
