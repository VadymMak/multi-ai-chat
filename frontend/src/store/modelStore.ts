// File: src/store/modelStore.ts
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

// ✅ Supported AI model providers
export type ModelProvider = "openai" | "anthropic" | "boost" | "all";

// ✅ Zustand store state
interface ModelStore {
  provider: ModelProvider;
  setProvider: (provider: ModelProvider) => void;
}

// ✅ Zustand store with built-in persistence
export const useModelStore = create<ModelStore>()(
  persist(
    (set) => ({
      provider: "openai",

      setProvider: (provider) => {
        set({ provider });
      },
    }),
    {
      name: "model-store",
      version: 1,
      storage: createJSONStorage(() => sessionStorage), // ✅ Matches chat/memory/project store
      partialize: (state) => ({
        provider: state.provider, // 🧠 Keep provider if needed across reloads
      }),
    }
  )
);
