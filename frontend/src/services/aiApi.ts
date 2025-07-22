// File: src/services/aiApi.ts
import api from "./api";
import { v4 as uuidv4 } from "uuid";
import type { AxiosError } from "axios";
import type { AiStarter, AiToAiResponse, AskResponse } from "../types/ai";
import type { ChatMessage } from "../types/chat";
import { useChatStore } from "../store/chatStore";
// render meta types
import type { RenderKind, RenderMeta } from "../types/chat";

/* ----------------------------- Types & helpers ---------------------------- */

export interface BoostResponse {
  messages: { sender: string; answer: string }[];
  summary: string;
  youtube: {
    title: string;
    videoId: string;
    url: string;
    description: string;
  }[];
  web: { title: string; url: string; snippet: string }[];
}

export interface LastSessionByRoleResponse {
  chat_session_id?: string;
  role_id?: number;
  role_name?: string;
  messages?: ChatMessage[];
  summaries?: { summary: string; timestamp?: string }[];
}

const isAxiosError = (error: unknown): error is AxiosError =>
  !!error && typeof error === "object" && "isAxiosError" in (error as any);

/** Coerce to positive integer project id */
const toProjectIdNumber = (project_id: string | number): number => {
  const n = Number(project_id);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
};

const describeError = (err: unknown) => {
  const ax = err as AxiosError | undefined;
  const status = ax?.response?.status ?? (ax as any)?.status ?? "n/a";
  const detail =
    (ax?.response?.data as any)?.detail ??
    (typeof ax?.response?.data === "string"
      ? ax.response!.data.slice(0, 200)
      : (ax as any)?.message || "Unknown error");
  return { status, detail };
};

/** If backend returns a new sid, mirror it into the chat store */
const maybeAdoptSessionId = (
  sid: string | undefined,
  roleId: number,
  projectIdNum: number
) => {
  if (!sid) return;
  const store = useChatStore.getState();
  try {
    store.setChatSessionId?.(sid);
    store.setLastSessionMarker?.({
      roleId,
      projectId: projectIdNum,
      chatSessionId: sid,
    });
  } catch {
    /* no-op if store APIs differ */
  }
};

/* ----------------------------- Normalizers ------------------------------- */

/** Map any backend render-ish shape into RenderMeta */
const normalizeRenderMeta = (raw: any): RenderMeta | undefined => {
  if (!raw) return undefined;

  // accept either nested {render:{...}} or top-level fields
  const r = raw.render ?? raw;

  // Did the response include ANY render-related hints?
  const hasHints =
    (typeof r.kind === "string" && r.kind.length > 0) ||
    (typeof r.type === "string" && r.type.length > 0) ||
    (typeof r.output_mode === "string" && r.output_mode.length > 0) ||
    (typeof r.presentation === "string" && r.presentation.length > 0) ||
    (typeof r.language === "string" && r.language.length > 0) ||
    (typeof r.lang === "string" && r.lang.length > 0) ||
    (typeof r.filename === "string" && r.filename.length > 0) ||
    (typeof r.file === "string" && r.file.length > 0);

  let kind: RenderKind | undefined;

  // 1) direct `kind`
  if (typeof r.kind === "string") {
    const k = r.kind.toLowerCase();
    if (
      k === "markdown" ||
      k === "plain" ||
      k === "code" ||
      k === "poem_plain" ||
      k === "poem_code"
    ) {
      kind = k as RenderKind;
    }
  }

  // 2) legacy `type`  (backend may send "doc" for markdown)
  if (!kind && typeof r.type === "string") {
    const t = r.type.toLowerCase();
    if (t === "doc") kind = "markdown";
    else if (
      t === "markdown" ||
      t === "plain" ||
      t === "code" ||
      t === "poem_plain" ||
      t === "poem_code"
    ) {
      kind = t as RenderKind;
    }
  }

  // 3) split fields  (backend uses output_mode "doc" for markdown)
  if (!kind) {
    const output_mode =
      typeof r.output_mode === "string"
        ? r.output_mode.toLowerCase()
        : undefined;
    const presentation =
      typeof r.presentation === "string"
        ? r.presentation.toLowerCase()
        : undefined;

    if (presentation === "poem_plain") kind = "poem_plain";
    else if (presentation === "poem_code") kind = "poem_code";
    else if (output_mode === "plain") kind = "plain";
    else if (output_mode === "code") kind = "code";
    else if (output_mode === "doc") kind = "markdown";
    else if (output_mode === "markdown") kind = "markdown"; // tolerate if ever sent
  }

  // If the server gave *no* hints at all, do NOT synthesize markdown.
  if (!kind && !hasHints) return undefined;

  const language =
    (typeof r.language === "string" && r.language) ||
    (typeof r.lang === "string" && r.lang) ||
    null;

  const filename =
    (typeof r.filename === "string" && r.filename) ||
    (typeof r.file === "string" && r.file) ||
    null;

  return {
    kind: (kind ?? "markdown") as RenderKind,
    language,
    filename,
    type: (r.type as any) || undefined,
  };
};

