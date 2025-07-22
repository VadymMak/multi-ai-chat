// File: src/store/memoryStore.ts
import { create, StateCreator } from "zustand";
import { persist, PersistOptions } from "zustand/middleware";
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
        console.log("✅ memoryStore hydrated");
      }
    },
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
        const isChanged = !current || current.id !== role.id;

        if (isChanged) {
          console.log("🧠 setRole:", role);
          set({ role });

          const projectStore = useProjectStore.getState();
          const oldProjectId = projectStore.projectId;

          if (typeof oldProjectId === "number" && oldProjectId > 0) {
            console.debug("🧼 Clearing stale projectId after role change");
            projectStore.setProjectId(null);
          }
        } else {
          console.log("ℹ️ Role unchanged, skipping update.");
        }
      },

      clearRole: () => {
        console.log("🧼 Clearing role...");
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

        // Fallback role selection
        const availableRoles = getKnownRoles();
        const fallbackRole = role || availableRoles[0];
        const allProjects =
          projectState.projectsByRole[fallbackRole?.id ?? -1] || [];
        const fallbackProject = allProjects[0];

        // Assign role if missing
        if (!role && fallbackRole) {
          console.log("🧠 Setting fallback role:", fallbackRole);
          get().setRole(fallbackRole);
          role = fallbackRole;
        }

        // Assign project if missing
        if ((!projectId || projectId < 1) && fallbackProject) {
          console.log("📁 Setting fallback project:", fallbackProject);
          projectState.setProjectId(fallbackProject.id);
          projectId = fallbackProject.id;
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
            console.log("🔁 Migrated role:", matched);
            return { role: matched };
          }
        }
        console.warn(
          "⚠️ Corrupt or unknown role in persisted state, resetting..."
        );
        return { role: null };
      },
    }
  )
);

// ✅ Export
export const useMemoryStore = baseMemoryStore;
