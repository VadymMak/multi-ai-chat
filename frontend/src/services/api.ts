// src/services/api.ts
import axios, {
  AxiosError,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from "axios";
import { useAuthStore } from "../store/authStore";

const ENV_BASE = import.meta.env.VITE_API_BASE_URL;
if (!ENV_BASE) {
  console.warn(
    "⚠️ VITE_API_BASE_URL is not defined. Falling back to localhost."
  );
}
const baseURL = ENV_BASE || "http://localhost:8000/api";

const api = axios.create({
  baseURL,
  timeout: 180000, // ✅ 2 minute timeout (reduced from 300000 for better error handling)
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
  message: string;
  status: number | null;
  url: string;
  detail?: string;
  isNetworkError?: boolean;
  isTimeout?: boolean;
  original: any;
};

function normalizeAxiosError(err: any): NormalizedAxiosError {
  const ax = err as AxiosError;
  const status = ax.response?.status ?? (ax as any)?.status ?? null;
  const url = ax.config?.url || (ax as any)?.url || "";
  const data = ax.response?.data;

  // Check for network error (no response received)
  const isNetworkError =
    ax.code === "ERR_NETWORK" || (!ax.response && ax.request);

  // Check for timeout error
  const isTimeout =
    ax.code === "ECONNABORTED" || ax.message?.includes("timeout");

  let name = "AxiosError";
  let message = ax.message || "Unknown error";

  if (isNetworkError) {
    name = "NetworkError";
    message = "Network error. Please check your internet connection.";
  } else if (isTimeout) {
    name = "TimeoutError";
    message = "Request timeout. The server is taking too long to respond.";
  }

  const detail =
    (data &&
      typeof (data as any).detail === "string" &&
      (data as any).detail) ||
    (typeof data === "string" ? data.slice(0, 200) : undefined);

  return {
    name,
    message,
    status,
    url,
    detail,
    isNetworkError,
    isTimeout,
    original: err,
  };
}

// ---------- Interceptors ----------

// Request interceptor - добавляем Authorization header
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = useAuthStore.getState().token;

    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    return config;
  },
  (error: AxiosError) => Promise.reject(error)
);

// Response interceptor - обработка ошибок + 401
api.interceptors.response.use(
  (res: AxiosResponse) => {
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
  (err: AxiosError) => {
    const normalized = normalizeAxiosError(err);

    // Обработка 401 Unauthorized - logout и redirect
    if (normalized.status === 401) {
      console.error("[Auth] 401 Unauthorized - logging out");
      useAuthStore.getState().logout();
      window.location.href = "/login";
    }

    return Promise.reject(normalized);
  }
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