/** Normalize sources (supports both new nested + legacy top-level) */
const normalizeSources = (data: any) => {
  const rawYt = (data?.sources?.youtube ?? data?.youtube) as any[] | undefined;
  const rawWeb = (data?.sources?.web ?? data?.web) as any[] | undefined;

  const yt = Array.isArray(rawYt)
    ? rawYt
        .map(
          (r) =>
            [
              String(r?.title ?? "").trim(),
              String(
                r?.url ??
                  (r?.videoId
                    ? `https://www.youtube.com/watch?v=${r.videoId}`
                    : "")
              ).trim(),
            ] as const
        )
        .filter(([, url]) => url)
        .map(([title, url]) => ({ title, url }))
    : [];

  const web = Array.isArray(rawWeb)
    ? rawWeb
        .map((r) => ({
          title: String(r?.title ?? "").trim(),
          url: String(r?.url ?? "").trim(),
          snippet: typeof r?.snippet === "string" ? r.snippet : undefined,
        }))
        .filter((x) => x.url)
    : [];

  return yt.length || web.length ? ({ youtube: yt, web } as const) : undefined;
};

/** Build fields expected by backend from a `kind` override (optional) */
const buildRenderFields = (opts?: {
  kind?: RenderKind;
  language?: string | null;
  filename?: string | null;
}) => {
  if (!opts?.kind) return {};
  const { kind, language, filename } = opts;
  const out: Record<string, any> = {};

  // output_mode + presentation for compatibility with backend
  if (kind === "plain") out.output_mode = "plain";
  else if (kind === "markdown") out.output_mode = "doc";
  // backend expects "doc"
  else if (kind === "code") out.output_mode = "code";
  else if (kind === "poem_plain") {
    out.output_mode = "plain";
    out.presentation = "poem_plain";
  } else if (kind === "poem_code") {
    out.output_mode = "code";
    out.presentation = "poem_code";
  }

  if (language) out.language = language;
  if (filename) out.filename = filename;

  return out;
};

/* --------------------------------- /ask ---------------------------------- */
/**
 * Send a message to OpenAI, Anthropic, or both.
 * - If no chatSessionId is provided but the store says sessionReady=true,
 *   we send with "" so the backend can create the session on first send.
 *
 * NEW: optional `opts` to pass render kind/language/filename without breaking callers.
 */
