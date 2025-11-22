// File: src/hooks/useChatHandler.ts
import { useCallback } from "react";
import { v4 as uuidv4 } from "uuid";
import type { Sender, ChatMessage } from "../types/chat";
import type { RenderKind } from "../types/chat";
import { renderSupplementary } from "../utils/renderSupplementary";
import { useChatStore } from "../store/chatStore";

interface UseChatHandlerParams {
  input: string;
  setInput: (val: string) => void;
  abortRef: React.MutableRefObject<AbortController | null>;
  provider: string | null; // "boost" or null
  typedProvider: "openai" | "anthropic" | "all" | null;
  roleId: number | null;
  projectId: string | number;
  chatSessionId?: string;
  setTyping: (val: boolean) => void;
  addMessage: (msg: ChatMessage) => void;
  streamText: (id: string, text: string, signal?: AbortSignal) => Promise<void>;
  sendAiMessage: typeof import("../services/aiApi").sendAiMessage;
  sendAiToAiMessage: typeof import("../services/aiApi").sendAiToAiMessage;
}

/** Optional per-send overrides */
type SendOverrides = {
  /** legacy from UI buttons; we'll map to output_mode/presentation */
  kind?: RenderKind;
  /** new explicit fields the backend understands */
  output_mode?: "plain" | "doc" | "code";
  presentation?: "default" | "poem_plain" | "poem_code";
  language?: string | null;
  filename?: string | null;
};

// ============================================================================
// CODE GENERATION DETECTION
// ============================================================================

const isCodeGenerationRequest = (query: string): boolean => {
  const lower = query.toLowerCase();

  // ✅ ENHANCED direct triggers - ADD THESE LINES
  const directTriggers = [
    "create app",
    "build app",
    "make app",
    "create todo",
    "build todo",
    "make todo",
    "create website",
    "build website",
    "write code for",
    "generate code for",
    "implement a",
    "develop a",

    // ✅✅✅ ADD THESE NEW TRIGGERS ✅✅✅
    "provide code",
    "provide the code",
    "provide me code",
    "provide me the code",
    "give me code",
    "give code",
    "give me the code",
    "show me code",
    "show code",
    "show the code",
    "send me code",
    "send code",
    "can you code",
    "can you create",
    "can you build",
    "can you make",
  ];

  if (directTriggers.some((trigger) => lower.includes(trigger))) {
    console.log("✅ [Detection] Matched trigger for:", lower); // ← Add debug
    return true;
  }

  // ✅ Keyword-based (existing logic)
  const codeKeywords = [
    "create",
    "build",
    "make",
    "generate",
    "write",
    "develop",
    "implement",
    "code",
    "program",
  ];

  const projectKeywords = [
    "app",
    "application",
    "website",
    "page",
    "component",
    "function",
    "class",
    "module",
    "script",
    "todo",
    "frontend",
    "backend",
    "full stack",
    "fullstack",
    "node",
    "nodejs",
    "react",
    "vue",
    "angular",
    "api",
    "server",
    "express",
    "fastapi",
  ];

  const hasCodeKeyword = codeKeywords.some((kw) => lower.includes(kw));
  const hasProjectKeyword = projectKeywords.some((kw) => lower.includes(kw));

  const matched = hasCodeKeyword && hasProjectKeyword;

  if (matched) {
    console.log("✅ [Detection] Matched keywords for:", lower); // ← Add debug
  } else {
    console.log("❌ [Detection] No match for:", lower); // ← Add debug
  }

  return matched;
};

// ============================================================================
// ERROR DETECTION HELPERS
// ============================================================================

const isNetworkError = (error: any): boolean => {
  return (
    error?.message?.includes("network") ||
    error?.message?.includes("fetch") ||
    error?.code === "ERR_NETWORK" ||
    error?.name === "NetworkError" ||
    !navigator.onLine
  );
};

const isTimeoutError = (error: any): boolean => {
  return (
    error?.message?.includes("timeout") ||
    error?.code === "ECONNABORTED" ||
    error?.name === "TimeoutError"
  );
};

const is401Error = (error: any): boolean => {
  return error?.status === 401 || error?.response?.status === 401;
};

const isRateLimitError = (error: any): boolean => {
  return (
    error?.status === 429 ||
    error?.response?.status === 429 ||
    error?.message?.includes("rate limit")
  );
};

const isServerError = (error: any): boolean => {
  const status = error?.status || error?.response?.status;
  return status >= 500 && status < 600;
};

