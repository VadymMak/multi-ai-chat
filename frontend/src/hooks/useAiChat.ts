import { useState, useRef } from "react";
import axios, { AxiosError } from "axios";
import { Model, Message, YouTubeResult } from "../types";

type Msg = Message & { youtubeResults?: YouTubeResult[] };

type ErrorDetails = {
  message: string;
  stack?: string;
  response?: any; // Allows optional response data (e.g., from AxiosError)
};

export const useAiChat = () => {
  /* ------------------------------------------------- state */
  const [messages, setMessages] = useState<Msg[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  // NEW: Use env var for backend URL (set in Netlify or .env for local)
  const backendUrl =
    process.env.REACT_APP_BACKEND_URL || "http://127.0.0.1:8000"; // Fallback to local for dev

  /* ------------------------------------------------- helpers */
  const pushMessage = (msg: Msg) => {
    console.log("Pushing message:", msg); // Debug log for pushed message
    setMessages((prev) => [...prev, msg]);
  };

  const autoScroll = () => {
    setTimeout(() => {
      if (chatContainerRef.current) {
        chatContainerRef.current.scrollTop =
          chatContainerRef.current.scrollHeight;
      }
    }, 100); // CHANGED: Slightly increased timeout for reliability
  };

  /* ------------------------------------------------- ask /all or single */
  const askLLM = async (question: string, provider: Model, role_id: string) => {
    pushMessage({
      sender: "user",
      text: question,
      timestamp: new Date().toISOString(),
    });
    setIsLoading(true);

    try {
      const res = await axios.post(
        `${backendUrl}/ask`, // CHANGED: Use dynamic backendUrl
        { question, provider, role_id },
        { timeout: 20000 } // Increased to 20 seconds
      );
      console.log("Backend response:", res.data); // Debug log for full response

      const { provider: p, answer, details, youtube_results } = res.data;
      if (!answer || (p === "all" && !Array.isArray(details))) {
        throw new Error("Invalid response structure from backend");
      }

      /* if “all”, render both assistants first, then the combined answer */
      if (p === "all" && Array.isArray(details)) {
        details.forEach((d) =>
          pushMessage({
            sender: "ai",
            aiModel: d.model,
            text: d.answer || "No response",
            timestamp: new Date().toISOString(),
          })
        );
      }

      pushMessage({
        sender: "ai",
        aiModel: p === "all" ? "final" : p,
        text: answer,
        youtubeResults: Array.isArray(youtube_results) ? youtube_results : [],
        timestamp: new Date().toISOString(),
      });

      return res.data;
    } catch (error) {
      const errorDetails: ErrorDetails =
        error instanceof Error
          ? { message: error.message, stack: error.stack }
          : { message: "Unknown error" };
      if (error instanceof AxiosError) {
        errorDetails.response = error.response?.data;
        // NEW: Log status code for better debugging
        console.error(
          `Axios error - Status: ${error.response?.status}, Data:`,
          errorDetails.response
        );
      }
      console.error("Error in askLLM:", errorDetails);
      const errorMessage =
        error instanceof Error ? error.message : "An unknown error occurred";
      pushMessage({
        sender: "ai",
        aiModel: "final",
        text: `Error: ${errorMessage}`,
        timestamp: new Date().toISOString(),
      });
    } finally {
      setIsLoading(false);
      autoScroll();
    }
  };

  /* ------------------------------------------------- ask-ai-to-ai */
  const askAiToAi = async (question: string, role_id: string) => {
    pushMessage({
      sender: "user",
      text: question,
      timestamp: new Date().toISOString(),
    });
    setIsLoading(true);

    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        console.log(`Attempt ${attempt} to call /ask-ai-to-ai`);
        const res = await axios.post(
          `${backendUrl}/ask-ai-to-ai`, // CHANGED: Use dynamic backendUrl
          { question, provider: "all", role_id },
          { timeout: 60000 } // Increased to 20 seconds
        );
        console.log("Backend response (askAiToAi):", res.data); // Debug log for full response

        const { details, answer, youtube_results } = res.data;
        if (!answer || !Array.isArray(details)) {
          throw new Error("Invalid response structure from backend");
        }

        if (Array.isArray(details)) {
          details.forEach((d) =>
            pushMessage({
              sender: "ai",
              aiModel: d.model,
              text: d.answer || "No response",
              timestamp: new Date().toISOString(),
            })
          );
        }

        pushMessage({
          sender: "ai",
          aiModel: "final",
          text: answer || "No summary received.",
          youtubeResults: Array.isArray(youtube_results) ? youtube_results : [],
          timestamp: new Date().toISOString(),
        });

        return res.data;
      } catch (error) {
        const errorDetails: ErrorDetails =
          error instanceof Error
            ? { message: error.message, stack: error.stack }
            : { message: "Unknown error" };
        if (error instanceof AxiosError) {
          errorDetails.response = error.response?.data;
          // NEW: Log status code for better debugging
          console.error(
            `Axios error - Status: ${error.response?.status}, Data:`,
            errorDetails.response
          );
          if (attempt === 2) {
            console.error(
              `Final attempt failed: Error in askAiToAi:`,
              errorDetails
            );
          } else {
            console.warn(`Attempt ${attempt} failed, retrying:`, errorDetails);
            await new Promise((resolve) => setTimeout(resolve, 1000)); // Wait 1 second before retry
            continue;
          }
        }
        const errorMessage =
          error instanceof Error ? error.message : "An unknown error occurred";
        pushMessage({
          sender: "ai",
          aiModel: "final",
          text: `Error: ${errorMessage}`,
          timestamp: new Date().toISOString(),
        });
        break; // Exit the loop on error if not retrying
      }
    } // End of for loop
    setIsLoading(false); // Moved outside the loop to ensure it runs
    autoScroll(); // Moved outside the loop to ensure it runs
  };

  /* ------------------------------------------------- continue turn */
  const continueAiToAiTurn = async (
    conversation: Msg[], // CHANGED: Typed as Msg[] instead of any[] for safety
    turn: number,
    role_id: string
  ) => {
    setIsLoading(true);
    try {
      const res = await axios.post(
        `${backendUrl}/ask-ai-to-ai-turn`, // CHANGED: Use dynamic backendUrl
        { messages: conversation, turn, role_id },
        { timeout: 20000 } // Increased to 20 seconds
      );
      console.log("Backend response (continueAiToAiTurn):", res.data); // Debug log for full response

      const last = res.data.conversation.at(-1);
      if (!last || !last.answer) {
        throw new Error("Invalid conversation data from backend");
      }
      pushMessage({
        sender: "ai",
        aiModel: last.model || "final",
        text: last.answer || "No answer.",
        timestamp: new Date().toISOString(),
      });
      return res.data;
    } catch (error) {
      const errorDetails: ErrorDetails =
        error instanceof Error
          ? { message: error.message, stack: error.stack }
          : { message: "Unknown error" };
      if (error instanceof AxiosError) {
        errorDetails.response = error.response?.data;
        // NEW: Log status code for better debugging
        console.error(
          `Axios error - Status: ${error.response?.status}, Data:`,
          errorDetails.response
        );
      }
      console.error("Error in continueAiToAiTurn:", errorDetails);
      const errorMessage =
        error instanceof Error ? error.message : "An unknown error occurred";
      pushMessage({
        sender: "ai",
        aiModel: "final",
        text: `Error: ${errorMessage}`,
        timestamp: new Date().toISOString(),
      });
    } finally {
      setIsLoading(false);
      autoScroll();
    }
  };

  return {
    messages,
    isLoading,
    askLLM,
    askAiToAi,
    continueAiToAiTurn,
    chatContainerRef,
  };
};
