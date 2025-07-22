// src/store/projectStore.ts
import { create } from "zustand";

interface ProjectStore {
  projectId: string;
  recentProjects: string[];
  setProjectId: (id: string) => void;
  addProject: (id: string) => void;
}

const LOCAL_KEY = "ai-assistant-project-store";

const loadInitialState = (): Pick<
  ProjectStore,
  "projectId" | "recentProjects"
> => {
  try {
    const saved = localStorage.getItem(LOCAL_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (
        typeof parsed.projectId === "string" &&
        Array.isArray(parsed.recentProjects)
      ) {
        return {
          projectId: parsed.projectId,
          recentProjects: parsed.recentProjects,
        };
      }
    }
  } catch (err) {
    console.warn("Failed to load project store from localStorage", err);
  }
  return {
    projectId: "default",
    recentProjects: ["default"],
  };
};

export const useProjectStore = create<ProjectStore>((set, get) => {
  const persist = () => {
    const { projectId, recentProjects } = get();
    localStorage.setItem(
      LOCAL_KEY,
      JSON.stringify({ projectId, recentProjects })
    );
  };

  const { projectId, recentProjects } = loadInitialState();

  return {
    projectId,
    recentProjects,

    setProjectId: (id: string) => {
      const trimmed = id.trim();
      if (!trimmed) return;

      const updated = get().recentProjects.includes(trimmed)
        ? get().recentProjects
        : [trimmed, ...get().recentProjects].slice(0, 10);

      set({ projectId: trimmed, recentProjects: updated });
      persist();
    },

    addProject: (id: string) => {
      const trimmed = id.trim();
      if (!trimmed) return;

      const current = get().recentProjects;
      if (!current.includes(trimmed)) {
        const updated = [trimmed, ...current].slice(0, 10);
        set({ recentProjects: updated });
        persist();
      }
    },
  };
});
