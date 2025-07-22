// src/store/chatStore.ts
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { createSelectors } from "./createSelectors";
import type { ChatMessage } from "../types/chat";

export interface ChatState {
  messages: ChatMessage[];
  isTyping: boolean;
  addMessage: (msg: ChatMessage) => void;
  setTyping: (typing: boolean) => void;
  updateMessageText: (id: string, newText: string) => void;
  markMessageDone: (id: string) => void;
  clearMessages: () => void;
}

const useBaseChatStore = create<ChatState>()(
  persist(
    (set) => ({
      messages: [],
      isTyping: false,
      addMessage: (msg) =>
        set((state) => {
          const exists = state.messages.some((m) => m.id === msg.id);
          if (exists) return state; // Skip if duplicate
          return { messages: [...state.messages, msg] };
        }),

      setTyping: (typing) => set({ isTyping: typing }),
      updateMessageText: (id, newText) => {
        console.log(`[Zustand] Updating text for ${id}:`, newText.slice(0, 60));
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === id ? { ...msg, text: newText } : msg
          ),
        }));
      },

      markMessageDone: (id) => {
        console.log(`[Zustand] Marking done for ${id}`);
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === id ? { ...msg, isTyping: false } : msg
          ),
        }));
      },

      clearMessages: () => set({ messages: [] }),
    }),
    {
      name: "chat-storage",
      partialize: (state) => ({ messages: state.messages }),
    }
  )
);

// ✅ Correctly typed enhanced selector version
export const useChatStore = createSelectors<ChatState>(useBaseChatStore);
