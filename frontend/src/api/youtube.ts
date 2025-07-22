// File: src/api/youtube.ts
export type YouTubeSummary = {
  videoId: string;
  url: string;
  summary: string;
  bullets: string[];
  chapters: { title: string; time: string }[];
};

function extractVideoId(urlOrId: string): string | null {
  const s = (urlOrId || "").trim();
  // 11-char id
  if (/^[A-Za-z0-9_-]{11}$/.test(s)) return s;

  try {
    const u = new URL(s);
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
    const m = s.match(/[A-Za-z0-9_-]{11}/);
    return m ? m[0] : null;
  }
}

export async function summarizeVideo(
  urlOrId: string,
  opts: { lang?: string; max_chars?: number } = {}
): Promise<YouTubeSummary> {
  const videoId = extractVideoId(urlOrId);
  if (!videoId) throw new Error("Invalid YouTube URL or videoId");

  const body = {
    videoId,
    lang: opts.lang ?? "en",
    max_chars: opts.max_chars ?? 12000,
    debug: false,
  };

  const res = await fetch("/api/youtube/summarize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Summarize failed (${res.status})`);
  }
  return res.json();
}
