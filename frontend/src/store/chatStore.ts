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
    if (!m?.attachments?.length) continue;
    for (const att of m.attachments) {
      try {
        if (
          att?.url &&
          typeof att.url === "string" &&
          att.url.startsWith("blob:")
        ) {
          URL.revokeObjectURL(att.url);
        }
      } catch {
        // ignore
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

  // control flags
  consumeManualSessionSync: boolean;
  sessionReady: boolean;

  // message ops
  addMessage: (msg: ChatMessage) => void;
  setTyping: (typing: boolean) => void;
  updateMessageText: (id: string, newText: string) => void;
  markMessageDone: (id: string) => void;
  clearMessages: () => void;
  deleteMessage: (id: string) => void;

  // session ops
  setChatSessionId: (id: string | null) => void;
  setLastSessionMarker: (marker: LastSessionMarker | null) => void;
  setMessages: (msgs: ChatMessage[]) => void;
  setConsumeManualSessionSync: (value: boolean) => void;
  setSessionReady: (ready: boolean) => void;

  // 👇 Back-compat helpers (used by earlier components)
  setNoHistory?: (value: boolean) => void;
  replaceMessages?: (msgs: ChatMessage[]) => void;

  waitForSessionReady: (
    roleId: number,
    projectId: number,
    timeoutMs?: number
  ) => Promise<string>;

  initializeChatSession: (projectId: number, roleId: number) => Promise<void>;

  // accepts optional divider to seed the new session
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

  // kept for compatibility with older callers (no-op now)
  resetFetchTracking: () => void;

  isSessionSynced: () => boolean;
  handleSessionIdUpdateFromAsk: (sessionId: string) => void;
}

// === Internal session lock ===
let sessionLock: Promise<void> | null = null;
let latestSessionVersion = 0;
let pendingSessionResolvers: Array<() => void> = [];

const log = (...args: any[]) => {
  if (process.env.NODE_ENV !== "production") console.debug(...args);
};

// === Store ===
const useBaseChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      messages: [],
      summaries: [],
      isTyping: false,
      noHistory: false,
      chatSessionId: null,
      lastSessionMarker: null,

      consumeManualSessionSync: false,
      sessionReady: false,

      // ---------- message ops ----------
      addMessage: (msg) =>
        set((state) => {
          if (state.messages.some((m) => m.id === msg.id)) return state;
          return { messages: [...state.messages, msg], noHistory: false };
        }),

      setTyping: (typing) => set({ isTyping: typing }),

      updateMessageText: (id, newText) =>
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === id ? { ...msg, text: newText } : msg
          ),
        })),

      markMessageDone: (id) =>
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === id ? { ...msg, isTyping: false } : msg
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
          const updated = state.messages.filter((msg) => msg.id !== id);
          return { messages: updated, noHistory: updated.length === 0 };
        }),

      // ---------- session ops ----------
      setChatSessionId: (id) => {
        set({ chatSessionId: id });
        // wake any waiters
        pendingSessionResolvers.forEach((r) => r());
        pendingSessionResolvers = [];
      },

      setConsumeManualSessionSync: (value) =>
        set({ consumeManualSessionSync: value }),

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
          // also re-check when someone updates session id
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
          revokeAttachmentUrls(state.messages);
          return { messages: msgs, noHistory: msgs.length === 0 };
        }),

      // 👇 Back-compat helpers so older code compiles
      setNoHistory: (value: boolean) => set({ noHistory: value }),
      replaceMessages: (msgs: ChatMessage[]) =>
        set((state) => {
          revokeAttachmentUrls(state.messages);
          return { messages: msgs, noHistory: msgs.length === 0 };
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
          const { data } = await api.get("/chat/last-session-by-role", {
            params: { role_id: roleId, project_id: projectId, limit: 200 },
          });
          if (version !== latestSessionVersion) return;

          const existingId = data?.chat_session_id
            ? String(data.chat_session_id)
            : uuidv4();

          set((state) => {
            revokeAttachmentUrls(state.messages);
            return {
              chatSessionId: existingId,
              messages: Array.isArray(data?.messages) ? data.messages : [],
              summaries: Array.isArray(data?.summaries) ? data.summaries : [],
              noHistory: !(data?.messages?.length > 0),
              lastSessionMarker: {
                projectId,
                roleId,
                chatSessionId: existingId,
              },
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

      // rotate + optionally seed divider in the new session
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
              sender: (dividerMessage as any).sender || ("final" as any),
              chat_session_id: newChatSessionId,
              role_id: roleId,
              project_id: String(projectId),
            } as any)
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
          const { data } = await api.get("/chat/last-session-by-role", {
            params: {
              role_id: marker.roleId,
              project_id: marker.projectId,
              limit: 200,
            },
          });

          set((state) => {
            revokeAttachmentUrls(state.messages);
            return {
              chatSessionId: marker.chatSessionId,
              messages: Array.isArray(data?.messages) ? data.messages : [],
              summaries: Array.isArray(data?.summaries) ? data.summaries : [],
              noHistory: !(data?.messages?.length > 0),
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
          const { data } = await api.get("/chat/last-session-by-role", {
            params: { role_id: roleId, project_id: projectId, limit: 200 },
          });
          if (version !== latestSessionVersion) return;

          const sid =
            (data?.chat_session_id && String(data.chat_session_id)) || uuidv4();

          set((state) => {
            revokeAttachmentUrls(state.messages);
            return {
              lastSessionMarker: { projectId, roleId, chatSessionId: sid },
              chatSessionId: sid,
              messages: Array.isArray(data?.messages) ? data.messages : [],
              summaries: Array.isArray(data?.summaries) ? data.summaries : [],
              noHistory: !(data?.messages?.length > 0),
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
      storage: createJSONStorage(() =>
        typeof window === "undefined"
          ? { getItem: () => null, setItem: () => {}, removeItem: () => {} }
          : sessionStorage
      ),
      // Persist just the marker so we can restore on reload
      partialize: (state) => ({
        lastSessionMarker: state.lastSessionMarker,
      }),
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
