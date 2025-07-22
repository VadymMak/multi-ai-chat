// File: src/store/projectStore.ts

import { create, StateCreator } from "zustand";
import { persist, PersistOptions, createJSONStorage } from "zustand/middleware";
import { StoreApi, UseBoundStore } from "zustand";
import api from "../services/api";

type ProjectId = number;

export interface Project {
  id: ProjectId;
  name: string;
  description?: string | null;
}

export interface ProjectStore {
  projectId: ProjectId | null;
  recentProjects: ProjectId[];
  projectsByRole: Record<number, Project[]>;
  isLoading: boolean;
  hasHydrated: boolean;

  setProjectId: (id: ProjectId | null) => void;
  addProject: (id: ProjectId) => void;

  getCachedProjects: (roleId: number) => Project[] | undefined;
  fetchProjectsForRole: (roleId: number) => Promise<Project[]>;
  forceRefreshProjects: (roleId: number) => Promise<Project[]>;

  autoSetFirstProjectIfMissing: (roleId: number) => void;
}

type MyPersist = PersistOptions<ProjectStore, Partial<ProjectStore>>;

// ==== Custom Persist with Hydration Hook ====

const projectPersist = (
  config: StateCreator<ProjectStore>,
  options: MyPersist
): StateCreator<
  ProjectStore,
  [],
  [["zustand/persist", Partial<ProjectStore>]],
  ProjectStore
> => {
  let setRef: ((partial: Partial<ProjectStore>) => void) | null = null;

  const wrappedConfig: StateCreator<ProjectStore> = (set, get, api) => {
    setRef = set;
    return config(set, get, api);
  };

  const updatedOptions: MyPersist = {
    ...options,
    onRehydrateStorage: () => () => {
      if (setRef) {
        setRef({ hasHydrated: true });
        console.debug("✅ [projectStore] hydration complete");
      }
    },
  };

  return persist(wrappedConfig, updatedOptions);
};

// ==== Zustand Store ====

const baseProjectStore: UseBoundStore<StoreApi<ProjectStore>> = create<
  ProjectStore
>()(
  projectPersist(
    (set, get) => ({
      projectId: null,
      recentProjects: [],
      projectsByRole: {},
      isLoading: false,
      hasHydrated: false,

      setProjectId: (id: ProjectId | null) => {
        if (id === null) {
          set({ projectId: null });
          console.debug("🗑️ [projectStore] Project cleared (null)");
          return;
        }

        if (typeof id !== "number" || isNaN(id) || id < 1) {
          console.warn("⚠️ [projectStore] Invalid project ID:", id);
          return;
        }

        const recent = get().recentProjects;
        const updated = recent.includes(id)
          ? recent
          : [id, ...recent].slice(0, 10);

        set({ projectId: id, recentProjects: updated });
        console.debug("📌 [projectStore] Project selected:", id);
      },

      addProject: (id: ProjectId) => {
        if (typeof id !== "number" || isNaN(id) || id < 1) {
          console.warn(
            "⚠️ [projectStore] Invalid project ID in addProject:",
            id
          );
          return;
        }

        const recent = get().recentProjects;
        if (!recent.includes(id)) {
          const updated = [id, ...recent].slice(0, 10);
          set({ recentProjects: updated });
        }
      },

      getCachedProjects: (roleId: number) => {
        if (typeof roleId !== "number" || isNaN(roleId) || roleId < 1)
          return undefined;
        return get().projectsByRole[roleId];
      },

      fetchProjectsForRole: async (roleId: number) => {
        const cached = get().projectsByRole[roleId];
        if (cached && cached.length > 0) {
          console.debug(
            `📦 [projectStore] Using cached projects for role ${roleId}`
          );
          return cached;
        }

        return await get().forceRefreshProjects(roleId);
      },

      forceRefreshProjects: async (roleId: number) => {
        if (typeof roleId !== "number" || isNaN(roleId) || roleId < 1) {
          console.warn(
            "⚠️ [projectStore] Invalid role ID in forceRefreshProjects:",
            roleId
          );
          return [];
        }

        set({ isLoading: true });

        try {
          const res = await api.get(`/projects/by-role?role_id=${roleId}`);
          const projects = Array.isArray(res.data) ? res.data : [];

          set((state) => ({
            projectsByRole: {
              ...state.projectsByRole,
              [roleId]: projects,
            },
          }));

          console.debug(
            `📥 [projectStore] Loaded ${projects.length} projects for role ${roleId}`
          );
          return projects;
        } catch (err) {
          console.error(
            `❌ [projectStore] Failed to fetch projects for roleId=${roleId}:`,
            err
          );
          return [];
        } finally {
          set({ isLoading: false });
        }
      },

      autoSetFirstProjectIfMissing: (roleId: number) => {
        const { projectId, projectsByRole, setProjectId } = get();
        const projects = projectsByRole[roleId];

        if (!projectId && projects?.length) {
          console.debug(
            "🔁 [projectStore] Auto-selecting first project:",
            projects[0].id
          );
          setProjectId(projects[0].id);
        }
      },
    }),
    {
      name: "project-store",
      version: 2,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        projectId: state.projectId,
        recentProjects: state.recentProjects,
        projectsByRole: state.projectsByRole,
      }),
    }
  )
);

// ==== Export ====

export const useProjectStore = baseProjectStore;
