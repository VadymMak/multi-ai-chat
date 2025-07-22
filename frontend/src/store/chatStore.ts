// File: src/store/chatStore.ts

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { v4 as uuidv4 } from "uuid";
import { createSelectors } from "./createSelectors";
import type { ChatMessage } from "../types/chat";
import api from "../services/api";

// -- Types --
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
  fetchedHistoryKeys: Set<string>;
  noHistoryKeys: Set<string>;
  consumeManualSessionSync: boolean;

  addMessage: (msg: ChatMessage) => void;
  setTyping: (typing: boolean) => void;
  updateMessageText: (id: string, newText: string) => void;
  markMessageDone: (id: string) => void;
  clearMessages: () => void;
  deleteMessage: (id: string) => void;

  setChatSessionId: (id: string | null) => void;
  setLastSessionMarker: (marker: LastSessionMarker | null) => void;
  setMessages: (msgs: ChatMessage[]) => void;
  setConsumeManualSessionSync: (value: boolean) => void;

  initializeChatSession: (projectId: number, roleId: number) => Promise<void>;
  rotateChatSessionAfterSummary: (
    projectId: number,
    roleId: number,
    newChatSessionId: string
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

// -- Internal Session Locking --
let sessionLock: Promise<void> | null = null;
let latestSessionVersion = 0;

// -- Store Creation --
const useBaseChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      messages: [],
      summaries: [],
      isTyping: false,
      noHistory: false,
      chatSessionId: null,
      lastSessionMarker: null,
      fetchedHistoryKeys: new Set(),
      noHistoryKeys: new Set(),
      consumeManualSessionSync: false,

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
        set({ messages: [], summaries: [], noHistory: true }),

      deleteMessage: (id) =>
        set((state) => {
          const updated = state.messages.filter((msg) => msg.id !== id);
          return { messages: updated, noHistory: updated.length === 0 };
        }),

      setChatSessionId: (id) => set({ chatSessionId: id }),

      setConsumeManualSessionSync: (value) =>
        set({ consumeManualSessionSync: value }),

      handleSessionIdUpdateFromAsk: (sessionId) => {
        const current = get();
        if (!sessionId || sessionId === current.chatSessionId) return;
        set({
          chatSessionId: sessionId,
          lastSessionMarker: current.lastSessionMarker
            ? { ...current.lastSessionMarker, chatSessionId: sessionId }
            : null,
        });
      },

      setLastSessionMarker: (marker) => {
        if (marker === null) {
          set({ lastSessionMarker: null });
          return;
        }
        const currentId = get().chatSessionId;
        if (marker.chatSessionId !== currentId) return;
        set({ lastSessionMarker: marker });
      },

      setMessages: (msgs) =>
        set({ messages: msgs, noHistory: msgs.length === 0 }),

      resetFetchTracking: () =>
        set({ fetchedHistoryKeys: new Set(), noHistoryKeys: new Set() }),

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
        const { lastSessionMarker } = get();

        if (
          lastSessionMarker &&
          lastSessionMarker.projectId === projectId &&
          lastSessionMarker.roleId === roleId &&
          lastSessionMarker.chatSessionId
        ) {
          set({ chatSessionId: lastSessionMarker.chatSessionId });
          return;
        }

        try {
          const { data } = await api.get("/chat/last-session-by-role", {
            params: { role_id: roleId, project_id: projectId },
          });

          if (version !== latestSessionVersion) return;

          const sessionId = String(data?.chat_session_id || uuidv4());

          set({
            chatSessionId: sessionId,
            messages: data?.messages || [],
            summaries: data?.summaries || [],
            noHistory: !(data?.messages?.length > 0),
            lastSessionMarker: { projectId, roleId, chatSessionId: sessionId },
          });
        } catch {
          if (version !== latestSessionVersion) return;

          const newId = uuidv4();
          set({
            chatSessionId: newId,
            messages: [],
            summaries: [],
            noHistory: true,
            lastSessionMarker: { projectId, roleId, chatSessionId: newId },
          });
        }
      },

      rotateChatSessionAfterSummary: async (
        projectId,
        roleId,
        newChatSessionId
      ) => {
        try {
          const { data } = await api.get("/chat/last-session-by-role", {
            params: { role_id: roleId, project_id: projectId },
          });

          const dividerMessage: ChatMessage = {
            id: `system-divider-${uuidv4()}`,
            sender: "system",
            text: "📌 New phase started after summarization",
            role_id: roleId,
            project_id: projectId,
            chat_session_id: newChatSessionId,
            isTyping: false,
          };

          set({
            chatSessionId: newChatSessionId,
            messages: [...(data?.messages || []), dividerMessage],
            summaries: data?.summaries || [],
            noHistory: !(data?.messages?.length > 0),
            lastSessionMarker: {
              projectId,
              roleId,
              chatSessionId: newChatSessionId,
            },
          });
        } catch (err) {
          console.error("❌ Failed to rotate session after summary", err);
        }
      },

      restoreSessionFromMarker: async () => {
        const marker = get().lastSessionMarker;
        if (!marker) return false;

        try {
          const { data } = await api.get("/chat/last-session-by-role", {
            params: {
              role_id: marker.roleId,
              project_id: marker.projectId,
            },
          });

          set({
            chatSessionId: marker.chatSessionId,
            messages: data?.messages || [],
            summaries: data?.summaries || [],
            noHistory: !(data?.messages?.length > 0),
          });

          return true;
        } catch {
          return false;
        }
      },

      loadOrInitSessionForRoleProject: async (roleId, projectId) => {
        const version = ++latestSessionVersion;
        const key = `${roleId}-${projectId}`;
        const { fetchedHistoryKeys, noHistoryKeys, messages } = get();

        if (fetchedHistoryKeys.has(key) && messages.length > 0) return;
        if (noHistoryKeys.has(key)) return;

        try {
          const { data } = await api.get("/chat/last-session-by-role", {
            params: { role_id: roleId, project_id: projectId },
          });

          if (version !== latestSessionVersion) return;

          if (!data?.messages?.length) {
            const newId = uuidv4();
            set((state) => ({
              noHistory: true,
              chatSessionId: newId,
              messages: [],
              summaries: [],
              noHistoryKeys: new Set([...state.noHistoryKeys, key]),
              fetchedHistoryKeys: new Set([...state.fetchedHistoryKeys, key]),
            }));
            return;
          }

          set((state) => ({
            lastSessionMarker: {
              projectId,
              roleId,
              chatSessionId: data.chat_session_id,
            },
            chatSessionId: data.chat_session_id,
            messages: data.messages || [],
            summaries: data.summaries || [],
            noHistory: false,
            fetchedHistoryKeys: new Set([...state.fetchedHistoryKeys, key]),
          }));
        } catch (err) {
          console.error(`⚠️ Error fetching session for ${key}`, err);
        }
      },

      syncAndInitSession: async (roleId, projectId) => {
        await syncAndInitSessionLocked(roleId, projectId);
        return { chat_session_id: get().chatSessionId || uuidv4() };
      },
    }),
    {
      name: "chat-storage",
      storage: createJSONStorage(() =>
        typeof window === "undefined"
          ? {
              getItem: () => null,
              setItem: () => {},
              removeItem: () => {},
            }
          : sessionStorage
      ),
      partialize: (state) => ({
        lastSessionMarker: state.lastSessionMarker,
      }),
    }
  )
);

// -- Lock-based Runner --
async function syncAndInitSessionLocked(roleId: number, projectId: number) {
  const version = ++latestSessionVersion;

  if (!sessionLock) {
    sessionLock = useBaseChatStore
      .getState()
      .loadOrInitSessionForRoleProject(roleId, projectId)
      .finally(() => {
        if (version === latestSessionVersion) {
          sessionLock = null;
        }
      });
  }

  return sessionLock;
}

// ✅ Export with Selectors
export const useChatStore = createSelectors<ChatState>(useBaseChatStore);

// -- Cleanup & Debug --
if (typeof window !== "undefined") {
  window.addEventListener("beforeunload", () => {
    useBaseChatStore.setState({
      messages: [],
      summaries: [],
      isTyping: false,
      fetchedHistoryKeys: new Set(),
      noHistoryKeys: new Set(),
    });
  });

  // @ts-ignore
  window.useChatStore = useChatStore;
}
