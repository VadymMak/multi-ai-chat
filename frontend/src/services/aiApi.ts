import api from "./api";
import type { AxiosError } from "axios";
import type { AiStarter, AiToAiResponse } from "../types/ai";
import type { ChatMessage, Sender } from "../types/chat";

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

const isAxiosError = (error: unknown): error is AxiosError => {
  return typeof error === "object" && error !== null && "isAxiosError" in error;
};

const sanitizeProjectId = (
  project_id: string | number
): number | "default" | undefined => {
  if (project_id === "default") return "default";
  if (!isNaN(Number(project_id))) return Number(project_id);
  return undefined;
};

// ✅ Returns structured messages + chat_session_id
export const sendAiMessage = async (
  question: string,
  provider: "openai" | "anthropic" | "all",
  role: string | number,
  project_id: string | number,
  chatSessionId?: string
): Promise<{ messages: ChatMessage[]; chat_session_id: string }> => {
  const payload = {
    query: question,
    provider,
    role_id: Number(role),
    project_id: sanitizeProjectId(project_id) ?? 0,
    chat_session_id: chatSessionId ?? "",
  };

  console.log("📤 POST /ask payload:", payload);

  try {
    const res = await api.post("/ask", payload);
    const data = res.data;

    const messages: ChatMessage[] = [
      {
        id: `user-${crypto.randomUUID()}`,
        sender: "user",
        text: question,
        isTyping: false,
      },
      {
        id: `${provider}-${crypto.randomUUID()}`,
        sender: provider as Sender,
        text: data.answer ?? "[No reply]",
        isTyping: false,
      },
    ];

    return {
      messages,
      chat_session_id: data.chat_session_id ?? chatSessionId ?? "",
    };
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 422) {
      const detail = (error.response.data as { detail: any }).detail;
      console.error(
        "🔍 422 Validation Error:",
        JSON.stringify(detail, null, 2)
      );
    } else {
      console.error("❌ API Error from /ask:", error);
    }
    throw error;
  }
};

// ✅ Boost Mode: AI-to-AI chat
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
    const response = await api.post("/ask-ai-to-ai", payload);
    const { messages, summary, youtube, web } = response.data;

    return {
      messages: [
        {
          id: crypto.randomUUID(),
          sender: messages[0]?.sender ?? "openai",
          text: messages[0]?.answer ?? "⚠️ No response from first AI.",
        },
        {
          id: crypto.randomUUID(),
          sender: messages[1]?.sender ?? "anthropic",
          text: messages[1]?.answer ?? "⚠️ No response from second AI.",
        },
        {
          id: crypto.randomUUID(),
          sender: "anthropic",
          text: summary ?? "⚠️ No summary available.",
          isSummary: true,
        },
      ],
      youtube,
      web,
    };
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 422) {
      const detail = (error.response.data as { detail: any }).detail;
      console.error(
        "🔍 422 Validation Error:",
        JSON.stringify(detail, null, 2)
      );
    } else {
      console.error("❌ API Error from /ask-ai-to-ai:", error);
    }
    throw error;
  }
};

export const fetchPromptsByRole = async (roleId: number) => {
  try {
    const res = await api.get(`/prompts/by-role/${roleId}`);
    return res.data;
  } catch (error) {
    console.error(`❌ Failed to fetch prompts for role ${roleId}:`, error);
    throw error;
  }
};

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
    const response = await api.post("/upload", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });

    return response.data ?? null;
  } catch (error) {
    if (isAxiosError(error)) {
      console.error("❌ Upload failed:", error.message);
    } else {
      console.error("❌ Unknown upload error:", error);
    }
    return null;
  }
};

// ✅ FIXED: Ensures project_id is always a string
export const getChatHistory = async (
  projectId: string | number,
  roleId: string | number,
  chatSessionId: string
): Promise<{ messages: ChatMessage[] }> => {
  try {
    const res = await api.get("/chat/history", {
      params: {
        project_id: String(projectId), // ensure string
        role_id: Number(roleId),
        chat_session_id: chatSessionId,
      },
    });

    const raw = res.data.messages || [];

    const normalized: ChatMessage[] = raw.map((msg: any) => ({
      ...msg,
      project_id: String(msg.project_id),
      role_id: Number(msg.role_id),
      chat_session_id: msg.chat_session_id ?? "",
      sender: msg.sender,
      text: msg.text,
      isTyping: msg.isTyping ?? false,
      isSummary: msg.isSummary ?? false,
      id: `${msg.sender}-${crypto.randomUUID()}`,
    }));

    return { messages: normalized };
  } catch (error) {
    console.error("❌ Failed to fetch chat history:", error);
    throw error;
  }
};

export const getLastSession = async () => {
  const response = await fetch("/chat/last-session");
  if (!response.ok) throw new Error("Failed to get last session");
  return await response.json();
};