export const sendAiMessage = async (
  question: string,
  provider: "openai" | "anthropic" | "all",
  role: string | number,
  project_id: string | number,
  chatSessionId?: string,
  opts?: {
    kind?: RenderKind;
    language?: string | null;
    filename?: string | null;
  }
): Promise<AskResponse> => {
  const role_id = Number(role);
  const projectIdNum = toProjectIdNumber(project_id);

  const store = useChatStore.getState();
  const finalSessionId =
    chatSessionId ??
    (store.sessionReady
      ? ""
      : await store.waitForSessionReady(role_id, projectIdNum));

  const payload = {
    query: question,
    provider,
    role_id,
    project_id: String(projectIdNum),
    chat_session_id: finalSessionId ?? "",
    ...buildRenderFields(opts),
  };

  // Optional: re-enable for debugging payload/renders
  // console.log("📤 POST /ask payload:", payload);

  try {
    const res = await api.post("/ask", payload);
    const data = res.data ?? {};
    const sid = String(data.chat_session_id ?? finalSessionId ?? "");

    // If backend minted a new sid, adopt it into the store
    if (!finalSessionId && data.chat_session_id) {
      maybeAdoptSessionId(sid, role_id, projectIdNum);
    }

    // Normalize sources & render
    const sources = normalizeSources(data);
    // Prefer server meta; if absent, fall back to caller override
    const render =
      normalizeRenderMeta(data) ||
      (opts?.kind
        ? {
            kind: opts.kind,
            language: opts.language ?? null,
            filename: opts.filename ?? null,
          }
        : undefined);

    // Optional: re-enable for debugging client-side meta
    // console.log("🧪 normalized render meta (client)", render);

    if (provider === "all") {
      const messages = [
        data.openai
          ? ({
              sender: "openai",
              text: String(data.openai),
              ...(sources ? { sources } : {}),
              ...(render ? { render } : {}),
            } as any)
          : null,
        data.claude
          ? ({
              sender: "anthropic",
              text: String(data.claude),
              ...(sources ? { sources } : {}),
              ...(render ? { render } : {}),
            } as any)
          : null,
        data.summary
          ? ({
              sender: "anthropic", // keep for summary bubble styling
              text: String(data.summary),
              isSummary: true,
              ...(sources ? { sources } : {}),
              ...(render ? { render } : {}),
            } as any)
          : null,
      ].filter(Boolean) as AskResponse["messages"];

      return {
        messages,
        chat_session_id: sid,
        ...(sources ? { sources } : {}),
      };
    }

    // Single-provider path → attach sources + render to the assistant message
    const single: AskResponse["messages"][number] = {
      sender: provider,
      text: data.answer ?? "[No reply]",
      ...(sources ? { sources } : {}),
      ...(render ? { render } : {}),
    } as any;

    return {
      messages: [single],
      chat_session_id: sid,
      ...(sources ? { sources } : {}),
    };
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 422) {
      console.error("🔍 422 Validation Error (/ask):", error.response.data);
    } else {
      const { status, detail } = describeError(error);
      console.error(`❌ API Error from /ask (status ${status}): ${detail}`);
    }
    throw error;
  }
};

/* ------------------------- /chat/last-session-by-role --------------------- */
export const getLastSessionByRole = async (
  roleId: number,
  projectId: string | number
): Promise<LastSessionByRoleResponse> => {
  try {
    const res = await api.get("/chat/last-session-by-role", {
      params: { role_id: roleId, project_id: String(projectId), limit: 200 },
    });
    const data = res.data ?? {};
    return {
      ...data,
      messages: Array.isArray(data.messages) ? data.messages : [],
      summaries: Array.isArray(data.summaries) ? data.summaries : [],
    };
  } catch (err) {
    if (isAxiosError(err) && err.response?.status === 404) {
      console.warn(
        `ℹ️ No session found for role=${roleId}, project=${projectId}`
      );
      return { messages: [], summaries: [] };
    }
    const { status, detail } = describeError(err);
    console.error(
      `⚠️ Failed to fetch session for role=${roleId}, project=${projectId} (status ${status}): ${detail}`
    );
    return { messages: [], summaries: [] };
  }
};

