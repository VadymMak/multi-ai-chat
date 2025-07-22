// File: src/features/aiConversation/ProjectSelector.tsx
import React, { useEffect, useCallback, useRef, useMemo } from "react";
import { useProjectStore } from "../../store/projectStore";
import { useMemoryStore } from "../../store/memoryStore";
import { runSessionFlow } from "../../controllers/runSessionFlow";

const ProjectSelector: React.FC = () => {
  // ✅ Proper Zustand subscription - component re-renders when store changes
  const projectsByRole = useProjectStore((state) => state.projectsByRole);
  const projectId = useProjectStore((state) => state.projectId);
  const setProjectId = useProjectStore((state) => state.setProjectId);
  const forceRefreshProjects = useProjectStore(
    (state) => state.forceRefreshProjects
  );

  const roleId = useMemoryStore(
    useCallback((s) => (typeof s.role?.id === "number" ? s.role!.id : null), [])
  );

  // ✅ Memoize projects to prevent useEffect dependency warning
  const projects = useMemo(
    () => (roleId ? projectsByRole[roleId] || [] : []),
    [projectsByRole, roleId]
  );

  const loadingRef = useRef<boolean>(false);

  // Load projects on mount
  useEffect(() => {
    if (roleId && !loadingRef.current) {
      loadingRef.current = true;
      void forceRefreshProjects(roleId).finally(() => {
        loadingRef.current = false;
      });
    }
  }, [roleId, forceRefreshProjects]);

  // Listen for updates from Settings
  useEffect(() => {
    const handleProjectsUpdated = async () => {
      if (!roleId) return;
      console.log("📥 ProjectSelector: Event received, refreshing...");
      await forceRefreshProjects(roleId);
      console.log("✅ ProjectSelector: Refresh complete");
    };

    window.addEventListener("projectsUpdated", handleProjectsUpdated);

    return () => {
      window.removeEventListener("projectsUpdated", handleProjectsUpdated);
    };
  }, [roleId, forceRefreshProjects]);

  // Auto-select first project if none selected
  useEffect(() => {
    if (roleId && projects.length > 0 && !projectId) {
      const firstId = projects[0].id;
      setProjectId(firstId);
      void runSessionFlow(roleId, firstId, "ProjectSelector[Auto]");
    }
  }, [roleId, projects, projectId, setProjectId]);

  // ────────────────────────────────────────────────────────────────────────────
  // Handlers
  // ────────────────────────────────────────────────────────────────────────────
  const handleChange = useCallback(
    async (e: React.ChangeEvent<HTMLSelectElement>) => {
      const newId = parseInt(e.target.value, 10);
      if (Number.isNaN(newId) || !roleId || newId === projectId) return;

      setProjectId(newId);

      try {
        await runSessionFlow(roleId, newId, "ProjectSelector");
      } catch (err) {
        console.error("❌ [ProjectSelector] Session init failed:", err);
      }
    },
    [roleId, projectId, setProjectId]
  );

  // ────────────────────────────────────────────────────────────────────────────
  // UI
  // ────────────────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-2">
      <select
        id="project-select"
        value={projectId ?? ""}
        onChange={handleChange}
        className="w-full px-3 py-2 rounded border border-border text-sm bg-surface text-text-primary focus:border-primary focus:outline-none transition-colors"
        disabled={!roleId}
      >
        {projects.length === 0 && <option value="">No linked projects</option>}
        {projects.map((proj) => (
          <option key={proj.id} value={proj.id.toString()}>
            {proj.name}
          </option>
        ))}
      </select>
    </div>
  );
};

export default ProjectSelector;
