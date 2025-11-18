// src/services/aiApi.ts
import api from "./api";
import { v4 as uuidv4 } from "uuid";
import type { AxiosError } from "axios";
import type { AiStarter, AiToAiResponse, AskResponse } from "../types/ai";
import type { ChatMessage } from "../types/chat";
import { useChatStore } from "../store/chatStore";
import type { RenderKind, RenderMeta } from "../types/chat";

/* ----------------------------- Types & helpers ---------------------------- */

export interface BoostResponse {
  messages: { sender: string; answer: string }[];
  summary: string;
  youtube: {
    title: string;
    url: string;
    /** optional fields from different backends */
    videoId?: string;
    description?: string;
  }[];
  web: {
    title: string;
    url: string;
    /** can be snippet or description depending on backend */
    snippet?: string;
    description?: string;
  }[];
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
  const data = ax?.response?.data as any;
  const detail =
    data?.detail ??
    (typeof data === "string"
      ? data.slice(0, 400)
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
    if (typeof store.handleSessionIdUpdateFromAsk === "function") {
      store.handleSessionIdUpdateFromAsk(sid);
    } else {
      store.setChatSessionId?.(sid);
      store.setLastSessionMarker?.({
        roleId,
        projectId: projectIdNum,
        chatSessionId: sid,
      });
    }
  } catch {
    /* store API may differ */
  }
};

/* ----------------------------- Normalizers ------------------------------- */

const normalizeRenderMeta = (raw: any): RenderMeta | undefined => {
  if (!raw) return undefined;
  const r = raw.render ?? raw;

  const hasHints =
    (typeof r.kind === "string" && r.kind) ||
    (typeof r.type === "string" && r.type) ||
    (typeof r.output_mode === "string" && r.output_mode) ||
    (typeof r.presentation === "string" && r.presentation) ||
    (typeof r.language === "string" && r.language) ||
    (typeof r.lang === "string" && r.lang) ||
    (typeof r.filename === "string" && r.filename) ||
    (typeof r.file === "string" && r.file);

  let kind: RenderKind | undefined;

  if (typeof r.kind === "string") {
    const k = r.kind.toLowerCase();
    if (["markdown", "plain", "code", "poem_plain", "poem_code"].includes(k)) {
      kind = k as RenderKind;
    }
  }

  if (!kind && typeof r.type === "string") {
    const t = r.type.toLowerCase();
    if (t === "doc") kind = "markdown";
    else if (
      ["markdown", "plain", "code", "poem_plain", "poem_code"].includes(t)
    ) {
      kind = t as RenderKind;
    }
  }

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
    else if (output_mode === "doc" || output_mode === "markdown")
      kind = "markdown";
  }

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

const normalizeSources = (data: any) => {
  const rawYt = (data?.sources?.youtube ?? data?.youtube) as any[] | undefined;
  const rawWeb = (data?.sources?.web ?? data?.web) as any[] | undefined;

  const yt = Array.isArray(rawYt)
    ? (rawYt
        .map((r) => {
          const title = String(r?.title ?? "").trim();
          const url = String(
            r?.url ??
              (r?.videoId ? `https://www.youtube.com/watch?v=${r.videoId}` : "")
          ).trim();
          const description =
            typeof r?.description === "string" ? r.description : undefined;
          return url
            ? { title, url, ...(description ? { description } : {}) }
            : null;
        })
        .filter(Boolean) as {
        title: string;
        url: string;
        description?: string;
      }[])
    : [];

  const web = Array.isArray(rawWeb)
    ? (rawWeb
        .map((r) => {
          const title = String(r?.title ?? "").trim();
          const url = String(r?.url ?? "").trim();
          const snippet =
            typeof r?.snippet === "string"
              ? r.snippet
              : typeof r?.description === "string"
              ? r.description
              : undefined;
          return url ? { title, url, ...(snippet ? { snippet } : {}) } : null;
        })
        .filter(Boolean) as { title: string; url: string; snippet?: string }[])
    : [];

  return yt.length || web.length ? ({ youtube: yt, web } as const) : undefined;
};