/* ------------------------------ /ask-ai-to-ai ----------------------------- */
export const sendAiToAiMessage = async (
  topic: string,
  starter: AiStarter,
  roleId: number,
  projectId: string | number,
  chatSessionId?: string
): Promise<AiToAiResponse> => {
  const projectIdNum = toProjectIdNumber(projectId);

  const store = useChatStore.getState();
  const finalSessionId =
    chatSessionId ??
    (store.sessionReady
      ? ""
      : await store.waitForSessionReady(roleId, projectIdNum));

  const payload = {
    topic,
    starter,
    role: String(roleId),
    project_id: String(projectIdNum),
    chat_session_id: finalSessionId ?? "",
  };

  // console.log("📤 POST /ask-ai-to-ai payload:", payload);

  try {
    const res = await api.post("/ask-ai-to-ai", payload);
    const { messages, summary, youtube, web, chat_session_id } = res.data ?? {};

    const sid = String(chat_session_id ?? finalSessionId ?? "");
    if (!finalSessionId && chat_session_id) {
      maybeAdoptSessionId(sid, roleId, projectIdNum);
    }

    const mapped: ChatMessage[] = [];

    if (messages?.[0]) {
      mapped.push({
        id: `boost0-${uuidv4()}`,
        sender: String(messages[0].sender),
        text: String(messages[0].answer ?? ""),
        role_id: roleId,
        project_id: String(projectIdNum),
        chat_session_id: sid,
        isTyping: false,
      } as ChatMessage);
    }

    if (messages?.[1]) {
      mapped.push({
        id: `boost1-${uuidv4()}`,
        sender: String(messages[1].sender),
        text: String(messages[1].answer ?? ""),
        role_id: roleId,
        project_id: String(projectIdNum),
        chat_session_id: sid,
        isTyping: false,
      } as ChatMessage);
    }

    mapped.push({
      id: `summary-${uuidv4()}`,
      sender: "anthropic",
      text: String(summary ?? "⚠️ No summary available."),
      role_id: roleId,
      project_id: String(projectIdNum),
      chat_session_id: sid,
      isTyping: false,
      isSummary: true,
    } as ChatMessage);

    return { messages: mapped, youtube: youtube ?? [], web: web ?? [] };
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 422) {
      console.error(
        "🔍 422 Validation Error (/ask-ai-to-ai):",
        error.response.data
      );
    } else {
      const { status, detail } = describeError(error);
      console.error(
        `❌ API Error from /ask-ai-to-ai (status ${status}): ${detail}`
      );
    }
    throw error;
  }
};

/* ------------------------------ /chat/summarize --------------------------- */
/**
 * Backend (refactored) returns:
 * {
 *   ok: true,
 *   project_id, role_id, chat_session_id,
 *   divider_message: { sender:'final', text:'...', isSummary:true, ... }
 * }
 */
export const summarizeChat = async (
  roleId: number,
  projectId: string | number,
  chatSessionId?: string | null
): Promise<{
  ok: boolean;
  divider?: ChatMessage;
  chat_session_id?: string;
  new_chat_session_id?: string; // optional rotation support
}> => {
  const payload = {
    role_id: Number(roleId),
    project_id: String(toProjectIdNumber(projectId)),
    chat_session_id: chatSessionId ?? null,
  };
  // console.log("📤 POST /chat/summarize payload:", payload);

  try {
    const res = await api.post("/chat/summarize", payload);
    const data = res.data ?? {};

    const dividerRaw =
      data?.divider_message ??
      (data?.summary
        ? {
            sender: "final",
            text: String(data.summary || ""),
            role_id: roleId,
            project_id: String(toProjectIdNumber(projectId)),
            chat_session_id: chatSessionId ?? data.chat_session_id ?? "",
            isSummary: true,
          }
        : undefined);

    const divider: ChatMessage | undefined = dividerRaw
      ? ({
          id: `divider-${uuidv4()}`,
          sender: dividerRaw.sender ?? "final",
          text: String(dividerRaw.text ?? ""),
          role_id: Number(dividerRaw.role_id ?? roleId),
          project_id: String(dividerRaw.project_id ?? projectId),
          chat_session_id: String(
            (dividerRaw as any).chat_session_id ?? data.chat_session_id ?? ""
          ),
          isTyping: false,
          isSummary: true,
          render: normalizeRenderMeta(dividerRaw),
        } as ChatMessage)
      : undefined;

    return {
      ok: Boolean(data?.ok ?? true),
      divider,
      chat_session_id: data?.chat_session_id,
      new_chat_session_id: data?.new_chat_session_id,
    };
  } catch (error) {
    const { status, detail } = describeError(error);
    console.error(
      `❌ API Error from /chat/summarize (status ${status}): ${detail}`
    );
    throw error;
  }
};

