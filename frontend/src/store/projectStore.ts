// File: src/store/projectStore.ts
import { create, StateCreator, StoreApi, UseBoundStore } from "zustand";
import { persist, PersistOptions, createJSONStorage } from "zustand/middleware";
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
  allProjects: Project[];
  isLoading: boolean;
  hasHydrated: boolean;

  setProjectId: (id: ProjectId | string | null) => void;
  addProject: (id: ProjectId | string) => void;

  getCachedProjects: (roleId: number) => Project[] | undefined;
  fetchProjectsForRole: (roleId: number) => Promise<Project[]>;
  forceRefreshProjects: (roleId: number) => Promise<Project[]>;
  autoSetFirstProjectIfMissing: (roleId: number) => void;

  getActiveProject: (
    roleId: number,
    projectId: ProjectId | string | null
  ) => Project | null;

  // CRUD methods for Settings UI
  fetchAllProjects: () => Promise<Project[]>;
  createProject: (data: {
    name: string;
    description?: string;
  }) => Promise<Project | null>;
  updateProject: (
    id: number,
    data: { name?: string; description?: string }
  ) => Promise<void>;
  deleteProject: (id: number) => Promise<void>;
}

type MyPersist = PersistOptions<ProjectStore, Partial<ProjectStore>>;

/* -------------------------------- helpers -------------------------------- */

const toProjectId = (
  val: ProjectId | string | null | undefined
): ProjectId | null => {
  if (val === null || val === undefined) return null;
  if (typeof val === "number")
    return Number.isFinite(val) && val > 0 ? val : null;
  const parsed = parseInt(val, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
};

const normalizeProjects = (projects: any[]): Project[] =>
  (projects || [])
    .map((p) => ({
      ...p,
      id: typeof p?.id === "string" ? parseInt(p.id, 10) : p?.id,
    }))
    .filter(
      (p) => typeof p.id === "number" && Number.isFinite(p.id) && p.id > 0
    ) as Project[];

const shallowEqualProjects = (a?: Project[], b?: Project[]): boolean => {
  if (a === b) return true;
  if (!a || !b) return false;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    const x = a[i];
    const y = b[i];
    if (!y) return false;
    if (x.id !== y.id || x.name !== y.name || x.description !== y.description)
      return false;
  }
  return true;
};

/* -------------- Custom Persist with Hydration Hook -------------- */
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
        if (process.env.NODE_ENV !== "production") {
          console.debug("✅ [projectStore] hydration complete");
        }
      }
    },
  };

  return persist(wrappedConfig, updatedOptions);
};

/* -------- small memo cache for activeProject by array reference -------- */
const activeProjectCache = new WeakMap<
  Project[],
  Map<ProjectId, Project | null>
>();

/* ----------------------------- Zustand Store ----------------------------- */
const baseProjectStore: UseBoundStore<StoreApi<ProjectStore>> = create<
  ProjectStore
