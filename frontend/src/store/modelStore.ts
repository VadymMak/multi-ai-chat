// File: src/store/modelStore.ts
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

// ✅ Supported AI model providers
export type ModelProvider = "openai" | "anthropic" | "grok" | "boost" | "all";

// ✅ Role structure
export interface MemoryRole {
  id: number;
  name: string;
}

// ✅ Zustand store state
interface ModelStore {
  provider: ModelProvider;
  role: MemoryRole | null;
  setProvider: (provider: ModelProvider) => void;
  setRole: (role: MemoryRole | null) => void;
}

// ✅ Zustand store with built-in persistence
export const useModelStore = create<ModelStore>()(
  persist(
    (set) => ({
      provider: "openai",
      role: null,

      setProvider: (provider) => {
        set({ provider });
      },

      setRole: (role) => {
        set({ role });
      },
    }),
    {
      name: "model-store",
      version: 1,
      storage: createJSONStorage(() => sessionStorage), // ✅ Matches chat/memory/project store
      partialize: (state) => ({
        provider: state.provider, // 🧠 Keep provider if needed across reloads
        role: state.role, // 🧠 Discard after session if needed
      }),
    }
  )
);
