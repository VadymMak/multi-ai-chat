import axios from "./apiClient";
import type { AxiosError } from "axios";

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

// ✅ Type guard to check if error is an AxiosError
const isAxiosError = (error: unknown): error is AxiosError => {
  return typeof error === "object" && error !== null && "isAxiosError" in error;
};

// ✅ AI request to single model
export const sendAiMessage = async (
  question: string,
  provider: "openai" | "anthropic" | "all",
  role: string | number,
  project_id: string | number
) => {
  const payload = {
    query: question,
    provider,
    role_id: Number(role),
    project_id: String(project_id),
  };

  console.log("📤 POST /ask payload:", payload);
  console.log("🔎 typeof role:", typeof payload.role_id); // should be 'number'
  console.log("🔎 typeof project_id:", typeof payload.project_id); // should be 'string'

  try {
    const res = await axios.post("/ask", payload);
    return res.data;
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 422) {
      const detail = (error.response.data as { detail: any }).detail;
      console.error("❌ Validation Error (422) from /ask:", detail);
    } else {
      console.error("❌ API Error from /ask:", error);
    }
    throw error;
  }
};

// ✅ Boost mode
export const sendAiToAiMessage = async (
  topic: string,
  starter: "openai" | "anthropic",
  role: string | number,
  project_id: string | number
) => {
  const payload = {
    topic,
    starter,
    role_id: Number(role),
    project_id: String(project_id),
  };

  console.log("📤 POST /ask-ai-to-ai payload:", payload);
  console.log("🔎 typeof role:", typeof payload.role_id);
  console.log("🔎 typeof project_id:", typeof payload.project_id);

  try {
    const response = await axios.post("/ask-ai-to-ai", payload);
    const { messages, summary, youtube, web } = response.data;

    return {
      messages: [
        {
          id: crypto.randomUUID(),
          sender: messages[0].sender,
          text: messages[0].answer,
        },
        {
          id: crypto.randomUUID(),
          sender: messages[1].sender,
          text: messages[1].answer,
        },
        {
          id: crypto.randomUUID(),
          sender: "anthropic",
          text: summary,
          isSummary: true,
        },
      ],
      youtube,
      web,
    };
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 422) {
      const detail = (error.response.data as { detail: any }).detail;
      console.error("❌ Validation Error (422) from /ask-ai-to-ai:", detail);
    } else {
      console.error("❌ API Error from /ask-ai-to-ai:", error);
    }
    throw error;
  }
};
