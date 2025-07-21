import axios from "./apiClient";

export const sendAiMessage = async (question: string) => {
  const res = await axios.post("/ask", {
    question,
    // provider and role are injected via interceptor
  });
  return res.data;
};

export const sendAiToAiMessage = async (
  topic: string,
  starter: "openai" | "anthropic"
) => {
  const res = await axios.post("/ask-ai-to-ai", {
    topic,
    starter,
    // role is injected via interceptor
  });
  return res.data;
};
