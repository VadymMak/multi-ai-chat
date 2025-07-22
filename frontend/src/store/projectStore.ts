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

  // accept string | number | null (we'll coerce safely)
  setProjectId: (id: ProjectId | string | null) => void;
  addProject: (id: ProjectId | string) => void;

  getCachedProjects: (roleId: number) => Project[] | undefined;
  fetchProjectsForRole: (roleId: number) => Promise<Project[]>;
  forceRefreshProjects: (roleId: number) => Promise<Project[]>;
  autoSetFirstProjectIfMissing: (roleId: number) => void;

  // derived (memoized by current array ref)
  getActiveProject: (
    roleId: number,
    projectId: ProjectId | string | null
  ) => Project | null;
}

type MyPersist = PersistOptions<ProjectStore, Partial<ProjectStore>>;

/* -------------------- helpers -------------------- */

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

const shallowEqualProjects = (
  a: Project[] | undefined,
  b: Project[] | undefined
): boolean => {
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
        console.debug("✅ [projectStore] hydration complete");
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

/* -------------------- Zustand Store -------------------- */
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

      setProjectId: (incoming) => {
        const id = toProjectId(incoming);
        const prev = get().projectId;
        if (id === null) {
          if (prev !== null) {
            set({ projectId: null });
            console.debug("🗑️ [projectStore] Project cleared (null)");
          }
          return;
        }
        if (prev === id) {
          // no-op to avoid rerender churn
          return;
        }

        // update recent list (dedupe, cap 10)
        const recent = get().recentProjects;
        const updated = recent.includes(id)
          ? recent
          : [id, ...recent].slice(0, 10);

        set({ projectId: id, recentProjects: updated });
        console.debug("📌 [projectStore] Project selected:", id);
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
          const res = await api.get(`/projects/by-role`, {
            params: { role_id: roleId },
          });
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
            console.debug(
              `📥 [projectStore] Loaded ${incoming.length} projects for role ${roleId}`
            );
          } else {
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
            console.debug(
              "🔁 [projectStore] Auto-selecting first project:",
              firstId
            );
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
          console.debug(
            "🔁 [projectStore] Auto-selecting first project:",
            firstId
          );
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
    }),
    {
      name: "project-store",
      version: 3, // keep version from your last migration
      storage: createJSONStorage(() => localStorage),
      // Persist only what we want long-term: selected & recent IDs (no cached lists)
      partialize: (state) => ({
        projectId: state.projectId,
        recentProjects: state.recentProjects,
        // projectsByRole intentionally NOT persisted to avoid stale caches
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

/* -------------------- Selectors for memoized usage in components -------------------- */
// Use like:
// const projects = useProjectStore(useMemo(() => selectProjectsForRole(roleId), [roleId]));
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
