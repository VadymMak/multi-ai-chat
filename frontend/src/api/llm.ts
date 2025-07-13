import axios from "axios";

export async function askAiToAi(question: string) {
  const res = await axios.post("http://127.0.0.1:8000/ask-ai-to-ai", {
    question,
    provider: "all",
  });
  return res.data; // { provider: "all", conversation: [...] }
}