>()(
  projectPersist(
    (set, get) => ({
      projectId: null,
      recentProjects: [],
      projectsByRole: {},
      allProjects: [],
      isLoading: false,
      hasHydrated: false,

      setProjectId: (incoming) => {
        const id = toProjectId(incoming);
        const prev = get().projectId;
        if (id === null) {
          if (prev !== null) {
            set({ projectId: null });
            if (process.env.NODE_ENV !== "production") {
              console.debug("🗑️ [projectStore] Project cleared (null)");
            }
          }
          return;
        }
        if (prev === id) return; // no-op

        // update recent list (dedupe, cap 10)
        const recent = get().recentProjects;
        const updated = recent.includes(id)
          ? recent
          : [id, ...recent].slice(0, 10);

        set({ projectId: id, recentProjects: updated });
        if (process.env.NODE_ENV !== "production") {
          console.debug("📌 [projectStore] Project selected:", id);
        }
      },

      addProject: (incoming) => {
        const id = toProjectId(incoming);
        if (id === null) {
          console.warn(
            "⚠️ [projectStore] Invalid project ID in addProject:",
            incoming
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
        if (typeof roleId !== "number" || isNaN(roleId) || roleId < 1) {
          console.warn(
            "⚠️ [projectStore] Invalid role ID in fetchProjectsForRole:",
            roleId
          );
          return [];
        }

        const cached = get().projectsByRole[roleId];
        if (cached && cached.length > 0) {
          if (process.env.NODE_ENV !== "production") {
            console.debug(
              `📦 [projectStore] Using cached projects for role ${roleId}`
            );
          }
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
          const res = await api.get("/projects");
          const incoming = normalizeProjects(
            Array.isArray(res.data) ? res.data : []
          );
          const { projectsByRole } = get();
          const prev = projectsByRole[roleId];

          // Only set if changed (prevents re-renders)
          if (!shallowEqualProjects(prev, incoming)) {
            set((state) => ({
              projectsByRole: {
                ...state.projectsByRole,
                [roleId]: incoming,
              },
            }));
            if (process.env.NODE_ENV !== "production") {
              console.debug(
                `📥 [projectStore] Loaded ${incoming.length} projects for role ${roleId}`
              );
            }
          } else if (process.env.NODE_ENV !== "production") {
            console.debug(
              `♻️ [projectStore] Projects unchanged for role ${roleId} — skip set`
            );
          }

          // If no project selected yet, pick the first
          const currentId = get().projectId;
          const list = get().projectsByRole[roleId] ?? incoming;
          if (!currentId && list.length > 0) {
            const firstId = list[0].id;
            set({ projectId: firstId });
            if (process.env.NODE_ENV !== "production") {
              console.debug(
                "🔁 [projectStore] Auto-selecting first project:",
                firstId
              );
            }
          }

          return get().projectsByRole[roleId] ?? incoming;
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
        if (typeof roleId !== "number" || isNaN(roleId) || roleId < 1) {
          console.warn(
            "⚠️ [projectStore] Invalid role ID in autoSetFirstProjectIfMissing:",
            roleId
          );
          return;
        }

        const { projectId, projectsByRole } = get();
        const projects = projectsByRole[roleId];

        if (!projectId && projects?.length) {
          const firstId = projects[0].id;
          set({ projectId: firstId });
          if (process.env.NODE_ENV !== "production") {
            console.debug(
              "🔁 [projectStore] Auto-selecting first project:",
              firstId
            );
          }
        }
      },

      getActiveProject: (
        roleId: number,
        incomingId: ProjectId | string | null
      ) => {
        const id = toProjectId(incomingId);
        if (!id) return null;
        const list = get().projectsByRole[roleId] || [];
        // cache per array reference
        let byId = activeProjectCache.get(list);
        if (!byId) {
          byId = new Map<ProjectId, Project | null>();
          activeProjectCache.set(list, byId);
        }
        if (byId.has(id)) return byId.get(id) ?? null;
        const found = list.find((p) => p.id === id) ?? null;
        byId.set(id, found);
        return found;
      },

      // CRUD methods for Settings UI
      fetchAllProjects: async () => {
        set({ isLoading: true });
        try {
          const res = await api.get("/projects");
          const projects = normalizeProjects(
            Array.isArray(res.data) ? res.data : []
          );
          set({ allProjects: projects });
          if (process.env.NODE_ENV !== "production") {
            console.debug(
              `📥 [projectStore] Loaded ${projects.length} total projects`
            );
          }
          return projects;
        } catch (err) {
          console.error("❌ [projectStore] Failed to fetch all projects:", err);
          return [];
        } finally {
          set({ isLoading: false });
        }
      },

      createProject: async (data: { name: string; description?: string }) => {
        try {
          const res = await api.post("/projects", {
            name: data.name.trim(),
            description: data.description?.trim() || "",
          });
          const newProject = res?.data;
          if (newProject && typeof newProject.id === "number") {
            if (process.env.NODE_ENV !== "production") {
              console.debug("✅ [projectStore] Project created:", newProject);
            }
            return normalizeProjects([newProject])[0] || null;
          }
          return null;
        } catch (err) {
          console.error("❌ [projectStore] Failed to create project:", err);
          return null;
        }
      },

      updateProject: async (
        id: number,
        data: { name?: string; description?: string }
      ) => {
        try {
          await api.put(`/projects/${id}`, {
            ...(data.name !== undefined && { name: data.name.trim() }),
            ...(data.description !== undefined && {
              description: data.description.trim(),
            }),
          });
          if (process.env.NODE_ENV !== "production") {
            console.debug(`✅ [projectStore] Project ${id} updated`);
          }
        } catch (err) {
          console.error(
            `❌ [projectStore] Failed to update project ${id}:`,
            err
          );
          throw err;
        }
      },

      deleteProject: async (id: number) => {
        try {
          await api.delete(`/projects/${id}`);
          if (process.env.NODE_ENV !== "production") {
            console.debug(`✅ [projectStore] Project ${id} deleted`);
          }
        } catch (err) {
          console.error(
            `❌ [projectStore] Failed to delete project ${id}:`,
            err
          );
          throw err;
        }
      },
    }),
    {
      name: "project-store",
      version: 3,
      storage: createJSONStorage(() =>
        typeof window === "undefined"
          ? {
              getItem: () => null as any,
              setItem: () => {},
              removeItem: () => {},
            }
          : localStorage
      ),
      // Persist only what we want long-term: selected & recent IDs (no cached lists)
      partialize: (state) => ({
        projectId: state.projectId,
        recentProjects: state.recentProjects,
      }),
      migrate: (persisted, version) => {
        if (version < 3 && persisted && typeof persisted === "object") {
          if ("projectsByRole" in (persisted as any)) {
            delete (persisted as any).projectsByRole;
          }
        }
        return persisted as any;
      },
    }
  )
);

/* -------------------- Selectors -------------------- */
export const selectProjectsForRole = (roleId?: number) => (
  s: ProjectStore
): Project[] =>
  roleId && s.projectsByRole[roleId] ? s.projectsByRole[roleId] : [];

export const selectBasics = (s: ProjectStore) => ({
  projectId: s.projectId,
  isLoading: s.isLoading,
});

/* -------------------- Export -------------------- */
export const useProjectStore = baseProjectStore;
