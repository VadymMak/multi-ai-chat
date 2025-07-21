import { create } from "zustand";

export type Sender = "user" | "openai" | "anthropic" | "grok";

export interface ChatMessage {
  id: string;
  sender: Sender;
  text: string;
  isTyping?: boolean;
  isSummary?: boolean;
}

export interface ChatState {
  messages: ChatMessage[];
  isTyping: boolean;
  addMessage: (msg: ChatMessage) => void;
  setTyping: (typing: boolean) => void;
  updateMessageText: (id: string, newText: string) => void;
  markMessageDone: (id: string) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isTyping: false,

  addMessage: (msg) =>
    set((state) => ({
      messages: [...state.messages, msg],
    })),

  setTyping: (typing) => set(() => ({ isTyping: typing })),

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

  clearMessages: () => set({ messages: [] }),
}));