const buildRenderFields = (opts?: {
  kind?: RenderKind;
  output_mode?: "plain" | "doc" | "code";
  presentation?: "default" | "poem_plain" | "poem_code";
  language?: string | null;
  filename?: string | null;
}) => {
  if (!opts) return {};

  const out: Record<string, any> = {};

  if (opts.output_mode) out.output_mode = opts.output_mode;
  if (opts.presentation && opts.presentation !== "default") {
    out.presentation = opts.presentation;
  }

  if (!out.output_mode && opts.kind) {
    if (opts.kind === "plain") out.output_mode = "plain";
    else if (opts.kind === "markdown") out.output_mode = "doc";
    else if (opts.kind === "code") out.output_mode = "code";
    else if (opts.kind === "poem_plain") {
      out.output_mode = "plain";
      out.presentation = "poem_plain";
    } else if (opts.kind === "poem_code") {
      out.output_mode = "code";
      out.presentation = "poem_code";
    }
  }

  if (opts.language != null) out.language = opts.language;
  if (opts.filename != null) out.filename = opts.filename;

  return out;
};

/* --------------------------------- /ask ---------------------------------- */
export const sendAiMessage = async (
  question: string,
  provider: "openai" | "anthropic" | "all",
  role: string | number,
  project_id: string | number,
  chatSessionId?: string,
  opts?: {
    kind?: RenderKind;
    output_mode?: "plain" | "doc" | "code";
    presentation?: "default" | "poem_plain" | "poem_code";
    language?: string | null;
    filename?: string | null;
  }
): Promise<AskResponse> => {
  const role_id = Number(role);
  const projectIdNum = toProjectIdNumber(project_id);

  // Get Claude model from store if provider is anthropic
  let model_key: string | undefined;
  if (provider === "anthropic") {
    const { claudeModel } = useChatStore.getState();
    // Map the model name to the model_key format expected by backend model registry
    if (claudeModel === "claude-opus-4-20250514") {
      model_key = "claude-opus-4";
    } else if (claudeModel === "claude-sonnet-4-20250514") {
      model_key = "claude-3-5-sonnet";
    } else {
      model_key = "claude-3-5-sonnet"; // default to Sonnet
    }
  }

  // Resolve session id intelligently
  let finalSessionId = chatSessionId;
  const store = useChatStore.getState();
  if (finalSessionId == null) {
    if (store.sessionReady) {
      finalSessionId = store.chatSessionId ?? "";
    } else if (typeof store.waitForSessionReady === "function") {
      finalSessionId = await store.waitForSessionReady(role_id, projectIdNum);
    } else {
      finalSessionId = "";
    }
  }

  const renderCompat = buildRenderFields(opts);

  const renderModern = (() => {
    const r: Record<string, any> = {};
    let used = false;
    if (opts?.kind) {
      r.requested = opts.kind;
      r.kind = opts.kind;
      used = true;
    }
    if (opts?.output_mode) {
      r.output_mode = opts.output_mode;
      used = true;
    }
    if (opts?.presentation && opts.presentation !== "default") {
      r.presentation = opts.presentation;
      used = true;
    }
    if (opts?.language !== undefined) {
      r.language = opts.language;
      used = true;
    }
    if (opts?.filename !== undefined) {
      r.filename = opts.filename;
      used = true;
    }
    return used ? r : undefined;
  })();

  const payload = {
    query: question,
    question,
    text: question,
    provider,
    role_id,
    project_id: String(projectIdNum),
    chat_session_id: finalSessionId ?? "",
    ...(model_key ? { model_key } : {}),
    ...(Object.keys(renderCompat).length ? renderCompat : {}),
    ...(renderModern ? { render: renderModern } : {}),
  };

  try {
    const res = await api.post("/ask", payload);
    const data = res.data ?? {};
    const sid = String(data.chat_session_id ?? finalSessionId ?? "");

    if (!finalSessionId && data.chat_session_id) {
      maybeAdoptSessionId(sid, role_id, projectIdNum);
    }

    const sources = normalizeSources(data);
    const render =
      normalizeRenderMeta(data) ||
      (opts
        ? {
            kind:
              (opts.kind as RenderKind) ??
              (opts.output_mode === "plain"
                ? "plain"
                : opts.output_mode === "code"
                ? opts.presentation === "poem_code"
                  ? "poem_code"
                  : "code"
                : opts.presentation === "poem_plain"
                ? "poem_plain"
                : "markdown"),
            language: opts.language ?? null,
            filename: opts.filename ?? null,
          }
        : undefined);

    // A) Generic message array
    if (Array.isArray(data.messages)) {
      const messages = (data.messages as any[]).map((m) => ({
        sender: String(m?.sender || provider),
        text: String(m?.text ?? ""),
        ...(normalizeSources(m) ?? (sources ? { sources } : {})),
        ...(normalizeRenderMeta(m) ?? (render ? { render } : {})),
        ...(m?.isSummary ? { isSummary: true } : {}),
      })) as AskResponse["messages"];

      return {
        messages,
        chat_session_id: sid,
        ...(sources ? { sources } : {}),
      };
    }

    // B) Multi-provider shorthand
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
              sender: "anthropic",
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

    // C) Single model shorthand
    const singleText =
      (typeof data.answer === "string" && data.answer) ||
      (typeof data.text === "string" && data.text) ||
      "";

    const single: AskResponse["messages"][number] = {
      sender: provider,
      text: singleText || "[No reply]",
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

  let finalSessionId = chatSessionId;
  const store = useChatStore.getState();
  if (finalSessionId == null) {
    if (store.sessionReady) {
      finalSessionId = store.chatSessionId ?? "";
    } else if (typeof store.waitForSessionReady === "function") {
      finalSessionId = await store.waitForSessionReady(roleId, projectIdNum);
    } else {
      finalSessionId = "";
    }
  }

  const payload = {
    topic,
    starter,
    role: String(roleId),
    project_id: String(projectIdNum),
    chat_session_id: finalSessionId ?? "",
  };

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

    return {
      messages: mapped,
      youtube: youtube ?? [],
      web: web ?? [],
      chat_session_id: sid,
    };
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
export const summarizeChat = async (
  roleId: number,
  projectId: string | number,
  chatSessionId?: string | null
): Promise<{
  ok: boolean;
  divider?: ChatMessage;
  chat_session_id?: string;
  new_chat_session_id?: string;
}> => {
  const payload = {
    role_id: Number(roleId),
    project_id: String(toProjectIdNumber(projectId)),
    chat_session_id: chatSessionId ?? null,
  };

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

// Alias
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
  chatSessionId?: string,
  provider?: string
): Promise<any | null> => {
  if (!file || !roleId || projectId === undefined || projectId === null) {
    console.warn("⚠️ Missing file, roleId, or projectId");
    return null;
  }

  const pid = toProjectIdNumber(projectId);

  // Ensure clipboard drops have a filename (some browsers omit it)
  const namedFile = file.name?.trim()
    ? file
    : new File(
        [file],
        `upload-${Date.now()}.${(
          file.type.split("/")[1] || "bin"
        ).toLowerCase()}`,
        { type: file.type || "application/octet-stream" }
      );

  const formData = new FormData();
  formData.append("file", namedFile, namedFile.name);

  try {
    const res = await api.post("/upload", formData, {
      params: {
        role_id: Number(roleId),
        project_id: String(pid),
        ...(chatSessionId ? { chat_session_id: chatSessionId } : {}),
        ...(provider ? { provider } : {}),
      },
      // Let the browser set multipart boundary; don't set Content-Type manually
    });

    const data = res.data ?? null;
    if (data?.chat_session_id) {
      maybeAdoptSessionId(String(data.chat_session_id), Number(roleId), pid);
    }
    return data;
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
        include_youtube: true,
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
      render: normalizeRenderMeta(msg),
      sources: normalizeSources(msg),
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
