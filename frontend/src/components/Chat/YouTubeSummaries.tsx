// File: src/components/Chat/YouTubeSummaries.tsx
import React from "react";
import type { LooseSource } from "../Attachments/SourceList";
import { summarizeVideo } from "../../api/youtube";

type Props = { items: LooseSource[] };

function extractVideoId(url: string): string | null {
  try {
    const u = new URL(url);
    if (u.hostname.includes("youtu.be")) {
      const id = u.pathname.replace("/", "");
      return id && id.length >= 11 ? id.substring(0, 11) : null;
    }
    if (u.pathname.startsWith("/shorts/")) {
      const id = u.pathname.split("/shorts/")[1]?.split("/")[0] || "";
      return id && id.length >= 11 ? id.substring(0, 11) : null;
    }
    const id = u.searchParams.get("v") || "";
    return id && id.length >= 11 ? id.substring(0, 11) : null;
  } catch {
    const m = (url || "").match(/[A-Za-z0-9_-]{11}/);
    return m ? m[0] : null;
  }
}

type SummaryState = {
  loading: boolean;
  error?: string;
  data?: {
    summary: string;
    bullets: string[];
    chapters: { title: string; time: string }[];
  };
};

const YouTubeSummaries: React.FC<Props> = ({ items }) => {
  const [state, setState] = React.useState<Record<string, SummaryState>>({});

  const doSummarize = async (url: string) => {
    const vid = extractVideoId(url);
    if (!vid) return;

    setState((s) => ({ ...s, [vid]: { loading: true } }));
    try {
      const data = await summarizeVideo(url);
      setState((s) => ({
        ...s,
        [vid]: {
          loading: false,
          data: {
            summary: data.summary,
            bullets: data.bullets || [],
            chapters: data.chapters || [],
          },
        },
      }));
    } catch (e: any) {
      setState((s) => ({
        ...s,
        [vid]: { loading: false, error: e?.message || "Failed to summarize" },
      }));
    }
  };

  if (!items?.length) return null;

  return (
    <div className="mt-2 space-y-3">
      <div className="text-xs font-medium text-gray-500">YouTube tools</div>
      <div className="grid gap-2">
        {items.slice(0, 6).map((it) => {
          const vid = extractVideoId(it.url || "");
          const st = vid ? state[vid] : undefined;
          return (
            <div
              key={it.url}
              className="rounded-lg border bg-white/70 p-3 shadow-sm"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate font-medium">
                    {it.title || it.url}
                  </div>
                  <div className="truncate text-xs text-gray-500">{it.url}</div>
                </div>
                <button
                  onClick={() => doSummarize(it.url!)}
                  disabled={!!st?.loading}
                  className="shrink-0 rounded-md border px-2 py-1 text-xs hover:bg-white disabled:opacity-60"
                  title="Summarize this video"
                >
                  {st?.loading ? "Summarizing…" : "Summarize"}
                </button>
              </div>

              {st?.error && (
                <div className="mt-2 rounded bg-red-50 p-2 text-xs text-red-700">
                  {st.error}
                </div>
              )}

              {st?.data && (
                <div className="mt-3 space-y-2">
                  <div className="text-sm">{st.data.summary}</div>
                  {st.data.bullets?.length > 0 && (
                    <ul className="ml-4 list-disc text-sm">
                      {st.data.bullets.slice(0, 8).map((b, i) => (
                        <li key={i}>{b}</li>
                      ))}
                    </ul>
                  )}
                  {st.data.chapters?.length > 0 && (
                    <div className="pt-1">
                      <div className="text-xs font-medium text-gray-600">
                        Chapters
                      </div>
                      <div className="flex flex-wrap gap-2 pt-1">
                        {st.data.chapters.slice(0, 12).map((c, i) => (
                          <span
                            key={i}
                            className="rounded-full border px-2 py-0.5 text-xs"
                            title={c.title}
                          >
                            {c.time} — {c.title}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default YouTubeSummaries;
