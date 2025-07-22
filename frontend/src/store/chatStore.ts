// File: src/store/chatStore.ts

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { v4 as uuidv4 } from "uuid";
import { createSelectors } from "./createSelectors";
import type { ChatMessage } from "../types/chat";

export interface LastSessionMarker {
  projectId: number;
  roleId: number;
  chatSessionId: string;
}

export interface ChatState {
  messages: ChatMessage[];
  isTyping: boolean;
  chatSessionId: string | null;
  lastSessionMarker: LastSessionMarker | null;

  addMessage: (msg: ChatMessage) => void;
  setTyping: (typing: boolean) => void;

  updateMessageText: (id: string, newText: string) => void;
  markMessageDone: (id: string) => void;

  clearMessages: () => void;
  deleteMessage: (id: string) => void;

  setChatSessionId: (id: string | null) => void;
  initializeChatSession: () => void;

  setLastSessionMarker: (marker: LastSessionMarker) => void;
  setMessages: (msgs: ChatMessage[]) => void;
}

const useBaseChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      messages: [],
      isTyping: false,
      chatSessionId: null,
      lastSessionMarker: null,

      addMessage: (msg) =>
        set((state) => {
          if (state.messages.some((m) => m.id === msg.id)) return state;
          return { messages: [...state.messages, msg] };
        }),

      setTyping: (typing) => {
        console.log("[Zustand] Typing state set to:", typing);
        set({ isTyping: typing });
      },

      updateMessageText: (id, newText) => {
        if (!newText) return;
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === id ? { ...msg, text: newText } : msg
          ),
        }));
      },

      markMessageDone: (id) => {
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === id ? { ...msg, isTyping: false } : msg
          ),
        }));
      },

      clearMessages: () => {
        console.log("[Zustand] Messages cleared");
        set({ messages: [] });
      },

      deleteMessage: (id) => {
        console.log("[Zustand] Message deleted:", id);
        set((state) => ({
          messages: state.messages.filter((msg) => msg.id !== id),
        }));
      },

      setChatSessionId: (id) => {
        console.log("[Zustand] Set chatSessionId:", id);
        set({ chatSessionId: id });
      },

      initializeChatSession: () => {
        const current = get().chatSessionId;
        if (!current) {
          const newId = uuidv4();
          console.log("[Zustand] Created new session ID:", newId);
          set({ chatSessionId: newId });
        }
      },

      setLastSessionMarker: (marker) => {
        console.log("[Zustand] Set lastSessionMarker:", marker);
        set({ lastSessionMarker: marker });
      },

      setMessages: (msgs) => {
        console.log("[Zustand] Set messages:", msgs.length);
        set({ messages: msgs });
      },
    }),
    {
      name: "chat-storage",
      partialize: (state) => ({
        lastSessionMarker: state.lastSessionMarker,
      }),
    }
  )
);

export const useChatStore = createSelectors<ChatState>(useBaseChatStore);
