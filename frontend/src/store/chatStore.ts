// File: src/store/chatStore.ts
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { v4 as uuidv4 } from "uuid";
import { createSelectors } from "./createSelectors";
import type { ChatMessage } from "../types/chat";
import api from "../services/api";

/** Utils: revoke blob: URLs to avoid memory leaks */
const revokeAttachmentUrls = (msgs: ChatMessage[]) => {
  for (const m of msgs) {
    const atts = (m as any).attachments as Array<{ url?: string }> | undefined;
    if (!atts?.length) continue;
    for (const att of atts) {
      try {
        const url = att?.url;
        if (typeof url === "string" && url.startsWith("blob:")) {
          URL.revokeObjectURL(url);
        }
      } catch {
        /* ignore */
      }
    }
  }
};

export interface LastSessionMarker {
  projectId: number;
  roleId: number;
  chatSessionId: string;
  roleName?: string;
}

export interface ChatState {
  messages: ChatMessage[];
  summaries?: { summary: string; timestamp?: string }[];
  isTyping: boolean;
  noHistory: boolean;
  chatSessionId: string | null;
  lastSessionMarker: LastSessionMarker | null;

  // Token budget tracking
  totalTokens: number;
  maxTokens: number;

  // Summary tracking
  hasSummary: boolean;
  lastSummaryAt: string | null;

  // Claude model selection
  claudeModel: "claude-sonnet-4-20250514" | "claude-opus-4-20250514";
  setClaudeModel: (
    model: "claude-sonnet-4-20250514" | "claude-opus-4-20250514"
  ) => void;

  /** internal one-shot skip */
  manualSessionSyncFlag: boolean;
  /** consume & reset; returns true if skip should happen this tick */
  consumeManualSessionSync: () => boolean;

  /** set the one-shot flag */
  setConsumeManualSessionSync: (value: boolean) => void;

  /** becomes true after session init finishes */
  sessionReady: boolean;

  // message ops
  addMessage: (msg: ChatMessage) => void;
  setTyping: (typing: boolean) => void;
  updateMessageText: (id: string, newText: string) => void;
  markMessageDone: (id: string) => void;
  clearMessages: () => void;
  deleteMessage: (id: string) => void;
  updateMessageOnServer: (id: string, newText: string) => Promise<void>;
  deleteMessageOnServer: (id: string) => Promise<void>;
  regenerateMessageOnServer: (id: string) => Promise<void>;

  // session ops
  setChatSessionId: (id: string | null) => void;
  setLastSessionMarker: (marker: LastSessionMarker | null) => void;
  setMessages: (msgs: ChatMessage[]) => void;
  setSessionReady: (ready: boolean) => void;

  // Token budget tracking
  setTokenUsage: (used: number, max: number) => void;

  // Summary tracking
  setSummaryCreated: (summaryId: number, timestamp: string) => void;

  // Back-compat helpers
  setNoHistory?: (value: boolean) => void;
  replaceMessages?: (msgs: ChatMessage[]) => void;

  waitForSessionReady: (
    roleId: number,
    projectId: number,
    timeoutMs?: number
  ) => Promise<string>;

  initializeChatSession: (projectId: number, roleId: number) => Promise<void>;

  rotateChatSessionAfterSummary: (
    projectId: number,
    roleId: number,
    newChatSessionId: string,
    dividerMessage?: ChatMessage
  ) => Promise<void>;

  restoreSessionFromMarker: () => Promise<boolean>;
  loadOrInitSessionForRoleProject: (
    roleId: number,
    projectId: number
  ) => Promise<void>;
  syncAndInitSession: (
    roleId: number,
    projectId: number
  ) => Promise<{ chat_session_id: string }>;

  resetFetchTracking: () => void;

  isSessionSynced: () => boolean;
  handleSessionIdUpdateFromAsk: (sessionId: string) => void;
}

// === Internal session lock (global) ===
let sessionLock: Promise<void> | null = null;
let latestSessionVersion = 0;
let pendingSessionResolvers: Array<() => void> = [];

const log = (...args: any[]) => {
  if (process.env.NODE_ENV !== "production") console.debug(...args);
};

