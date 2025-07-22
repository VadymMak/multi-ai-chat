import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import api from "../services/api";

// --- shared types (match backend responses) ---
export type YTItem = {
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

export type SearchParams = {
  query: string;
  max?: number;
  sinceMonths?: number;
  channels?: string | null;
  order?: "relevance" | "date";
  region?: string;
  debug?: boolean;
};

export type YouTubeSummary = {
  videoId: string;
  url: string;
  summary: string;
  bullets: string[];
  chapters: { title: string; time: string }[];
};

// --- internal entry types ---
type SearchEntry = { items: YTItem[]; fetchedAt: number };
type SummaryEntry = { data: YouTubeSummary; fetchedAt: number };

// keys
function searchKey(p: SearchParams): string {
  return [
    p.query.trim(),
    p.max ?? 3,
    p.sinceMonths ?? 24,
    p.channels ?? "",
    p.order ?? "relevance",
    p.region ?? "US",
  ].join("|");
}
const normLang = (lang?: string) => (lang || "en").toLowerCase().split("-")[0];
const summaryKey = (videoId: string, lang?: string) =>
  `${videoId}|${normLang(lang)}`;

const DEFAULT_TTL_SEARCH = 6 * 60 * 60 * 1000; // 6h
const DEFAULT_TTL_SUMMARY = 7 * 24 * 60 * 60 * 1000; // 7d

type State = {
  search: Record<string, SearchEntry>;
  summaries: Record<string, SummaryEntry>;
  ttlSearchMs: number;
  ttlSummaryMs: number;

  // search
  getCachedSearch: (key: string) => YTItem[] | null;
  fetchSearch: (params: SearchParams, force?: boolean) => Promise<YTItem[]>;

  // summaries (LANG-AWARE)
  getCachedSummary: (videoId: string, lang?: string) => YouTubeSummary | null;
  fetchSummary: (
    videoId: string,
    opts?: {
      lang?: string;
      max_chars?: number;
      debug?: boolean;
      force?: boolean;
    }
  ) => Promise<YouTubeSummary>;

  clearAll: () => void;
};

export const useYouTubeStore = create<State>()(
  persist(
    (set, get) => ({
      search: {},
      summaries: {},
      ttlSearchMs: DEFAULT_TTL_SEARCH,
      ttlSummaryMs: DEFAULT_TTL_SUMMARY,

      getCachedSearch: (key) => {
        const e = get().search[key];
        if (!e) return null;
        const fresh = Date.now() - e.fetchedAt < get().ttlSearchMs;
        return fresh ? e.items : null;
        // stale? caller will refetch
      },

      async fetchSearch(params, force = false) {
        const key = searchKey(params);
        if (!force) {
          const cached = get().getCachedSearch(key);
          if (cached) return cached;
        }
        const { data } = await api.get<{ items: YTItem[] }>("/youtube/search", {
          params: {
            query: params.query,
            max: params.max ?? 3,
            sinceMonths: params.sinceMonths ?? 24,
            channels: params.channels ?? undefined,
            order: params.order ?? "relevance",
            region: params.region ?? "US",
            debug: params.debug ?? false,
          },
        });
        set((s) => ({
          search: {
            ...s.search,
            [key]: { items: data.items || [], fetchedAt: Date.now() },
          },
        }));
        return data.items || [];
      },

      // --- language-aware cache lookups ---
      getCachedSummary: (videoId, lang) => {
        const key = summaryKey(videoId, lang);
        const e = get().summaries[key];
        if (!e) return null;
        const fresh = Date.now() - e.fetchedAt < get().ttlSummaryMs;
        return fresh ? e.data : null;
      },

      async fetchSummary(videoId, opts) {
        const lang = normLang(opts?.lang);
        const key = summaryKey(videoId, lang);

        if (!opts?.force) {
          const cached = get().summaries[key];
          if (cached && Date.now() - cached.fetchedAt < get().ttlSummaryMs) {
            return cached.data;
          }
        }

        const { data } = await api.post<YouTubeSummary>("/youtube/summarize", {
          videoId,
          lang, // <- make sure backend honors this
          max_chars: opts?.max_chars ?? 12000,
          debug: !!opts?.debug,
        });

        set((s) => ({
          summaries: {
            ...s.summaries,
            [key]: { data, fetchedAt: Date.now() },
          },
        }));
        return data;
      },

      clearAll: () => set({ search: {}, summaries: {} }),
    }),
    {
      // bump name/version to avoid mixing old (non-lang) cache entries
      name: "yt-cache-v2",
      version: 2,
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({
        search: s.search,
        summaries: s.summaries,
        ttlSearchMs: s.ttlSearchMs,
        ttlSummaryMs: s.ttlSummaryMs,
      }),
    }
  )
);
