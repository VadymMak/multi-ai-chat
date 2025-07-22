// File: src/components/Chat/YouTubeMessages.tsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "../../types/chat";
import SourceList, { LooseSource } from "../Attachments/SourceList";
import {
  useYouTubeStore,
  type YouTubeSummary as StoreYouTubeSummary,
} from "../../store/youtubeStore";

/* ---------- UI config ---------- */
const SUMMARIZE_TOP_N = 3 as const;

/* ---------- Types (component-local) ---------- */
type Props = { message: ChatMessage };

type LocalSumm = Record<
  string,
  { loading: boolean; data?: StoreYouTubeSummary; error?: string }
>;

/* ---------- Regex ---------- */
const mdLink = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/i;
const bareUrl = /(https?:\/\/[^\s)]+)$/i;

/* ---------- URL/ID helpers ---------- */
function extractVideoId(url: string): string | null {
  try {
    const u = new URL(url);
    if (u.hostname.includes("youtu.be")) {
      const id = u.pathname.replace("/", "");
      return id && id.length >= 11 ? id.substring(0, 11) : null;
    }
    if ((u.pathname || "").startsWith("/shorts/")) {
      const id = u.pathname.split("/shorts/")[1]?.split("/")[0] || "";
      return id && id.length >= 11 ? id.substring(0, 11) : null;
    }
    const id = u.searchParams.get("v") || "";
    return id && id.length >= 11 ? id.substring(0, 11) : null;
  } catch {
    const m = url.match(/[A-Za-z0-9_-]{11}/);
    return m ? m[0] : null;
  }
}
function canonYouTubeUrl(input: string): string {
  const v = extractVideoId(input);
  return v ? `https://www.youtube.com/watch?v=${v}` : input.trim();
}

/* ---------- Parsing helpers ---------- */
function parseLineToSource(
  line: string
): (LooseSource & { videoId?: string }) | null {
  const s = line.trim().replace(/^[-*•]\s+/, "");
  const m = s.match(mdLink);
  if (m) {
    const url = canonYouTubeUrl(m[2]);
    return { title: m[1], url, videoId: extractVideoId(url) || undefined };
  }
  const u = s.match(bareUrl);
  if (u) {
    const url = canonYouTubeUrl(u[1]);
    return { title: url, url, videoId: extractVideoId(url) || undefined };
  }
  // Support `"Title" - URL` form
  const dash = s.split(" - ");
  if (dash.length >= 2) {
    const maybeUrl = dash[dash.length - 1].trim();
    if (bareUrl.test(maybeUrl)) {
      const url = canonYouTubeUrl(maybeUrl);
      const title =
        dash
          .slice(0, -1)
          .join(" - ")
          .replace(/^"+|"+$/g, "")
          .trim() || url;
      return { title, url, videoId: extractVideoId(url) || undefined };
    }
  }
  return null;
}

/** Normalize many shapes to LooseSource (+ optional extras). */
function toLooseSource(
  v: unknown
): (LooseSource & { videoId?: string; channelTitle?: string }) | null {
  if (!v) return null;

  if (typeof v === "string") {
    return parseLineToSource(v);
  }

  const o = v as Record<string, unknown>;
  const rawTitle =
    (typeof o.title === "string" && o.title) ||
    (typeof o.name === "string" && o.name) ||
    "";
  const rawUrl =
    (typeof o.url === "string" && o.url) ||
    (typeof (o as any).link === "string" && (o as any).link) ||
    (typeof (o as any).videoId === "string" &&
      `https://www.youtube.com/watch?v=${(o as any).videoId}`) ||
    "";
  const url = canonYouTubeUrl(String(rawUrl || "").trim());
  if (!url) return null;

  const title = (rawTitle || url).toString().trim();
  const videoId = extractVideoId(url) || undefined;
  const snippet =
    (typeof (o as any).description === "string" && (o as any).description) ||
    (typeof (o as any).snippet === "string" && (o as any).snippet) ||
    undefined;
  const channelTitle =
    (typeof (o as any).channelTitle === "string" && (o as any).channelTitle) ||
    undefined;

  return { title, url, snippet, videoId, channelTitle };
}

