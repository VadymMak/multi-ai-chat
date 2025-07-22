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
  timeout: 120000, // ✅ 2 minute timeout (reduced from 300000 for better error handling)
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

export type NormalizedAxiosError = {
  name: string;
  status: number | null;
  url: string;
  detail: string;
  original: any;
};

function normalizeAxiosError(err: any): NormalizedAxiosError {
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

// ===================================================================
//                          YOUTUBE TYPES
// ===================================================================
export type YouTubeVideo = {
  title: string;
  videoId: string;
  url: string;
  channelTitle: string;
  channelId: string;
  publishedAt: string;
  description: string;
  duration: string;
  viewCount: number;
  isLive: boolean;
};

export type YouTubeSearchResponse = {
  items: YouTubeVideo[];
};

export type YouTubeChapter = { title: string; time: string };
export type YouTubeSummaryResponse = {
  videoId: string;
  url: string;
  summary: string;
  bullets: string[];
  chapters: YouTubeChapter[];
};

// ===================================================================
//                       YOUTUBE API HELPERS
// ===================================================================

/** GET /youtube/search */
export async function youtubeSearch(opts: {
  query: string;
  max?: number;
  sinceMonths?: number;
  channels?: string;
  order?: "relevance" | "date";
  region?: string;
  debug?: boolean;
}): Promise<YouTubeSearchResponse> {
  const params = {
    query: opts.query,
    max: opts.max ?? 3,
    sinceMonths: opts.sinceMonths ?? 24,
    channels: opts.channels || undefined,
    order: opts.order ?? "relevance",
    region: opts.region ?? "US",
    debug: opts.debug ? 1 : 0,
  };
  const res = await api.get<YouTubeSearchResponse>("/youtube/search", {
    params,
  });
  return res.data;
}

/** POST /youtube/summarize */
export async function summarizeYouTube(payload: {
  videoId?: string;
  url?: string;
  lang?: string;
  max_chars?: number;
  model_key?: string | null;
  debug?: boolean;
}): Promise<YouTubeSummaryResponse> {
  const body = {
    videoId: payload.videoId ?? null,
    url: payload.url ?? null,
    lang: payload.lang ?? "en",
    max_chars: payload.max_chars ?? 12000,
    model_key: payload.model_key ?? null,
    debug: !!payload.debug,
  };
  const res = await api.post<YouTubeSummaryResponse>(
    "/youtube/summarize",
    body
  );
  return res.data;
}

export default api;
