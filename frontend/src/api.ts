import axios from "axios";

export const askLLM = async (question: string, provider: string) => {
  const response = await axios.post("http://127.0.0.1:8000/ask", {
    question,
    provider,
  });
  return response.data;
};