/** Dedupe by videoId, then URL. */
function uniqYT(
  items: Array<LooseSource & { videoId?: string }>
): LooseSource[] {
  const seenIds = new Set<string>();
  const seenUrls = new Set<string>();
  const out: LooseSource[] = [];
  for (const it of items) {
    const id = (it.videoId || "").trim().toLowerCase();
    const url = (it.url || "").trim().toLowerCase();
    if (id) {
      if (seenIds.has(id)) continue;
      seenIds.add(id);
    } else {
      if (!url || seenUrls.has(url)) continue;
      seenUrls.add(url);
    }
    out.push({ title: it.title, url: it.url, snippet: it.snippet });
  }
  return out;
}

/* ---------- Naive language detection ---------- */
function shortUILang(): string {
  try {
    const nav = (typeof navigator !== "undefined" && navigator) as
      | Navigator
      | undefined;
    const l = (nav?.language || nav?.languages?.[0] || "en")
      .toLowerCase()
      .split("-")[0];
    return l || "en";
  } catch {
    return "en";
  }
}

function detectLangFromMessage(msg: ChatMessage): string | null {
  const parts: string[] = [];
  if (msg.text) parts.push(msg.text);
  const youtube = ((msg as any)?.sources?.youtube ??
    (msg as any)?.youtube) as unknown[];
  if (Array.isArray(youtube)) {
    for (const it of youtube) {
      const t =
        (it as any)?.title ||
        (it as any)?.name ||
        (typeof it === "string" ? it : "");
      if (t) parts.push(String(t));
    }
  }
  const blob = parts.join(" ");
  // Cyrillic (Russian, Ukrainian, etc.) → return "ru"
  if (/[А-Яа-яЁё]/.test(blob)) return "ru";
  return null; // unknown
}