// Sleep utility for retry delays
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// Get user-friendly error message
const getErrorMessage = (error: any): string => {
  if (isNetworkError(error)) {
    return "Network connection lost. Please check your internet.";
  }
  if (isTimeoutError(error)) {
    return "Request timeout. The AI is taking too long to respond.";
  }
  if (is401Error(error)) {
    return "Invalid API key. Please check your settings.";
  }
  if (isRateLimitError(error)) {
    return "Rate limit exceeded. Please wait a moment.";
  }
  if (isServerError(error)) {
    return "Server error. Please try again in a moment.";
  }

  // Generic error
  const msg = error?.message || error?.detail || String(error);
  return msg.slice(0, 100); // Truncate long errors
};

// ============================================================================
// MODE DERIVATION
// ============================================================================

function deriveMode(
  over?: SendOverrides
): {
  output_mode?: "plain" | "doc" | "code";
  presentation?: "default" | "poem_plain" | "poem_code";
} {
  if (over?.output_mode || over?.presentation) {
    return {
      output_mode: over.output_mode,
      presentation: over.presentation ?? "default",
    };
  }
  switch (over?.kind) {
    case "plain":
      return { output_mode: "plain", presentation: "default" };
    case "markdown":
      return { output_mode: "doc", presentation: "default" };
    case "code":
      return { output_mode: "code", presentation: "default" };
    case "poem_plain":
      return { output_mode: "plain", presentation: "poem_plain" };
    case "poem_code":
      return { output_mode: "code", presentation: "poem_code" };
    default:
      return { output_mode: "doc", presentation: "default" };
  }
}

// ============================================================================
// STREAMING REQUEST HANDLER
// ============================================================================

const handleStreamingRequest = async (
  query: string,
  provider: "openai" | "anthropic",
  roleId: number,
  projectId: string | number,
  chatSessionId: string,
  addMessage: (msg: ChatMessage) => void
): Promise<void> => {
  const { toast } = await import("../store/toastStore");

  toast.info("⏳ Generating code... This may take 1-2 minutes.");

  const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

  try {
    const response = await fetch(`${API_URL}/ask-stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("token") || ""}`,
      },
      body: JSON.stringify({
        query,
        provider,
        role_id: roleId,
        project_id: projectId,
        chat_session_id: chatSessionId,
      }),
    });

    if (!response.ok) {
      throw new Error(`Streaming failed: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("No reader available");
    }

    const decoder = new TextDecoder();
    let accumulated = "";
    const streamingMsgId = `ai-${uuidv4()}`;

    // ✅ Multi-file tracking
    const files = new Map<string, string>();
    let currentFile: string | null = null;
    let totalFiles = 0;

    // ✅ Add message with BOTH flags
    addMessage({
      id: streamingMsgId,
      sender: provider,
      text: "",
      isStreaming: true,
      isTyping: true,
      role_id: roleId,
      project_id: String(projectId),
      chat_session_id: chatSessionId,
    } as ChatMessage);

    console.log("🌊 [Streaming] Started for message:", streamingMsgId);

    // ✅ Throttled update mechanism
    let lastUpdateTime = Date.now();
    const UPDATE_INTERVAL = 100; // ms

    const scheduleUpdate = (text: string) => {
      const now = Date.now();

      if (now - lastUpdateTime >= UPDATE_INTERVAL || text.length % 200 === 0) {
        useChatStore.getState().updateMessageText(streamingMsgId, text);
        lastUpdateTime = now;
      }
    };

    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        console.log("✅ [Streaming] Done");
        // Final update
        useChatStore.getState().updateMessageText(streamingMsgId, accumulated);
        break;
      }

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split("\n");

      for (const line of lines) {
        if (!line.trim() || !line.startsWith("data: ")) continue;

        const data = line.substring(6).trim();
        if (data === "[DONE]") continue;

        try {
          const parsed = JSON.parse(data);

          // ✅ Handle different event types
          if (parsed.event === "chunk") {
            accumulated += parsed.data.content;
            scheduleUpdate(accumulated);
          } else if (parsed.event === "files_detected") {
            totalFiles = parsed.data.total_files;
            toast.info(`📁 Detected ${totalFiles} files...`);
          } else if (parsed.event === "file_start") {
            const filename: string = parsed.data.filename || "unknown.txt";
            currentFile = filename;
            files.set(filename, "");
            toast.info(
              `📝 Generating ${filename} (${parsed.data.index}/${parsed.data.total})`
            );
          } else if (parsed.event === "file_chunk") {
            if (currentFile) {
              const existing = files.get(currentFile) || "";
              files.set(currentFile, existing + parsed.data.content);

              // Render all files
              const allFiles = Array.from(files.entries())
                .map(
                  ([name, content]) =>
                    `### 📄 ${name}\n\`\`\`\n${content}\n\`\`\``
                )
                .join("\n\n");

              scheduleUpdate(allFiles);
            }
          } else if (parsed.event === "file_end") {
            toast.success(`✅ ${parsed.data.filename} complete!`);
          } else if (parsed.event === "done") {
            console.log("✅ [Streaming] Complete event received");

            // Remove flags
            const messages = useChatStore.getState().messages;
            const updatedMessages = messages.map((msg) =>
              msg.id === streamingMsgId
                ? {
                    ...msg,
                    text: accumulated,
                    isStreaming: false,
                    isTyping: false,
                  }
                : msg
            );
            useChatStore.getState().setMessages(updatedMessages);

            toast.success(
              `✅ Code generated successfully!${
                totalFiles > 1 ? ` (${totalFiles} files)` : ""
              }`
            );
          } else if (parsed.event === "error") {
            throw new Error(parsed.data?.error || "Streaming error");
          }
        } catch (parseError) {
          console.error("❌ [Streaming] Parse error:", parseError);
        }
      }
    }
  } catch (error) {
    console.error("❌ [Streaming] Error:", error);
    toast.error("❌ Failed to generate code. Please try again.");
    throw error;
  }
};