/** Ensure each message has an id */
const withIds = (msgs: any[] | undefined | null): ChatMessage[] => {
  if (!Array.isArray(msgs)) return [];
  return msgs.map((m, idx) => {
    // ✅ Prefer backend database ID if present
    const id = m?.id
      ? String(m.id) // Backend может вернуть number, конвертируем в string
      : `msg-${idx}-${uuidv4()}`; // Fallback для новых сообщений
    return { ...m, id } as ChatMessage;
  });
};

/** Replace a single item by id with minimal allocations */
function replaceById<T extends { id?: string }>(
  list: T[],
  id: string,
  updater: (prev: T) => T
) {
  const idx = list.findIndex((m) => m?.id === id);
  if (idx < 0) return list;
  const prev = list[idx];
  const next = updater(prev);
  if (next === prev) return list;
  const copy = list.slice();
  copy[idx] = next;
  return copy;
}

/** Remove a single item by id with minimal allocations */
function removeById<T extends { id?: string }>(list: T[], id: string) {
  const idx = list.findIndex((m) => m?.id === id);
  if (idx < 0) return list;
  const copy = list.slice();
  copy.splice(idx, 1);
  return copy;
}

/** ---------- NEW: per-(role,project,limit) one-flight guard ---------- */
const lastSessionInflight = new Map<string, Promise<any>>();
function fetchLastSessionByRoleOnce(
  roleId: number,
  projectId: number,
  limit = 200
) {
  const key = `${roleId}:${projectId}:${limit}`;
  const existing = lastSessionInflight.get(key);
  if (existing) return existing;

  const p = api
    .get("/chat/last-session-by-role", {
      params: { role_id: roleId, project_id: projectId, limit },
    })
    .finally(() => {
      // clear only if this is still the same promise (avoid races)
      const cur = lastSessionInflight.get(key);
      if (cur === p) lastSessionInflight.delete(key);
    });

  lastSessionInflight.set(key, p);
  return p;
}

const useBaseChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      messages: [],
      summaries: [],
      isTyping: false,
      noHistory: false,
      chatSessionId: null,
      lastSessionMarker: null,

      // Token budget tracking
      totalTokens: 0,
      maxTokens: 6000,

      // Summary tracking
      hasSummary: false,
      lastSummaryAt: null,

      // Claude model selection
      claudeModel:
        (localStorage.getItem("claudeModel") as any) ||
        "claude-sonnet-4-20250514",

      manualSessionSyncFlag: false,
      consumeManualSessionSync: () => {
        const was = get().manualSessionSyncFlag;
        if (was) set({ manualSessionSyncFlag: false });
        return was;
      },
      setConsumeManualSessionSync: (value) =>
        set({ manualSessionSyncFlag: value }),

      sessionReady: false,

      // ---------- message ops ----------
      addMessage: (msg) =>
        set((state) => {
          // ✅ Prevent duplicates by ID
          if (state.messages.some((m) => m.id === msg.id)) {
            console.warn(`[chatStore] Duplicate message blocked: ${msg.id}`);
            return state;
          }

          // ✅ ТОЛЬКО для AI messages проверяем duplicate content
          // User messages всегда добавляются (они новые!)
          if (msg.sender !== "user") {
            const isDuplicate = state.messages.some((m) => {
              const sameContent =
                m.sender === msg.sender && m.text === msg.text;
              if (!sameContent) return false;

              // Check timestamp proximity (within 1 second)
              const mTime = (m as any).timestamp;
              const msgTime = (msg as any).timestamp;
              if (mTime && msgTime) {
                return Math.abs(mTime - msgTime) < 1000;
              }

              // If no timestamps, consider it a duplicate if content matches
              return true;
            });

            if (isDuplicate) {
              console.warn(`[chatStore] Duplicate message blocked by content`);
              return state;
            }
          }

          const next = state.messages.concat(msg);
          return { messages: next, noHistory: false };
        }),

      setTyping: (typing) => set({ isTyping: typing }),

      updateMessageText: (id, newText) =>
        set((state) => ({
          messages: replaceById(state.messages, id, (prev) =>
            prev && (prev as any).text !== newText
              ? ({ ...prev, text: newText } as ChatMessage)
              : prev
          ),
        })),

      markMessageDone: (id) =>
        set((state) => ({
          messages: replaceById(state.messages, id, (prev) =>
            prev && (prev as any).isTyping
              ? ({ ...prev, isTyping: false } as ChatMessage)
              : prev
          ),
        })),

      clearMessages: () =>
        set((state) => {
          revokeAttachmentUrls(state.messages);
          return { messages: [], summaries: [], noHistory: true };
        }),

      deleteMessage: (id) =>
        set((state) => {
          const toDelete = state.messages.find((m) => m.id === id);
          if (toDelete) revokeAttachmentUrls([toDelete]);
          const updated = removeById(state.messages, id);
          return { messages: updated, noHistory: updated.length === 0 };
        }),

      updateMessageOnServer: async (id, newText) => {
        try {
          const { updateMessage } = await import("../api/messagesApi");
          const result = await updateMessage(id, newText);

          if (result.success) {
            // Обновляем в store
            get().updateMessageText(id, newText);

            // Показываем toast
            const { toast } = await import("./toastStore");
            toast.success("Message updated!");
          }
        } catch (error) {
          console.error("Failed to update message:", error);
          const { toast } = await import("./toastStore");
          toast.error(
            error instanceof Error ? error.message : "Failed to update message"
          );
          throw error;
        }
      },

      deleteMessageOnServer: async (id) => {
        try {
          const { deleteMessage } = await import("../api/messagesApi");
          const result = await deleteMessage(id);

          if (result.success) {
            // Удаляем из store
            get().deleteMessage(id);

            // Показываем toast
            const { toast } = await import("./toastStore");
            toast.success("Message deleted!");
          }
        } catch (error) {
          console.error("Failed to delete message:", error);
          const { toast } = await import("./toastStore");
          toast.error(
            error instanceof Error ? error.message : "Failed to delete message"
          );
          throw error;
        }
      },

      regenerateMessageOnServer: async (id) => {
        try {
          const { regenerateMessage } = await import("../api/messagesApi");
          const result = await regenerateMessage(id);

          // TODO: Реализовать полную регенерацию когда backend будет готов
          console.log("Regenerate result:", result);

          const { toast } = await import("./toastStore");
          toast.info("Regeneration coming soon!");
        } catch (error) {
          console.error("Failed to regenerate message:", error);
          const { toast } = await import("./toastStore");
          toast.error(
            error instanceof Error
              ? error.message
              : "Failed to regenerate message"
          );
          throw error;
        }
      },

      // ---------- session ops ----------
      setChatSessionId: (id) => {
        set({ chatSessionId: id });
        pendingSessionResolvers.forEach((r) => r());
        pendingSessionResolvers = [];
      },

      setSessionReady: (ready) => set({ sessionReady: ready }),

      waitForSessionReady: (roleId, projectId, timeoutMs = 3000) => {
        const start = Date.now();
        return new Promise<string>((resolve, reject) => {
          const check = () => {
            const { chatSessionId, lastSessionMarker, sessionReady } = get();
            const ok =
              sessionReady &&
              !!chatSessionId &&
              !!lastSessionMarker &&
              lastSessionMarker.roleId === roleId &&
              lastSessionMarker.projectId === projectId &&
              lastSessionMarker.chatSessionId === chatSessionId;

            if (ok) return resolve(chatSessionId as string);
            if (Date.now() - start > timeoutMs)
              return reject(new Error("Session not ready"));

            setTimeout(check, 25);
          };

          check();
          pendingSessionResolvers.push(() => check());
        });
      },

      handleSessionIdUpdateFromAsk: (sessionId) => {
        const current = get();
        if (!sessionId || sessionId === current.chatSessionId) return;
        set({
          chatSessionId: sessionId,
          lastSessionMarker: current.lastSessionMarker
            ? { ...current.lastSessionMarker, chatSessionId: sessionId }
            : null,
        });
        log("[chatStore] handleSessionIdUpdateFromAsk →", sessionId);
      },

      setLastSessionMarker: (marker) =>
        set({ lastSessionMarker: marker || null }),

      setMessages: (msgs) =>
        set((state) => {
          console.log("🔧 [setMessages] ========== CALLED ==========");
          console.log("🔧 [setMessages] Input messages:", msgs?.length);
          console.log("🔧 [setMessages] Input data:", msgs);
          console.log(
            "🔧 [setMessages] Current messages in store:",
            state.messages.length
          );
          console.log(
            "🔧 [setMessages] Stack trace:",
            new Error().stack?.split("\n").slice(1, 5).join("\n")
          );

          revokeAttachmentUrls(state.messages);
          const normalized = withIds(msgs);

          console.log("🔧 [setMessages] After withIds:", normalized.length);
          console.log("🔧 [setMessages] Normalized data:", normalized);
          console.log("🔧 [setMessages] ========== END ==========");

          return { messages: normalized, noHistory: normalized.length === 0 };
        }),

      // Token budget tracking
      setTokenUsage: (used, max) => set({ totalTokens: used, maxTokens: max }),

      // Summary tracking
      setSummaryCreated: (summaryId, timestamp) =>
        set({
          hasSummary: true,
          lastSummaryAt: timestamp,
        }),

      // Claude model selection
      setClaudeModel: (model) => {
        set({ claudeModel: model });
        localStorage.setItem("claudeModel", model);
        console.log(`[Model] Switched to: ${model}`);
      },

      // Back-compat helpers
      setNoHistory: (value: boolean) => set({ noHistory: value }),
      replaceMessages: (msgs: ChatMessage[]) =>
        set((state) => {
          revokeAttachmentUrls(state.messages);
          const normalized = withIds(msgs);
          return { messages: normalized, noHistory: normalized.length === 0 };
        }),

      resetFetchTracking: () => {
        // kept for compatibility (no-op)
      },

      isSessionSynced: () => {
        const { lastSessionMarker, chatSessionId } = get();
        return (
          !!lastSessionMarker &&
          lastSessionMarker.chatSessionId === chatSessionId &&
          !!lastSessionMarker.roleId &&
          !!lastSessionMarker.projectId
        );
      },

      initializeChatSession: async (projectId, roleId) => {
        const version = ++latestSessionVersion;
        set({ sessionReady: false });

        const { lastSessionMarker } = get();
        if (
          lastSessionMarker &&
          lastSessionMarker.projectId === projectId &&
          lastSessionMarker.roleId === roleId &&
          lastSessionMarker.chatSessionId
        ) {
          set({
            chatSessionId: lastSessionMarker.chatSessionId,
            sessionReady: true,
          });
          return;
        }

        try {
          const { data } = await fetchLastSessionByRoleOnce(
            roleId,
            projectId,
            200
          );
          if (version !== latestSessionVersion) return;

          const existingId = data?.chat_session_id
            ? String(data.chat_session_id)
            : uuidv4();
          const normalizedMsgs = withIds(data?.messages);
          const normalizedSummaries = Array.isArray(data?.summaries)
            ? data.summaries
            : [];

          // Extract token info if available
          const totalTokens = data?.total_tokens ?? 0;
          const maxTokens = data?.max_tokens ?? 6000;

          set((state) => {
            revokeAttachmentUrls(state.messages);
            return {
              chatSessionId: existingId,
              messages: normalizedMsgs,
              summaries: normalizedSummaries,
              noHistory: !(normalizedMsgs.length > 0),
              lastSessionMarker: {
                projectId,
                roleId,
                chatSessionId: existingId,
              },
              totalTokens,
              maxTokens,
              sessionReady: true,
            };
          });
        } catch {
          if (version !== latestSessionVersion) return;
          const newId = uuidv4();
          set((state) => {
            revokeAttachmentUrls(state.messages);
            return {
              chatSessionId: newId,
              messages: [],
              summaries: [],
              noHistory: true,
              lastSessionMarker: { projectId, roleId, chatSessionId: newId },
              sessionReady: true,
            };
          });
        }
      },

      rotateChatSessionAfterSummary: async (
        projectId,
        roleId,
        newChatSessionId,
        dividerMessage
      ) => {
        const normalizedDivider: ChatMessage | undefined = dividerMessage
          ? ({
              ...dividerMessage,
              id: dividerMessage.id || `divider-${uuidv4()}`,
              isSummary: true,
              isTyping: false,
              sender: ((dividerMessage as any).sender ??
                "final") as ChatMessage["sender"],
              chat_session_id: newChatSessionId,
              role_id: roleId,
              project_id: String(projectId),
            } as ChatMessage)
          : undefined;

        set((state) => {
          revokeAttachmentUrls(state.messages);
          const nextMsgs = normalizedDivider ? [normalizedDivider] : [];
          return {
            chatSessionId: newChatSessionId,
            lastSessionMarker: {
              projectId,
              roleId,
              chatSessionId: newChatSessionId,
            },
            messages: nextMsgs,
            noHistory: nextMsgs.length === 0,
            sessionReady: true,
          };
        });

        log("[chatStore] 🔄 Rotated to new session", {
          projectId,
          roleId,
          newChatSessionId,
          dividerIncluded: Boolean(normalizedDivider),
        });
      },

      restoreSessionFromMarker: async () => {
        const marker = get().lastSessionMarker;
        if (!marker) return false;
        set({ sessionReady: false });

        try {
          const { data } = await fetchLastSessionByRoleOnce(
            marker.roleId,
            marker.projectId,
            200
          );

          const normalizedMsgs = withIds(data?.messages);
          const normalizedSummaries = Array.isArray(data?.summaries)
            ? data.summaries
            : [];

          // Extract token info if available
          const totalTokens = data?.total_tokens ?? 0;
          const maxTokens = data?.max_tokens ?? 6000;

          set((state) => {
            revokeAttachmentUrls(state.messages);
            return {
              chatSessionId: marker.chatSessionId,
              messages: normalizedMsgs,
              summaries: normalizedSummaries,
              noHistory: !(normalizedMsgs.length > 0),
              totalTokens,
              maxTokens,
              sessionReady: true,
            };
          });
          return true;
        } catch {
          set({ sessionReady: true });
          return false;
        }
      },

      loadOrInitSessionForRoleProject: async (roleId, projectId) => {
        const version = ++latestSessionVersion;
        set({ sessionReady: false });

        try {
          const { data } = await fetchLastSessionByRoleOnce(
            roleId,
            projectId,
            200
          );
          if (version !== latestSessionVersion) return;

          const sid =
            (data?.chat_session_id && String(data.chat_session_id)) || uuidv4();
          const normalizedMsgs = withIds(data?.messages);
          const normalizedSummaries = Array.isArray(data?.summaries)
            ? data.summaries
            : [];

          // Extract token info if available
          const totalTokens = data?.total_tokens ?? 0;
          const maxTokens = data?.max_tokens ?? 6000;

          set((state) => {
            revokeAttachmentUrls(state.messages);
            return {
              lastSessionMarker: { projectId, roleId, chatSessionId: sid },
              chatSessionId: sid,
              messages: normalizedMsgs,
              summaries: normalizedSummaries,
              noHistory: !(normalizedMsgs.length > 0),
              totalTokens,
              maxTokens,
              sessionReady: true,
            };
          });
        } catch (err) {
          console.error(
            `⚠️ Error fetching session for ${roleId}-${projectId}`,
            err
          );
          const sid = uuidv4();
          set((state) => {
            revokeAttachmentUrls(state.messages);
            return {
              lastSessionMarker: { projectId, roleId, chatSessionId: sid },
              chatSessionId: sid,
              messages: [],
              summaries: [],
              noHistory: true,
              sessionReady: true,
            };
          });
        }
      },

      syncAndInitSession: async (roleId, projectId) => {
        set({ sessionReady: false });
        await syncAndInitSessionLocked(roleId, projectId);
        set({ sessionReady: true });
        return { chat_session_id: get().chatSessionId || uuidv4() };
      },
    }),
    {
      name: "chat-storage",
      storage: createJSONStorage(() => localStorage),
      partialize: () => ({}),
    }
  )
);

async function syncAndInitSessionLocked(roleId: number, projectId: number) {
  const version = ++latestSessionVersion;
  if (!sessionLock) {
    sessionLock = useBaseChatStore
      .getState()
      .loadOrInitSessionForRoleProject(roleId, projectId)
      .finally(() => {
        if (version === latestSessionVersion) sessionLock = null;
      });
  }
  return sessionLock;
}

export const useChatStore = createSelectors<ChatState>(useBaseChatStore);

// Optional cleanup before unload (cosmetic)
if (typeof window !== "undefined") {
  window.addEventListener("beforeunload", () => {
    const state = useBaseChatStore.getState();
    revokeAttachmentUrls(state.messages);
    useBaseChatStore.setState({
      messages: [],
      summaries: [],
      isTyping: false,
    } as Partial<ChatState>);
  });
  // @ts-ignore – handy for debugging
  (window as any).useChatStore = useChatStore;
}