/* ---------- Component ---------- */
const YouTubeMessages: React.FC<Props> = ({ message }) => {
  const yt = useYouTubeStore();
  const [summ, setSumm] = useState<LocalSumm>({});
  const controllers = useRef<Record<string, AbortController>>({});

  // Parse items from message (prefer structured)
  const items = useMemo<LooseSource[]>(() => {
    const structured =
      ((message as any)?.sources?.youtube as unknown[]) ||
      ((message as any)?.youtube as unknown[]) ||
      [];

    if (Array.isArray(structured) && structured.length) {
      return uniqYT(
        structured
          .map(toLooseSource)
          .filter(
            (x): x is LooseSource & { videoId?: string } =>
              !!x && (!!x.title || !!x.url)
          )
      );
    }

    const lines =
      message.text
        ?.split("\n")
        .map((l) => l.trim())
        .filter(Boolean) || [];

    return uniqYT(
      lines
        .map(parseLineToSource)
        .filter((x): x is LooseSource & { videoId?: string } => !!x && !!x.url)
    );
  }, [message]);

  // Preferred summary language (message-driven → browser UI fallback)
  const targetLang = useMemo(() => {
    return detectLangFromMessage(message) || shortUILang();
  }, [message]);

  // Clean old cache on mount (placeholder)
  useEffect(() => {
    // yt.purgeOld && yt.purgeOld();
  }, [yt]);

  async function fetchSummary(videoId: string) {
    // Use persisted cache first (language-aware if your store supports it)
    const cached =
      (yt as any).getCachedSummary?.(videoId, targetLang) ??
      yt.getCachedSummary(videoId);
    if (cached) {
      setSumm((m) => ({ ...m, [videoId]: { loading: false, data: cached } }));
      return;
    }

    // Cancel any in-flight for this id (note: store fetch currently doesn't accept signal)
    controllers.current[videoId]?.abort();
    const ctl = new AbortController();
    controllers.current[videoId] = ctl;

    setSumm((m) => ({ ...m, [videoId]: { loading: true } }));
    try {
      const data = await yt.fetchSummary(videoId, {
        lang: targetLang, // ← dynamic language
        max_chars: 12000,
        debug: false,
        force: false,
        // signal: ctl.signal, // enable if your api wrapper supports AbortController
      });
      setSumm((m) => ({ ...m, [videoId]: { loading: false, data } }));
    } catch (e: unknown) {
      const msg =
        (e as any)?.response?.data?.detail ||
        (e as Error)?.message ||
        "Failed to summarize";
      setSumm((m) => ({
        ...m,
        [videoId]: { loading: false, error: String(msg) },
      }));
    } finally {
      delete controllers.current[videoId];
    }
  }

  function cancelSummary(videoId: string) {
    controllers.current[videoId]?.abort();
  }

  async function summarizeTopN() {
    const vids = items
      .slice(0, SUMMARIZE_TOP_N)
      .map((it) => extractVideoId(it.url || "") || "")
      .filter((v) => v.length > 0); // avoid TS predicate for Babel compat

    for (const vid of vids) {
      if (summ[vid]?.data && !summ[vid]?.error) continue;
      await fetchSummary(vid);
    }
  }

  function copyBullets(videoId: string) {
    const b = summ[videoId]?.data?.bullets || [];
    if (!b.length) return;
    const txt = b.map((x: string) => `• ${x}`).join("\n");
    navigator.clipboard?.writeText(txt).catch(() => {});
  }

  if (!items.length) return null;

  return (
    <div className="space-y-2">
      {/* Primary list of YouTube links/cards */}
      <SourceList tone="youtube" items={items} />

      {/* Bulk action */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={summarizeTopN}
          className="text-xs px-2 py-1 rounded border bg-white/80 hover:bg-white transition"
          title={`Summarize top ${SUMMARIZE_TOP_N}`}
          type="button"
        >
          Summarize top {SUMMARIZE_TOP_N}
        </button>
      </div>

      {/* Inline summaries for the first N items */}
      {items.slice(0, SUMMARIZE_TOP_N).map((it, i) => {
        const vid = extractVideoId(it.url || "") || undefined;
        if (!vid) return null;
        const state = summ[vid];

        return (
          <div
            key={`sum-${vid}`}
            className="mt-1 rounded-md border bg-white/70 p-3"
            aria-busy={!!state?.loading}
            aria-live="polite"
          >
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold">
                {i + 1}. {it.title || it.url}
              </div>
              <div className="flex gap-1">
                {state?.loading ? (
                  <button
                    onClick={() => cancelSummary(vid)}
                    className="text-[11px] px-2 py-0.5 rounded border"
                    title="Cancel"
                    type="button"
                  >
                    Cancel
                  </button>
                ) : (
                  <button
                    onClick={() => fetchSummary(vid)}
                    className="text-[11px] px-2 py-0.5 rounded border"
                    title="Summarize this video"
                    type="button"
                  >
                    {state?.data ? "Refresh" : "Summarize"}
                  </button>
                )}
                {state?.data?.bullets?.length ? (
                  <button
                    onClick={() => copyBullets(vid)}
                    className="text-[11px] px-2 py-0.5 rounded border"
                    title="Copy bullets"
                    type="button"
                  >
                    Copy bullets
                  </button>
                ) : null}
                {state?.data?.url ? (
                  <a
                    href={state.data.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[11px] px-2 py-0.5 rounded border"
                    title="Open video"
                  >
                    Open ↗
                  </a>
                ) : null}
              </div>
            </div>

            {/* Content */}
            {state?.error ? (
              <div className="mt-2 text-xs text-red-600">⚠ {state.error}</div>
            ) : state?.loading ? (
              <div className="mt-2 animate-pulse space-y-2">
                <div className="h-3 rounded bg-gray-200" />
                <div className="h-3 rounded bg-gray-200 w-11/12" />
                <div className="h-3 rounded bg-gray-200 w-10/12" />
              </div>
            ) : state?.data ? (
              <>
                <p className="mt-2 text-sm">{state.data.summary}</p>
                {state.data.bullets?.length > 0 && (
                  <ul className="list-disc ml-5 mt-2 text-sm">
                    {state.data.bullets.map((b: string, idx: number) => (
                      <li key={idx}>{b}</li>
                    ))}
                  </ul>
                )}
                {state.data.chapters?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {state.data.chapters.map(
                      (c: { title: string; time: string }, idx: number) => (
                        <span
                          key={idx}
                          className="text-[11px] px-2 py-0.5 rounded-full border bg-white"
                          title={c.title}
                        >
                          {c.time} — {c.title}
                        </span>
                      )
                    )}
                  </div>
                )}
              </>
            ) : (
              <div className="mt-2 text-[11px] text-gray-600">
                Click “Summarize” to fetch a short abstract and bullets.
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default YouTubeMessages;
