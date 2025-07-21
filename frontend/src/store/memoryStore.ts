// File: src/store/memoryStore.ts

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { MemoryRole } from "../types/memory";

interface MemoryStore {
  role: MemoryRole;
  setRole: (role: MemoryRole) => void;
}

export const useMemoryStore = create<MemoryStore>()(
  persist(
    (set) => ({
      role: "LLM Engineer", // default
      setRole: (role) => set({ role }),
    }),
    {
      name: "memory-role-store",
    }
  )
);
