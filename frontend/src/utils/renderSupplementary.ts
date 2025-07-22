// src/utils/renderSupplementary.ts
import { v4 as uuidv4 } from "uuid";
import type { ChatMessage, Sender } from "../types/chat";
import { useChatStore } from "../store/chatStore";

/* ----------------- helpers: YouTube canonicalization ----------------- */
const YT_ID_RE = /[A-Za-z0-9_-]{11}/;

function extractVideoId(urlOrId: string): string | null {
  const s = String(urlOrId || "").trim();
  try {
    const u = new URL(s);
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
    const m = s.match(YT_ID_RE);
    return m ? m[0] : null;
  }
}

function canonYouTubeUrl(input: string): string {
  const v = extractVideoId(input);
  return v ? `https://www.youtube.com/watch?v=${v}` : input.trim();
}

/* --------------------- input shapes we accept --------------------- */
type YTIn =
  | {
      title?: string;
      url?: string;
      videoId?: string;
      id?: string;
      description?: string;
    }
  | [string, string] // [title, url]
  | [string, string, string] // [title, url, snippetOrId]
  | [string, string, string, string]; // [title, url, snippetMaybeId, extraSnippet]

type WebIn =
  | {
      title?: string;
      url?: string;
      link?: string;
      snippet?: string;
      description?: string;
    }
  | [string, string] // [title, url]
  | [string, string, string]; // [title, url, snippet]

type YTOut = {
  title: string;
  url: string;
  description?: string;
  videoId?: string;
};
type WebOut = { title: string; url: string; snippet?: string };

/* ----------------------- normalizers (strict) ---------------------- */
function normYoutube(data: unknown): YTOut[] {
  const arr = Array.isArray(data) ? (data as YTIn[]) : [];
  const raw: YTOut[] = [];

  for (const it of arr) {
    let title = "YouTube";
    let url = "";
    let description: string | undefined;
    let videoId: string | undefined;

    if (Array.isArray(it)) {
      if (it[0]) title = String(it[0]).trim() || title;
      if (it[1]) url = String(it[1]).trim();
      // entry[2] may be snippet OR a raw id; if it's a valid id, prefer as id
      if (it.length >= 3) {
        const third = String(it[2] ?? "").trim();
        if (YT_ID_RE.test(third)) videoId = extractVideoId(third) || undefined;
        else description = third || undefined;
      }
      if (it.length >= 4 && !description) {
        description = String(it[3] ?? "").trim() || undefined;
      }
    } else if (it && typeof it === "object") {
      const o = it as Record<string, unknown>;
      title = String(o.title ?? "").trim() || title;
      const rawUrl =
        (typeof o.url === "string" && o.url) ||
        (typeof (o as any).link === "string" && (o as any).link) ||
        "";
      const rawId =
        (typeof (o as any).videoId === "string" && (o as any).videoId) ||
        (typeof (o as any).id === "string" && (o as any).id) ||
        "";
      const desc =
        (typeof o.description === "string" && o.description) || undefined;

      if (rawUrl) url = String(rawUrl).trim();
      if (!rawUrl && rawId)
        videoId = extractVideoId(String(rawId)) || undefined;
      description = desc;
    }

    // canonicalize
    const finalUrl = canonYouTubeUrl(url || videoId || "");
    const finalId = extractVideoId(finalUrl) || undefined;
    if (!finalUrl) continue;

    raw.push({
      title: title || finalUrl,
      url: finalUrl,
      description,
      videoId: finalId,
    });
  }

  // de-dupe by videoId first, then URL
  const seenIds = new Set<string>();
  const seenUrls = new Set<string>();
  const out: YTOut[] = [];
  for (const r of raw) {
    const idKey = (r.videoId || "").toLowerCase();
    const urlKey = (r.url || "").toLowerCase();
    if (idKey) {
      if (seenIds.has(idKey)) continue;
      seenIds.add(idKey);
    } else {
      if (!urlKey || seenUrls.has(urlKey)) continue;
      seenUrls.add(urlKey);
    }
    out.push(r);
  }

  return out.slice(0, 8);
}

function normWeb(data: unknown): WebOut[] {
  const arr = Array.isArray(data) ? (data as WebIn[]) : [];
  const raw: WebOut[] = [];

  for (const it of arr) {
    let title = "";
    let url = "";
    let snippet: string | undefined;

    if (Array.isArray(it)) {
      if (it[0]) title = String(it[0]).trim();
      if (it[1]) url = String(it[1]).trim();
      if (it.length >= 3) snippet = String(it[2] ?? "").trim() || undefined;
    } else if (it && typeof it === "object") {
      const o = it as Record<string, unknown>;
      title =
        (typeof o.title === "string" && o.title) ||
        (typeof (o as any).name === "string" && (o as any).name) ||
        "";
      url =
        (typeof o.url === "string" && o.url) ||
        (typeof (o as any).link === "string" && (o as any).link) ||
        "";
      snippet =
        (typeof o.snippet === "string" && o.snippet) ||
        (typeof (o as any).description === "string" &&
          (o as any).description) ||
        undefined;
      title = String(title).trim();
      url = String(url).trim();
    }

    if (!url) continue;
    raw.push({ title: title || url, url, snippet });
  }

  // de-dupe by URL (case-insensitive)
  const seen = new Set<string>();
  const out: WebOut[] = [];
  for (const r of raw) {
    const key = (r.url || "").toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(r);
  }

  return out.slice(0, 8);
}

/* -------------------- render utility (stream + mark) -------------------- */
export async function renderSupplementary(
  type: "youtube" | "web",
  data: any,
  addMessage: (msg: ChatMessage) => void,
  streamText: (id: string, text: string, signal?: AbortSignal) => Promise<void>,
  abortSignal?: AbortSignal,
  roleId?: number,
  projectId?: number | string,
  chatSessionId?: string
) {
  const id = `${type}-${uuidv4()}`;
  const sender = type as Sender;

  const ytList = type === "youtube" ? normYoutube(data) : [];
  const webList = type === "web" ? normWeb(data) : [];

  const text =
    type === "youtube"
      ? ytList.length === 0
        ? "📺 No YouTube results found."
        : ytList
            .map(
              (v) =>
                `▶️ [${v.title || "YouTube"}](${v.url})${
                  v.description ? `\n${v.description}` : ""
                }`
            )
            .join("\n\n")
      : webList.length === 0
      ? "🌐 No web results found."
      : webList
          .map(
            (v) =>
              `🌐 [${v.title || v.url}](${v.url})${
                v.snippet ? `\n${v.snippet}` : ""
              }`
          )
          .join("\n\n");

  // Attach structured sources ONLY when we actually have items.
  const hasStructured =
    (type === "youtube" ? ytList.length : webList.length) > 0;
  const sources =
    type === "youtube"
      ? ({ youtube: ytList } as any)
      : ({ web: webList } as any);

  // 1) create streaming bubble (ChatArea hides it and shows the sidecar card when typing ends)
  addMessage({
    id,
    sender,
    text: "",
    isTyping: true,
    role_id: roleId,
    project_id: projectId,
    chat_session_id: chatSessionId,
    ...(hasStructured ? { sources } : {}),
  } as any);

  try {
    // let React commit the bubble before streaming starts (prevents racey flicker)
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    // 2) stream the content (markdown fallback)
    await streamText(id, text, abortSignal);
  } finally {
    // 3) mark done (ChatArea will swap to the card if structured)
    try {
      const { markMessageDone } = useChatStore.getState();
      markMessageDone?.(id);
    } catch {}
  }
}
