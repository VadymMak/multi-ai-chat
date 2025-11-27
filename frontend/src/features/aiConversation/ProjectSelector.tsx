// File: src/features/aiConversation/ProjectSelector.tsx
import React, { useEffect, useCallback, useRef, useMemo } from "react";
import { Folder, Plus } from "lucide-react";
import { useProjectStore } from "../../store/projectStore";
import { useMemoryStore } from "../../store/memoryStore";
import { runSessionFlow } from "../../controllers/runSessionFlow";
import { toast } from "../../store/toastStore";
import { useChatStore } from "@/store/chatStore";

interface ProjectSelectorProps {
  onOpenSettings?: () => void;
}

const ProjectSelector: React.FC<ProjectSelectorProps> = ({
  onOpenSettings,
}) => {
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
  const setRole = useMemoryStore((state) => state.setRole);

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
      const firstProject = projects[0];
      setProjectId(firstProject.id);

      // Auto-set assistant from project
      if (firstProject.assistant) {
        setRole({
          id: firstProject.assistant.id,
          name: firstProject.assistant.name,
          description: firstProject.assistant.description,
        });
      }

      void runSessionFlow(roleId, firstProject.id, "ProjectSelector[Auto]");
    }
  }, [roleId, projects, projectId, setProjectId, setRole]);

  // ────────────────────────────────────────────────────────────────────────────
  // Handlers
  // ────────────────────────────────────────────────────────────────────────────
  const handleProjectSelect = useCallback(
    async (project: (typeof projects)[0]) => {
      if (project.id === projectId) return; // Already selected

      // Get the new role ID from project's assistant
      const newRoleId = project.assistant?.id ?? roleId;

      // Update stores
      setProjectId(project.id);

      if (project.assistant) {
        setRole({
          id: project.assistant.id,
          name: project.assistant.name,
          description: project.assistant.description,
        });
      }

      // Clear messages before loading new project's history
      useChatStore.getState().clearMessages();

      try {
        // Use NEW role ID, not the old one from closure
        await runSessionFlow(newRoleId!, project.id, "ProjectSelector");
        toast.success(`Switched to ${project.name}`);
      } catch (err) {
        console.error("❌ [ProjectSelector] Session init failed:", err);
        toast.error("Failed to switch project");
      }
    },
    [roleId, projectId, setProjectId, setRole]
  );

  // ────────────────────────────────────────────────────────────────────────────
  // UI
  // ────────────────────────────────────────────────────────────────────────────
  if (!roleId) {
    return (
      <div className="text-sm text-text-secondary p-3 text-center">
        Please select a role first
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="space-y-2">
        <div className="text-sm text-text-secondary p-3 text-center">
          No projects yet
        </div>
        {onOpenSettings && (
          <button
            onClick={onOpenSettings}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 text-sm bg-primary/10 hover:bg-primary/20 text-primary rounded-lg border border-primary/30 hover:border-primary/50 transition-colors"
          >
            <Plus size={16} />
            Create Project
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {projects.map((project) => {
        const isActive = project.id === projectId;
        return (
          <button
            key={project.id}
            onClick={() => handleProjectSelect(project)}
            className={`w-full text-left p-3 rounded-lg border transition-all ${
              isActive
                ? "bg-primary/10 border-primary shadow-sm"
                : "bg-surface border-border hover:border-primary/50 hover:bg-surface/80"
            }`}
          >
            <div className="flex items-center gap-2 mb-1">
              <Folder
                size={14}
                className={isActive ? "text-primary" : "text-text-secondary"}
              />
              <span
                className={`text-sm font-medium ${
                  isActive ? "text-primary" : "text-text-primary"
                }`}
              >
                {project.name}
              </span>
            </div>
            {project.assistant && (
              <div className="flex items-center gap-2 text-xs text-text-secondary ml-5">
                <span>🤖</span>
                <span>{project.assistant.name}</span>
              </div>
            )}
            {project.description && (
              <div className="text-xs text-text-secondary mt-1 ml-5 line-clamp-1">
                {project.description}
              </div>
            )}
          </button>
        );
      })}

      {onOpenSettings && (
        <button
          onClick={onOpenSettings}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 text-sm bg-surface hover:bg-surface/80 text-primary rounded-lg border border-border hover:border-primary/50 transition-colors"
        >
          <Plus size={16} />
          New Project
        </button>
      )}
    </div>
  );
};

export default ProjectSelector;
