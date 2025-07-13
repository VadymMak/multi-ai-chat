import { useState, useRef, useEffect } from "react"; // Added useEffect for state check
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

  // NEW: Use env var for backend URL with debug, no local fallback for test
  const backendUrl =
    process.env.REACT_APP_BACKEND_URL || "https://multi-ai-chat.onrender.com"; // Temporary hardcoded test value
  console.log("Backend URL from env:", process.env.REACT_APP_BACKEND_URL); // Debug env var

  // NEW: Effect to log and force reset isLoading if stuck
  useEffect(() => {
    if (isLoading) {
      console.log("isLoading is true, checking for stuck state...");
      const timer = setTimeout(() => {
        if (isLoading) {
          console.log("isLoading stuck, forcing to false");
          setIsLoading(false);
        }
      }, 65000); // Trigger after 65 seconds (beyond timeout)
      return () => clearTimeout(timer);
    }
  }, [isLoading]);

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
    console.log("isLoading set to true:", true); // Debug
    const url = `${backendUrl}/ask`;
    console.log("Sending request to:", url); // Log the exact URL being called
    console.log("Request payload:", { question, provider, role_id }); // Log request data

    try {
      const res = await axios.post(
        url,
        { question, provider, role_id },
        { timeout: 60000 } // Increased to 60 seconds to handle potential delays
      );
      console.log("Backend response:", res.data); // Log full response

      const { provider: p, answer, details, youtube_results } = res.data;
      if (!answer || (p === "all" && !Array.isArray(details))) {
        throw new Error("Invalid response structure from backend");
      }

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
      console.log("isLoading set to false in finally:", isLoading); // Debug
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
    console.log("isLoading set to true:", true); // Debug

    try {
      console.log("Attempt 1 to call /ask-ai-to-ai"); // Simplified to single attempt for now
      const url = `${backendUrl}/ask-ai-to-ai`;
      console.log("Sending request to:", url); // Log the exact URL
      console.log("Request payload:", { question, provider: "all", role_id }); // Log request data

      const res = await axios.post(
        url,
        { question, provider: "all", role_id },
        { timeout: 60000 } // Increased to 60 seconds
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
        console.error(
          `Axios error - Status: ${error.response?.status}, Data:`,
          errorDetails.response
        );
      }
      console.error("Error in askAiToAi:", errorDetails);
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
      console.log("isLoading set to false in finally:", isLoading); // Debug
      autoScroll();
    }
  };

  /* ------------------------------------------------- continue turn */
  const continueAiToAiTurn = async (
    conversation: Msg[],
    turn: number,
    role_id: string
  ) => {
    setIsLoading(true);
    console.log("isLoading set to true:", true); // Debug
    try {
      const url = `${backendUrl}/ask-ai-to-ai-turn`;
      console.log("Sending request to:", url); // Log the exact URL
      console.log("Request payload:", {
        messages: conversation,
        turn,
        role_id,
      }); // Log request data

      const res = await axios.post(
        url,
        { messages: conversation, turn, role_id },
        { timeout: 60000 } // Increased to 60 seconds
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
      console.log("isLoading set to false in finally:", isLoading); // Debug
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
