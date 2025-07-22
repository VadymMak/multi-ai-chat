// File: src/store/memoryStore.ts

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { MemoryRole } from "../types/memory";

interface MemoryStore {
  role: MemoryRole | null;
  setRole: (role: MemoryRole) => void;
}

export const useMemoryStore = create<MemoryStore>()(
  persist(
    (set) => ({
      role: null,

      setRole: (role) => {
        if (!role || typeof role.id !== "number") {
          console.warn("❌ Invalid role passed to setRole:", role);
          return;
        }
        console.log("🧠 setRole called:", role);
        set({ role });
      },
    }),
    {
      name: "memory-role-store",
      partialize: (state) => ({
        role: state.role,
      }),
    }
  )
);
