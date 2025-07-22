// src/services/api.ts
import axios, { AxiosError, AxiosResponse } from "axios";

const ENV_BASE = process.env.REACT_APP_API_BASE_URL;
if (!ENV_BASE) {
  console.warn(
    "⚠️ REACT_APP_API_BASE_URL is not defined. Falling back to localhost."
  );
}
const baseURL = ENV_BASE || "http://localhost:8000/api";
console.debug("🌍 Axios baseURL:", baseURL);

const api = axios.create({
  baseURL,
  timeout: 300000,
  withCredentials: false,
  headers: { Accept: "application/json" },
});

// ---------- Helpers ----------
function looksLikeHtml(res: AxiosResponse): boolean {
  const ct = String(res.headers?.["content-type"] || "").toLowerCase();
  if (ct.includes("text/html")) return true;
  const body = res.data;
  if (typeof body === "string") {
    const t = body.trim().slice(0, 64).toLowerCase();
    if (t.startsWith("<!doctype") || t.startsWith("<html")) return true;
  }
  return false;
}

function normalizeAxiosError(err: any) {
  const ax = err as AxiosError;
  const status = ax.response?.status ?? (ax as any)?.status ?? null;
  const url = ax.config?.url || (ax as any)?.url || "";
  const data = ax.response?.data;
  const detail =
    (data &&
      typeof (data as any).detail === "string" &&
      (data as any).detail) ||
    (typeof data === "string"
      ? data.slice(0, 200)
      : ax.message || "Unknown error");
  return { name: "AxiosError", status, url, detail, original: err };
}

// ---------- Interceptors ----------
api.interceptors.response.use(
  (res) => {
    if (looksLikeHtml(res)) {
      const preview =
        typeof res.data === "string"
          ? res.data.trim().slice(0, 200)
          : String(res.data);
      return Promise.reject({
        name: "NonJsonResponseError",
        message: "Non-JSON response from backend (likely an HTML debug page).",
        status: res.status,
        url: res.config?.url,
        dataPreview: preview,
      });
    }
    return res;
  },
  (err) => Promise.reject(normalizeAxiosError(err))
);

export default api;
