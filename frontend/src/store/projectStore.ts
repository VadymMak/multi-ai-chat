// File: src/store/projectStore.ts

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ProjectStore {
  projectId: number | null;
  recentProjects: number[];
  setProjectId: (id: number) => void;
  addProject: (id: number) => void;
}

export const useProjectStore = create<ProjectStore>()(
  persist(
    (set, get) => ({
      projectId: null,
      recentProjects: [],

      setProjectId: (id: number) => {
        console.log("[Zustand] Set projectId:", id);
        const recent = get().recentProjects;
        const updated = recent.includes(id)
          ? recent
          : [id, ...recent].slice(0, 10);
        set({ projectId: id, recentProjects: updated });
      },

      addProject: (id: number) => {
        const recent = get().recentProjects;
        if (!recent.includes(id)) {
          const updated = [id, ...recent].slice(0, 10);
          set({ recentProjects: updated });
        }
      },
    }),
    {
      name: "project-store",
      partialize: (state) => ({
        projectId: state.projectId,
        recentProjects: state.recentProjects,
      }),
    }
  )
);
