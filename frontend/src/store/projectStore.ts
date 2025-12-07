// File: src/store/projectStore.ts
import { create, StateCreator, StoreApi, UseBoundStore } from "zustand";
import { persist, PersistOptions, createJSONStorage } from "zustand/middleware";
import { getGeneratedFiles } from "../services/fileApi";
import type { GeneratedFile } from "../types/projects";
import api from "../services/api";
import type {
  Project,
  GitLinkRequest,
  GitLinkResponse,
  GitSyncResponse,
} from "../types/projects";

type ProjectId = number;

// ✅ NEW: Generation status type
export interface GenerationStatus {
  status: "idle" | "running" | "generating" | "completed" | "failed";
  total_files: number;
  files_generated: number;
  files_failed: number;
  progress_percent: number;
  current_file?: string;
  errors?: string[];
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
    assistant_id?: number;
  }) => Promise<Project | null>;
  updateProject: (
    id: number,
    data: { name?: string; description?: string }
  ) => Promise<void>;
  deleteProject: (id: number) => Promise<void>;
  linkGitRepository: (
    projectId: number,
    gitUrl: string
  ) => Promise<GitLinkResponse>;
  syncGitStructure: (projectId: number) => Promise<GitSyncResponse>;
  unlinkGitRepository: (projectId: number) => Promise<void>;
  generatedFiles: GeneratedFile[];
  filesLoading: boolean;
  filesError: string | null;

  fetchGeneratedFiles: (projectId: number) => Promise<void>;
  clearGeneratedFiles: () => void;

  // ✅ NEW: Generation status
  generationStatus: GenerationStatus | null;
  generationPollingId: NodeJS.Timeout | null;
  fetchGenerationStatus: (
    projectId: number
  ) => Promise<GenerationStatus | null>;
  startGenerationPolling: (projectId: number) => void;
  stopGenerationPolling: () => void;
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
      generatedFiles: [],
      filesLoading: false,
      filesError: null,
      // ✅ NEW: Generation status state
      generationStatus: null,
      generationPollingId: null,

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

        // Stop polling for old project
        get().stopGenerationPolling();

        // update recent list (dedupe, cap 10)
        const recent = get().recentProjects;
        const updated = recent.includes(id)
          ? recent
          : [id, ...recent].slice(0, 10);

        set({ projectId: id, recentProjects: updated, generationStatus: null });
        if (process.env.NODE_ENV !== "production") {
          console.debug("📌 [projectStore] Project selected:", id);
        }

        // Check generation status for new project
        get().fetchGenerationStatus(id);
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

      createProject: async (data: {
        name: string;
        description?: string;
        assistant_id?: number;
      }) => {
        try {
          const payload: any = {
            name: data.name.trim(),
            description: data.description?.trim() || "",
          };
          if (data.assistant_id) {
            payload.assistant_id = data.assistant_id;
          }
          const res = await api.post("/projects", payload);
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
      // ✅ Git Integration methods (Phase 3)
      linkGitRepository: async (projectId: number, gitUrl: string) => {
        try {
          const res = await api.patch<GitLinkResponse>(
            `/projects/${projectId}/git`,
            { git_url: gitUrl }
          );

          // Update cache: set git_url
          const state = get();
          state.allProjects = state.allProjects.map((p) =>
            p.id === projectId
              ? { ...p, git_url: res.data.git_url, git_sync_status: null }
              : p
          );

          // Update projectsByRole cache
          Object.keys(state.projectsByRole).forEach((roleId) => {
            const role = parseInt(roleId);
            state.projectsByRole[role] = state.projectsByRole[role].map((p) =>
              p.id === projectId
                ? { ...p, git_url: res.data.git_url, git_sync_status: null }
                : p
            );
          });

          if (process.env.NODE_ENV !== "production") {
            console.debug(
              `✅ [projectStore] Git linked to project ${projectId}:`,
              res.data.git_url
            );
          }

          return res.data;
        } catch (err) {
          console.error(
            `❌ [projectStore] Failed to link Git to project ${projectId}:`,
            err
          );
          throw err;
        }
      },

      syncGitStructure: async (projectId: number) => {
        try {
          const res = await api.post<GitSyncResponse>(
            `/projects/${projectId}/sync-git`
          );

          // Update cache with sync status
          const state = get();
          state.allProjects = state.allProjects.map((p) =>
            p.id === projectId
              ? {
                  ...p,
                  git_sync_status: "synced",
                  git_updated_at: res.data.synced_at,
                  git_files_count: res.data.files_count,
                }
              : p
          );

          // Update projectsByRole cache
          Object.keys(state.projectsByRole).forEach((roleId) => {
            const role = parseInt(roleId);
            state.projectsByRole[role] = state.projectsByRole[role].map((p) =>
              p.id === projectId
                ? {
                    ...p,
                    git_sync_status: "synced",
                    git_updated_at: res.data.synced_at,
                    git_files_count: res.data.files_count,
                  }
                : p
            );
          });

          if (process.env.NODE_ENV !== "production") {
            console.debug(
              `✅ [projectStore] Git synced for project ${projectId}:`,
              res.data.files_count,
              "files"
            );
          }

          return res.data;
        } catch (err) {
          console.error(
            `❌ [projectStore] Failed to sync Git for project ${projectId}:`,
            err
          );
          throw err;
        }
      },

      unlinkGitRepository: async (projectId: number) => {
        try {
          await api.delete(`/projects/${projectId}/git`);

          // Update cache: remove git fields
          const state = get();
          state.allProjects = state.allProjects.map((p) =>
            p.id === projectId
              ? {
                  ...p,
                  git_url: null,
                  git_sync_status: null,
                  git_updated_at: null,
                  git_files_count: null,
                }
              : p
          );

          // Update projectsByRole cache
          Object.keys(state.projectsByRole).forEach((roleId) => {
            const role = parseInt(roleId);
            state.projectsByRole[role] = state.projectsByRole[role].map((p) =>
              p.id === projectId
                ? {
                    ...p,
                    git_url: null,
                    git_sync_status: null,
                    git_updated_at: null,
                    git_files_count: null,
                  }
                : p
            );
          });

          if (process.env.NODE_ENV !== "production") {
            console.debug(
              `✅ [projectStore] Git unlinked from project ${projectId}`
            );
          }
        } catch (err) {
          console.error(
            `❌ [projectStore] Failed to unlink Git from project ${projectId}:`,
            err
          );
          throw err;
        }
      },
      fetchGeneratedFiles: async (projectId: number) => {
        set({ filesLoading: true, filesError: null });
        try {
          const response = await getGeneratedFiles(projectId);
          set({
            generatedFiles: response.files,
            filesLoading: false,
          });
          if (process.env.NODE_ENV !== "production") {
            console.debug(
              `📥 [projectStore] Loaded ${response.files.length} generated files`
            );
          }
        } catch (error) {
          let errorMsg = "Failed to load files";

          if (error instanceof Error) {
            errorMsg = error.message;
          } else if (
            error &&
            typeof error === "object" &&
            "response" in error
          ) {
            const axiosError = error as {
              response?: { data?: { detail?: string } };
              message?: string;
            };
            errorMsg =
              axiosError.response?.data?.detail ||
              axiosError.message ||
              errorMsg;
          }

          set({
            filesError: errorMsg,
            filesLoading: false,
            generatedFiles: [],
          });

          console.error(
            "❌ [projectStore] Failed to fetch generated files:",
            error
          );
        }
      },

      clearGeneratedFiles: () => {
        set({
          generatedFiles: [],
          filesError: null,
          filesLoading: false,
        });
      },

      // ✅ NEW: Fetch generation status
      fetchGenerationStatus: async (projectId: number) => {
        try {
          const res = await api.get(
            `/project-builder/generation-status/${projectId}`
          );
          const status: GenerationStatus = res.data;

          set({ generationStatus: status });

          if (process.env.NODE_ENV !== "production") {
            console.debug(
              `📊 [projectStore] Generation status for ${projectId}:`,
              status.status,
              `${status.files_generated}/${status.total_files}`
            );
          }

          // Auto-start polling if generating (backend returns 'running')
          if (status.status === "running" || status.status === "generating") {
            get().startGenerationPolling(projectId);
          } else {
            get().stopGenerationPolling();
          }

          return status;
        } catch (error) {
          // 404 means no files/status yet - that's OK
          if ((error as any)?.response?.status === 404) {
            set({
              generationStatus: {
                status: "idle",
                total_files: 0,
                files_generated: 0,
                files_failed: 0,
                progress_percent: 0,
              },
            });
            return null;
          }
          console.error(
            "❌ [projectStore] Failed to fetch generation status:",
            error
          );
          return null;
        }
      },

      // ✅ NEW: Start polling for generation status
      startGenerationPolling: (projectId: number) => {
        // Stop any existing polling
        get().stopGenerationPolling();

        if (process.env.NODE_ENV !== "production") {
          console.debug(
            `🔄 [projectStore] Starting generation polling for project ${projectId}`
          );
        }

        const pollInterval = setInterval(async () => {
          const currentProjectId = get().projectId;

          // Stop if project changed
          if (currentProjectId !== projectId) {
            get().stopGenerationPolling();
            return;
          }

          const status = await get().fetchGenerationStatus(projectId);

          // Stop polling if completed or failed
          if (
            status &&
            (status.status === "completed" || status.status === "failed")
          ) {
            get().stopGenerationPolling();

            // Auto-refresh files when complete
            if (status.status === "completed") {
              get().fetchGeneratedFiles(projectId);
            }
          }
        }, 2000); // Poll every 2 seconds

        set({ generationPollingId: pollInterval });
      },

      // ✅ NEW: Stop polling
      stopGenerationPolling: () => {
        const { generationPollingId } = get();
        if (generationPollingId) {
          clearInterval(generationPollingId);
          set({ generationPollingId: null });

          if (process.env.NODE_ENV !== "production") {
            console.debug("⏹️ [projectStore] Stopped generation polling");
          }
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

// ✅ NEW: Generation status selector
export const selectGenerationStatus = (s: ProjectStore) => s.generationStatus;

/* -------------------- Export -------------------- */
export const useProjectStore = baseProjectStore;

// ✅ DEBUG: Export to window for console access
if (typeof window !== "undefined") {
  (window as any).useProjectStore = useProjectStore;
}
