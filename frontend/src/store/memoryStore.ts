// File: src/store/memoryStore.ts
import { create, StateCreator } from "zustand";
import { persist, PersistOptions, createJSONStorage } from "zustand/middleware";
import type { MemoryRole } from "../types/memory";
import { getKnownRoles } from "../constants/roles";
import { StoreApi, UseBoundStore } from "zustand";
import { useProjectStore } from "./projectStore";

// -- Types --
export interface MemoryStore {
  role: MemoryRole | null;
  hasHydrated: boolean;

  setRole: (role: MemoryRole) => void;
  clearRole: () => void;
  ensureRoleAndProjectInitialized: () => {
    fallbackRole: MemoryRole | null;
    fallbackProjectId: number | null;
  };
}

type MyPersist = PersistOptions<MemoryStore, Partial<MemoryStore>>;
type MemoryPersist = (
  config: StateCreator<MemoryStore>,
  options: MyPersist
) => StateCreator<
  MemoryStore,
  [],
  [["zustand/persist", Partial<MemoryStore>]],
  MemoryStore
>;

// -- Persist Middleware with Hydration Hook --
const memoryPersist: MemoryPersist = (config, options) => {
  let setRef: ((partial: Partial<MemoryStore>) => void) | null = null;

  const wrappedConfig: StateCreator<MemoryStore> = (set, get, api) => {
    setRef = set;
    return config(set, get, api);
  };

  const updatedOptions: MyPersist = {
    ...options,
    onRehydrateStorage: () => () => {
      if (setRef) {
        setRef({ hasHydrated: true });
        if (process.env.NODE_ENV !== "production") {
          console.debug("✅ memoryStore hydrated");
        }
      }
    },
    storage: createJSONStorage(() =>
      typeof window === "undefined"
        ? {
            getItem: () => null as any,
            setItem: () => {},
            removeItem: () => {},
          }
        : localStorage
    ),
  };

  return persist(wrappedConfig, updatedOptions);
};

// -- Store Instance --
const baseMemoryStore: UseBoundStore<StoreApi<MemoryStore>> = create<
  MemoryStore
>()(
  memoryPersist(
    (set, get) => ({
      role: null,
      hasHydrated: false,

      setRole: (role: MemoryRole) => {
        if (
          !role ||
          typeof role.id !== "number" ||
          typeof role.name !== "string"
        ) {
          console.warn("❌ Invalid role passed to setRole:", role);
          return;
        }

        const current = get().role;
        const changed = !current || current.id !== role.id;
        if (!changed) {
          if (process.env.NODE_ENV !== "production") {
            console.debug("ℹ️ Role unchanged, skipping update.");
          }
          return;
        }

        if (process.env.NODE_ENV !== "production") {
          console.debug("🧠 setRole:", role);
        }
        set({ role });

        // Clear selected project when role changes (prevents stale pairing)
        const projectStore = useProjectStore.getState();
        const oldProjectId = projectStore.projectId;
        if (typeof oldProjectId === "number" && oldProjectId > 0) {
          if (process.env.NODE_ENV !== "production") {
            console.debug("🧼 Clearing stale projectId after role change");
          }
          projectStore.setProjectId(null);
        }
      },

      clearRole: () => {
        if (process.env.NODE_ENV !== "production") {
          console.debug("🧼 Clearing role…");
        }
        set({ role: null });
      },

      ensureRoleAndProjectInitialized: () => {
        const state = get();
        const projectState = useProjectStore.getState();

        let role = state.role;
        let projectId = projectState.projectId;

        // Already initialized
        if (role && projectId) {
          return { fallbackRole: null, fallbackProjectId: null };
        }

        // Pick a fallback role if missing
        const availableRoles = getKnownRoles();
        const pickedRole = role ?? availableRoles[0] ?? null;

        // Look up first known project for that role (if any in cache)
        const projectsForRole = pickedRole
          ? projectState.projectsByRole[pickedRole.id] || []
          : [];
        const pickedProject = projectsForRole[0] ?? null;

        // Assign role if missing
        if (!role && pickedRole) {
          if (process.env.NODE_ENV !== "production") {
            console.debug("🧠 Setting fallback role:", pickedRole);
          }
          get().setRole(pickedRole);
          role = pickedRole;
        }

        // Assign project if missing
        if ((!projectId || projectId < 1) && pickedProject) {
          if (process.env.NODE_ENV !== "production") {
            console.debug("📁 Setting fallback project:", pickedProject);
          }
          projectState.setProjectId(pickedProject.id);
          projectId = pickedProject.id;
        }

        return {
          fallbackRole: role || null,
          fallbackProjectId: projectId || null,
        };
      },
    }),
    {
      name: "memory-role-store",
      version: 3,
      partialize: (state) => ({
        role: state.role,
      }),
      migrate: (
        persistedState: unknown,
        _version: number
      ): Partial<MemoryStore> => {
        const state = persistedState as Partial<MemoryStore>;
        const role = state?.role;
        if (role && typeof role.id === "number") {
          const matched = getKnownRoles().find((r) => r.id === role.id);
          if (matched) {
            if (process.env.NODE_ENV !== "production") {
              console.debug("🔁 Migrated role:", matched);
            }
            return { role: matched };
          }
        }
        console.warn(
          "⚠️ Corrupt or unknown role in persisted state, resetting…"
        );
        return { role: null };
      },
    }
  )
);
export const useMemoryStore = baseMemoryStore;
// ✅ Export
if (typeof window !== "undefined") {
  (window as any).useMemoryStore = useMemoryStore;
}
