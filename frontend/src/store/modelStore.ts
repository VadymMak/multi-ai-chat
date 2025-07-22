// File: src/store/modelStore.ts

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ModelProvider = "openai" | "anthropic" | "grok" | "boost";

interface ModelState {
  provider: ModelProvider;
  role: string;
  setProvider: (provider: ModelProvider) => void;
  setRole: (role: string) => void;
}

export const useModelStore = create<ModelState>()(
  persist(
    (set) => ({
      provider: "openai",
      role: "default", // ✅ Default role
      setProvider: (provider) => set({ provider }),
      setRole: (role) => set({ role }),
    }),
    {
      name: "model-store", // localStorage key
      partialize: (state) => ({
        provider: state.provider,
        role: state.role,
      }), // 🔒 Persist only relevant keys
    }
  )
);
