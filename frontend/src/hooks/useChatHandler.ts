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
  abortRef: React.RefObject<AbortController | null>;
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

      // ✅ Add timeout tracking
      let timeoutWarning1: NodeJS.Timeout | null = null;
      let timeoutWarning2: NodeJS.Timeout | null = null;
      let timeoutFinal: NodeJS.Timeout | null = null;

      // Prepare abort controller for this turn
      setTyping(true);
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      // Snapshot the best-known session id
      const initialSessionId =
        chatSessionId || useChatStore.getState().chatSessionId || "";

      // Echo user message immediately
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

      // ✅ Progressive timeout warnings
      const { toast } = await import("../store/toastStore");

      timeoutWarning1 = setTimeout(() => {
        toast.info("⏳ Processing large response... Please wait.");
      }, 15000); // 15 seconds

      timeoutWarning2 = setTimeout(() => {
        toast.warning("⚠️ Still working... This is taking longer than usual.");
      }, 30000); // 30 seconds

      timeoutFinal = setTimeout(() => {
        toast.error("❌ Request timeout. Please try a shorter query.");
        abortRef.current?.abort();
        setTyping(false);
      }, 120000); // 2 minutes - HARD TIMEOUT

      // ✅ Auto-retry logic with exponential backoff
      const maxRetries = 3;
      let retryCount = 0;

      const attemptSend = async (): Promise<void> => {
        try {
          if (provider === "boost") {
            // ===== Boost path (Ai-to-Ai) =====
            const result = await sendAiToAiMessage(
              messageToSend,
              "openai",
              roleId,
              projectId,
              initialSessionId
            );

            // Clear timeouts on success
            if (timeoutWarning1) clearTimeout(timeoutWarning1);
            if (timeoutWarning2) clearTimeout(timeoutWarning2);
            if (timeoutFinal) clearTimeout(timeoutFinal);

            // In case backend rotated/created a new session, adopt it
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
            // ===== Normal /api/ask path =====
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

            // Clear timeouts on success
            if (timeoutWarning1) clearTimeout(timeoutWarning1);
            if (timeoutWarning2) clearTimeout(timeoutWarning2);
            if (timeoutFinal) clearTimeout(timeoutFinal);

            // Adopt server-provided session id if present
            if ((askRes as any)?.chat_session_id) {
              useChatStore
                .getState()
                .handleSessionIdUpdateFromAsk(
                  String((askRes as any).chat_session_id)
                );
            }
            const sessId =
              useChatStore.getState().chatSessionId || initialSessionId;

            // Multi-model
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

              // supplemental
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

            // Single provider
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

            // supplemental
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

          // Clear timeouts
          if (timeoutWarning1) clearTimeout(timeoutWarning1);
          if (timeoutWarning2) clearTimeout(timeoutWarning2);
          if (timeoutFinal) clearTimeout(timeoutFinal);

          // ✅ RETRY LOGIC
          if (retryCount < maxRetries) {
            // Check if error is retriable
            const isRetriable =
              isNetworkError(err) || isTimeoutError(err) || isServerError(err);

            if (isRetriable) {
              retryCount++;
              const delayMs = Math.pow(2, retryCount) * 1000; // 2s, 4s, 8s

              toast.warning(
                `🔄 Retry ${retryCount}/${maxRetries} in ${delayMs / 1000}s...`
              );

              await sleep(delayMs);

              // Recursive retry
              return attemptSend();
            }
          }

          // ✅ FINAL ERROR HANDLING
          const errorMsg = getErrorMessage(err);

          // Show toast notification
          if (is401Error(err)) {
            toast.error("🔑 " + errorMsg + " → Open Settings");
          } else if (isRateLimitError(err)) {
            toast.error("⏱️ " + errorMsg);
          } else {
            toast.error("❌ " + errorMsg);
          }

          // Add error message to chat
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

          throw err; // Re-throw for outer catch
        }
      };

      // ✅ START: Initial attempt
      try {
        await attemptSend();
      } catch (finalError) {
        console.error("❌ Final error after retries:", finalError);
      } finally {
        // Clean up timeouts
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