// Alias (so callers can use either name)
export const summarizeSession = summarizeChat;

/* ---------------------------- Prompts / Upload ---------------------------- */
export const fetchPromptsByRole = async (roleId: number) => {
  try {
    const res = await api.get(`/prompts/by-role/${roleId}`);
    return res.data ?? [];
  } catch (error) {
    const { status, detail } = describeError(error);
    console.error(
      `❌ Failed to fetch prompts for role ${roleId} (status ${status}): ${detail}`
    );
    throw error;
  }
};

export const uploadFile = async (
  file: File,
  roleId: number | null,
  projectId: string | number,
  chatSessionId?: string
): Promise<{ summary: string } | null> => {
  if (!file || !roleId || projectId === undefined || projectId === null) {
    console.warn("⚠️ Missing file, roleId, or projectId");
    return null;
  }

  const pid = toProjectIdNumber(projectId);

  const formData = new FormData();
  formData.append("file", file);
  formData.append("role_id", String(roleId));
  formData.append("project_id", String(pid));
  formData.append("chat_session_id", chatSessionId ?? "");

  try {
    const res = await api.post("/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return res.data ?? null;
  } catch (error) {
    const { status, detail } = describeError(error);
    console.error(`❌ Upload failed (status ${status}): ${detail}`);
    return null;
  }
};

/* ------------------------------- /chat/history ---------------------------- */
export const getChatHistory = async (
  projectId: string | number,
  roleId: string | number,
  chatSessionId: string
): Promise<{ messages: ChatMessage[] }> => {
  try {
    const res = await api.get("/chat/history", {
      params: {
        project_id: String(toProjectIdNumber(projectId)),
        role_id: Number(roleId),
        chat_session_id: chatSessionId,
      },
    });

    const raw = Array.isArray(res.data?.messages) ? res.data.messages : [];
    const messages: ChatMessage[] = raw.map((msg: any) => ({
      id: `${msg.sender}-${uuidv4()}`,
      sender: String(msg.sender),
      text: String(msg.text ?? ""),
      role_id: Number(msg.role_id),
      project_id: String(msg.project_id),
      chat_session_id: String(msg.chat_session_id ?? ""),
      isTyping: Boolean(msg.isTyping),
      isSummary: Boolean(msg.isSummary),
      render: normalizeRenderMeta(msg), // pick up msg.render / msg.output_mode / msg.presentation
      // sources: normalizeSources(msg), // enable if history carries sources
    }));

    return { messages };
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 404) {
      console.warn("ℹ️ No chat history found for given session.");
      return { messages: [] };
    }
    const { status, detail } = describeError(error);
    console.error(
      `❌ Failed to fetch chat history (status ${status}): ${detail}`
    );
    return { messages: [] };
  }
};

/* --------------------------- /chat/last-session (any) --------------------- */
export const getLastSession = async () => {
  try {
    const res = await api.get("/chat/last-session");
    return res.data ?? {};
  } catch (err) {
    const { status, detail } = describeError(err);
    console.warn(
      `⚠️ Failed to fetch last session (status ${status}): ${detail}`
    );
    throw err;
  }
};
