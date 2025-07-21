// File: src/store/modelStore.ts

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ModelProvider = "openai" | "anthropic" | "grok" | "boost";

interface ModelState {
  provider: ModelProvider;
  setProvider: (provider: ModelProvider) => void;
}

export const useModelStore = create<ModelState>()(
  persist(
    (set) => ({
      provider: "openai",
      setProvider: (provider) => set({ provider }),
    }),
    {
      name: "model-store", // localStorage key
    }
  )
);