// ============================================================================
// MAIN HOOK
// ============================================================================

export const useChatHandler = ({
  input,
  setInput,
  abortRef,
  provider,
  typedProvider,
  roleId,
  projectId,
  chatSessionId,
  setTyping,
  addMessage,
  streamText,
  sendAiMessage,
  sendAiToAiMessage,
}: UseChatHandlerParams) => {
  const handleSend = useCallback(
    async (text?: string, overrides?: SendOverrides) => {
      const messageToSend = (text ?? input).trim();
      if (!messageToSend) return;
      if (!roleId || roleId <= 0) return;
      if (
        projectId === null ||
        projectId === undefined ||
        String(projectId).trim() === ""
      )
        return;

      // Declare initialSessionId at the start
      const initialSessionId =
        chatSessionId || useChatStore.getState().chatSessionId || "";

      // ✅ AUTO-DETECT CODE GENERATION AND USE STREAMING
      if (isCodeGenerationRequest(messageToSend)) {
        console.log("=".repeat(60));
        console.log("🌊 [Code Generation] Detected - using streaming");
        console.log("📝 [DEBUG] Query:", messageToSend);
        console.log("📝 [DEBUG] Role ID:", roleId);
        console.log("📝 [DEBUG] Project ID:", projectId);
        console.log("📝 [DEBUG] Session ID:", initialSessionId);
        console.log("=".repeat(60));

        setTyping(true);
        abortRef.current?.abort();
        abortRef.current = new AbortController();

        // Echo user message
        const userMessage: ChatMessage = {
          id: `user-${uuidv4()}`,
          sender: "user",
          text: messageToSend,
          chat_session_id: initialSessionId,
          role_id: roleId,
          project_id: String(projectId),
        };

        console.log("📤 [DEBUG] User message object:");
        console.log(JSON.stringify(userMessage, null, 2));
        console.log("📤 [DEBUG] Store BEFORE addMessage:");
        console.log(
          "  - Messages count:",
          useChatStore.getState().messages.length
        );
        console.log(
          "  - Last 3 messages:",
          useChatStore
            .getState()
            .messages.slice(-3)
            .map((m) => ({
              id: m.id,
              sender: m.sender,
              text: m.text?.substring(0, 30),
            }))
        );

        addMessage(userMessage);

        console.log("✅ [DEBUG] Store AFTER addMessage:");
        console.log(
          "  - Messages count:",
          useChatStore.getState().messages.length
        );
        console.log(
          "  - Last 3 messages:",
          useChatStore
            .getState()
            .messages.slice(-3)
            .map((m) => ({
              id: m.id,
              sender: m.sender,
              text: m.text?.substring(0, 30),
            }))
        );
        console.log("=".repeat(60));

        setInput("");

        try {
          await handleStreamingRequest(
            messageToSend,
            (typedProvider === "all" ? "openai" : typedProvider) as
              | "openai"
              | "anthropic",
            roleId,
            projectId,
            initialSessionId,
            addMessage
          );
        } catch (error) {
          console.error("❌ Streaming failed:", error);
        } finally {
          setTyping(false);
        }

        return;
      }

      // ✅ NON-STREAMING PATH (normal requests)
      let timeoutWarning1: NodeJS.Timeout | null = null;
      let timeoutWarning2: NodeJS.Timeout | null = null;
      let timeoutFinal: NodeJS.Timeout | null = null;

      setTyping(true);
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      // Echo user message for non-streaming requests
      const userMessage: ChatMessage = {
        id: `user-${uuidv4()}`,
        sender: "user",
        text: messageToSend,
        chat_session_id: initialSessionId,
        role_id: roleId,
        project_id: String(projectId),
      };
      addMessage(userMessage);
      setInput("");

      // Progressive timeout warnings
      const { toast } = await import("../store/toastStore");

      timeoutWarning1 = setTimeout(() => {
        toast.info("⏳ Processing large response... Please wait.");
      }, 15000);

      timeoutWarning2 = setTimeout(() => {
        toast.warning("⚠️ Still working... This is taking longer than usual.");
      }, 30000);

      timeoutFinal = setTimeout(() => {
        toast.error("❌ Request timeout. Please try a shorter query.");
        abortRef.current?.abort();
        setTyping(false);
      }, 120000);

      const maxRetries = 3;
      let retryCount = 0;

      const attemptSend = async (): Promise<void> => {
        try {
          if (provider === "boost") {
            const result = await sendAiToAiMessage(
              messageToSend,
              "openai",
              roleId,
              projectId,
              initialSessionId
            );

            if (timeoutWarning1) clearTimeout(timeoutWarning1);
            if (timeoutWarning2) clearTimeout(timeoutWarning2);
            if (timeoutFinal) clearTimeout(timeoutFinal);

            if ((result as any)?.chat_session_id) {
              useChatStore
                .getState()
                .handleSessionIdUpdateFromAsk(
                  String((result as any).chat_session_id)
                );
            }
            const sessId =
              useChatStore.getState().chatSessionId || initialSessionId;

            for (const { sender, text, isSummary } of result.messages ?? []) {
              const id = `${sender}-${uuidv4()}`;
              addMessage({
                id,
                sender: (sender as Sender) ?? "anthropic",
                text: "",
                isTyping: true,
                isSummary,
                chat_session_id: sessId,
                role_id: roleId,
                project_id: String(projectId),
              });
              await streamText(
                id,
                text || "⚠️ Empty",
                abortRef.current?.signal
              );
            }

            if (result.youtube?.length) {
              await renderSupplementary(
                "youtube",
                result.youtube,
                (m) =>
                  addMessage({
                    ...m,
                    chat_session_id: sessId,
                    role_id: roleId,
                    project_id: String(projectId),
                  } as ChatMessage),
                (id, t, sig) => streamText(id, t, sig),
                abortRef.current?.signal
              );
            }
            if (result.web?.length) {
              await renderSupplementary(
                "web",
                result.web,
                (m) =>
                  addMessage({
                    ...m,
                    chat_session_id: sessId,
                    role_id: roleId,
                    project_id: String(projectId),
                  } as ChatMessage),
                (id, t, sig) => streamText(id, t, sig),
                abortRef.current?.signal
              );
            }
            return;
          }

          if (typedProvider) {
            const mode = deriveMode(overrides);

            const askRes = await sendAiMessage(
              messageToSend,
              typedProvider,
              roleId,
              projectId,
              initialSessionId,
              {
                ...overrides,
                ...mode,
              }
            );

            if (timeoutWarning1) clearTimeout(timeoutWarning1);
            if (timeoutWarning2) clearTimeout(timeoutWarning2);
            if (timeoutFinal) clearTimeout(timeoutFinal);

            if ((askRes as any)?.chat_session_id) {
              useChatStore
                .getState()
                .handleSessionIdUpdateFromAsk(
                  String((askRes as any).chat_session_id)
                );
            }
            const sessId =
              useChatStore.getState().chatSessionId || initialSessionId;

            if (typedProvider === "all") {
              for (const m of askRes.messages ?? []) {
                const id = `ai-${uuidv4()}`;
                const sender = (m.sender as Sender) || "openai";
                const textOut = String(m.text ?? "");
                const sources = (m as any).sources ?? (askRes as any).sources;
                const render = (m as any).render;

                addMessage({
                  id,
                  sender,
                  text: "",
                  isTyping: true,
                  ...(render ? { render } : {}),
                  ...(sources ? ({ sources } as any) : {}),
                  chat_session_id: sessId,
                  role_id: roleId,
                  project_id: String(projectId),
                });

                await streamText(
                  id,
                  textOut || "🤖 No response",
                  abortRef.current?.signal
                );
              }

              if ((askRes as any)?.youtube?.length) {
                await renderSupplementary(
                  "youtube",
                  (askRes as any).youtube,
                  (m) =>
                    addMessage({
                      ...m,
                      chat_session_id: sessId,
                      role_id: roleId,
                      project_id: String(projectId),
                    } as ChatMessage),
                  (id, t, sig) => streamText(id, t, sig),
                  abortRef.current?.signal
                );
              }
              if ((askRes as any)?.web?.length) {
                await renderSupplementary(
                  "web",
                  (askRes as any).web,
                  (m) =>
                    addMessage({
                      ...m,
                      chat_session_id: sessId,
                      role_id: roleId,
                      project_id: String(projectId),
                    } as ChatMessage),
                  (id, t, sig) => streamText(id, t, sig),
                  abortRef.current?.signal
                );
              }

              return;
            }

            const m = askRes.messages?.[0] as any;
            const id = `ai-${uuidv4()}`;
            const textOut = String(m?.text ?? "");
            const sources = m?.sources ?? (askRes as any)?.sources;
            const render = m?.render;

            addMessage({
              id,
              sender: typedProvider,
              text: "",
              isTyping: true,
              ...(render ? { render } : {}),
              ...(sources ? ({ sources } as any) : {}),
              chat_session_id: sessId,
              role_id: roleId,
              project_id: String(projectId),
            });

            await streamText(
              id,
              textOut || "🤖 No response",
              abortRef.current?.signal
            );

            if ((askRes as any)?.youtube?.length) {
              await renderSupplementary(
                "youtube",
                (askRes as any).youtube,
                (m2) =>
                  addMessage({
                    ...m2,
                    chat_session_id: sessId,
                    role_id: roleId,
                    project_id: String(projectId),
                  } as ChatMessage),
                (id2, t2, sig2) => streamText(id2, t2, sig2),
                abortRef.current?.signal
              );
            }
            if ((askRes as any)?.web?.length) {
              await renderSupplementary(
                "web",
                (askRes as any).web,
                (m2) =>
                  addMessage({
                    ...m2,
                    chat_session_id: sessId,
                    role_id: roleId,
                    project_id: String(projectId),
                  } as ChatMessage),
                (id2, t2, sig2) => streamText(id2, t2, sig2),
                abortRef.current?.signal
              );
            }
          }
        } catch (err) {
          console.error("❌ send failed:", err);

          if (timeoutWarning1) clearTimeout(timeoutWarning1);
          if (timeoutWarning2) clearTimeout(timeoutWarning2);
          if (timeoutFinal) clearTimeout(timeoutFinal);

          if (retryCount < maxRetries) {
            const isRetriable =
              isNetworkError(err) || isTimeoutError(err) || isServerError(err);

            if (isRetriable) {
              retryCount++;
              const delayMs = Math.pow(2, retryCount) * 1000;

              toast.warning(
                `🔄 Retry ${retryCount}/${maxRetries} in ${delayMs / 1000}s...`
              );

              await sleep(delayMs);
              return attemptSend();
            }
          }

          const errorMsg = getErrorMessage(err);

          if (is401Error(err)) {
            toast.error("🔑 " + errorMsg + " → Open Settings");
          } else if (isRateLimitError(err)) {
            toast.error("⏱️ " + errorMsg);
          } else {
            toast.error("❌ " + errorMsg);
          }

          const sessId =
            useChatStore.getState().chatSessionId || initialSessionId;
          addMessage({
            id: `error-${uuidv4()}`,
            sender: "system",
            text: `⚠️ **Error:** ${errorMsg}\n\n*Try a different model or retry later.*`,
            chat_session_id: sessId,
            role_id: roleId,
            project_id: String(projectId),
          } as ChatMessage);

          throw err;
        }
      };

      try {
        await attemptSend();
      } catch (finalError) {
        console.error("❌ Final error after retries:", finalError);
      } finally {
        if (timeoutWarning1) clearTimeout(timeoutWarning1);
        if (timeoutWarning2) clearTimeout(timeoutWarning2);
        if (timeoutFinal) clearTimeout(timeoutFinal);
        setTyping(false);
      }
    },
    [
      input,
      provider,
      typedProvider,
      roleId,
      projectId,
      chatSessionId,
      setTyping,
      addMessage,
      streamText,
      sendAiMessage,
      sendAiToAiMessage,
      setInput,
      abortRef,
    ]
  );

  return { handleSend };
};
