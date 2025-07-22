// File: src/store/modelStore.ts

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ModelProvider = "openai" | "anthropic" | "grok" | "boost";

export interface MemoryRole {
  id: number;
  name: string;
}

interface ModelState {
  provider: ModelProvider;
  role: MemoryRole | null;
  setProvider: (provider: ModelProvider) => void;
  setRole: (role: MemoryRole | null) => void;
}

export const useModelStore = create<ModelState>()(
  persist(
    (set) => ({
      provider: "openai",
      role: null, // ✅ Default to null for clarity
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
