// File: src/services/aiApi.ts
import api from "./api";
import { v4 as uuidv4 } from "uuid";
import type { AxiosError } from "axios";
import type { AiStarter, AiToAiResponse } from "../types/ai";
import type { ChatMessage } from "../types/chat";

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
  typeof error === "object" && error !== null && "isAxiosError" in error;

const sanitizeProjectId = (
  project_id: string | number
): number | "default" | undefined => {
  if (project_id === "default") return "default";
  if (!isNaN(Number(project_id))) return Number(project_id);
  return undefined;
};

/**
 * ✅ Send a message to OpenAI, Anthropic, or both
 */
export const sendAiMessage = async (
  question: string,
  provider: "openai" | "anthropic" | "all",
  role: string | number,
  project_id: string | number,
  chatSessionId?: string
): Promise<{
  messages: { sender: string; text: string }[];
  chat_session_id: string;
}> => {
  const role_id = Number(role);
  const projectId = sanitizeProjectId(project_id) ?? 0;
  const payload = {
    query: question,
    provider,
    role_id,
    project_id: projectId,
    chat_session_id: chatSessionId ?? "",
  };

  console.log("📤 POST /ask payload:", payload);

  try {
    const res = await api.post("/ask", payload);
    const data = res.data ?? {};
    return {
      messages: [{ sender: provider, text: data.answer ?? "[No reply]" }],
      chat_session_id: data.chat_session_id ?? chatSessionId ?? "",
    };
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 422) {
      console.error("🔍 422 Validation Error:", error.response.data);
    } else {
      console.error("❌ API Error from /ask:", error);
    }
    throw error;
  }
};

/**
 * ✅ Restore last session for a role + project
 */
export const getLastSessionByRole = async (
  roleId: number,
  projectId: string | number
): Promise<LastSessionByRoleResponse> => {
  try {
    const res = await api.get("/chat/last-session-by-role", {
      params: {
        role_id: roleId,
        project_id: String(projectId),
      },
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
    console.error(
      `⚠️ Failed to fetch session for role=${roleId}, project=${projectId}:`,
      err
    );
    return { messages: [], summaries: [] };
  }
};

/**
 * ✅ Boost Mode — multi-AI chain and summary
 */
export const sendAiToAiMessage = async (
  topic: string,
  starter: AiStarter,
  roleId: number,
  projectId: string | number,
  chatSessionId?: string
): Promise<AiToAiResponse> => {
  const payload = {
    topic,
    starter,
    role: String(roleId),
    project_id: String(projectId),
    chat_session_id: chatSessionId ?? "",
  };

  console.log("📤 POST /ask-ai-to-ai payload:", payload);

  try {
    const res = await api.post("/ask-ai-to-ai", payload);
    const { messages, summary, youtube, web } = res.data ?? {};

    const chat_session_id = payload.chat_session_id;
    const mapped: ChatMessage[] = [];

    if (messages?.[0]) {
      mapped.push({
        id: `boost0-${uuidv4()}`,
        sender: messages[0].sender,
        text: messages[0].answer,
        role_id: roleId,
        project_id: String(projectId),
        chat_session_id,
        isTyping: false,
      });
    }

    if (messages?.[1]) {
      mapped.push({
        id: `boost1-${uuidv4()}`,
        sender: messages[1].sender,
        text: messages[1].answer,
        role_id: roleId,
        project_id: String(projectId),
        chat_session_id,
        isTyping: false,
      });
    }

    mapped.push({
      id: `summary-${uuidv4()}`,
      sender: "anthropic",
      text: summary ?? "⚠️ No summary available.",
      role_id: roleId,
      project_id: String(projectId),
      chat_session_id,
      isTyping: false,
      isSummary: true,
    });

    return { messages: mapped, youtube: youtube ?? [], web: web ?? [] };
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 422) {
      console.error("🔍 422 Validation Error:", error.response.data);
    } else {
      console.error("❌ API Error from /ask-ai-to-ai:", error);
    }
    throw error;
  }
};

/**
 * ✅ Summarize and rotate session
 */
export const summarizeChat = async (
  roleId: number,
  projectId: string | number,
  chatSessionId: string
): Promise<{ summary: string; new_chat_session_id?: string }> => {
  try {
    const payload = {
      role_id: roleId,
      project_id: String(projectId),
      chat_session_id: chatSessionId,
    };
    console.log("📤 POST /chat/summarize payload:", payload);

    const res = await api.post("/chat/summarize", payload);
    const { summary, new_chat_session_id, cleared } = res.data ?? {};

    if (cleared && new_chat_session_id) {
      console.log(`🔄 Session rotated → ${new_chat_session_id}`);
    }

    return { summary: summary ?? "", new_chat_session_id };
  } catch (error) {
    console.error("❌ API Error from /chat/summarize:", error);
    throw error;
  }
};

/**
 * ✅ Fetch all prompts for a role
 */
export const fetchPromptsByRole = async (roleId: number) => {
  try {
    const res = await api.get(`/prompts/by-role/${roleId}`);
    return res.data ?? [];
  } catch (error) {
    console.error(`❌ Failed to fetch prompts for role ${roleId}:`, error);
    throw error;
  }
};

/**
 * ✅ Upload file with context
 */
export const uploadFile = async (
  file: File,
  roleId: number | null,
  projectId: string | number,
  chatSessionId?: string
): Promise<{ summary: string } | null> => {
  if (!file || !roleId || !projectId) {
    console.warn("⚠️ Missing file, roleId, or projectId");
    return null;
  }

  const formData = new FormData();
  formData.append("file", file);
  formData.append("role_id", String(roleId));
  formData.append("project_id", String(projectId));
  formData.append("chat_session_id", chatSessionId ?? "");

  try {
    const res = await api.post("/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return res.data ?? null;
  } catch (error) {
    console.error("❌ Upload failed:", error);
    return null;
  }
};

/**
 * ✅ Load chat history (direct)
 * Always returns empty array if nothing found
 */
export const getChatHistory = async (
  projectId: string | number,
  roleId: string | number,
  chatSessionId: string
): Promise<{ messages: ChatMessage[] }> => {
  try {
    const res = await api.get("/chat/history", {
      params: {
        project_id: String(projectId),
        role_id: Number(roleId),
        chat_session_id: chatSessionId,
      },
    });

    const raw = Array.isArray(res.data?.messages) ? res.data.messages : [];
    const messages: ChatMessage[] = raw.map((msg: any) => ({
      id: `${msg.sender}-${uuidv4()}`,
      sender: msg.sender,
      text: msg.text,
      role_id: Number(msg.role_id),
      project_id: String(msg.project_id),
      chat_session_id: msg.chat_session_id ?? "",
      isTyping: msg.isTyping ?? false,
      isSummary: msg.isSummary ?? false,
    }));

    return { messages };
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 404) {
      console.warn("ℹ️ No chat history found for given session.");
      return { messages: [] };
    }
    console.error("❌ Failed to fetch chat history:", error);
    return { messages: [] };
  }
};

/**
 * ✅ Get last session without role/project filter
 */
export const getLastSession = async () => {
  try {
    const res = await api.get("/chat/last-session");
    return res.data ?? {};
  } catch (err) {
    console.warn("⚠️ Failed to fetch last session:", err);
    throw err;
  }
};
