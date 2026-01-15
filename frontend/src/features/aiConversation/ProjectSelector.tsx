// File: src/features/aiConversation/ProjectSelector.tsx
import React, {
  useEffect,
  useCallback,
  useRef,
  useMemo,
  useState,
} from "react";
import { Folder, Plus, MoreVertical, Link2 } from "lucide-react";
import { useProjectStore } from "../../store/projectStore";
import { useMemoryStore } from "../../store/memoryStore";
import { runSessionFlow } from "../../controllers/runSessionFlow";
import { toast } from "../../store/toastStore";
import { useChatStore } from "@/store/chatStore";
import ProjectContextMenu from "../../components/Settings/ProjectContextMenu";
import ProjectSettingsModal from "../../components/Settings/ProjectSettingsModal";
import { BarChart3 } from "lucide-react";  // или используем ViewGraphButton
import { useNavigate } from "react-router-dom";

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
  const navigate = useNavigate();

  const deleteProject = useProjectStore((state) => state.deleteProject); // ❌ УДАЛИ ЭТУ СТРОКУ

  const roleId = useMemoryStore(
    useCallback((s) => (typeof s.role?.id === "number" ? s.role!.id : null), [])
  );
  const setRole = useMemoryStore((state) => state.setRole);
  const isManualSwitchRef = useRef(false);
  // ✅ Context Menu State
  const [contextMenuOpen, setContextMenuOpen] = useState(false);
  const [contextMenuAnchor, setContextMenuAnchor] =
    useState<HTMLElement | null>(null);
  const [selectedProjectForMenu, setSelectedProjectForMenu] = useState<
    number | null
  >(null);

  // ✅ Settings Modal State
  const [settingsModalOpen, setSettingsModalOpen] = useState(false);
  const [projectIdForSettings, setProjectIdForSettings] = useState<
    number | null
  >(null);

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

  // ────────────────────────────────────────────────────────────────────────────
  // Handlers
  // ────────────────────────────────────────────────────────────────────────────
  const handleProjectSelect = useCallback(
    async (project: (typeof projects)[0]) => {
      if (project.id === projectId) return;

      // Mark as manual switch to prevent auto-select
      isManualSwitchRef.current = true;

      const newRoleId = project.assistant?.id ?? roleId;

      // ✅ Clear messages FIRST, before changing projectId
      useChatStore.getState().clearMessages();

      // ✅ Update role BEFORE projectId to prevent race conditions
      if (project.assistant) {
        setRole({
          id: project.assistant.id,
          name: project.assistant.name,
          description: project.assistant.description,
        });
      }

      // ✅ Set projectId AFTER clearing and role update
      setProjectId(project.id);

      try {
        await runSessionFlow(newRoleId!, project.id, "ProjectSelector");
        toast.success(`Switched to ${project.name}`);
      } catch (err) {
        console.error("❌ [ProjectSelector] Session init failed:", err);
        toast.error("Failed to switch project");
      } finally {
        // ✅ Delay reset to ensure all effects have processed
        setTimeout(() => {
          isManualSwitchRef.current = false;
        }, 300);
      }
    },
    [roleId, projectId, setProjectId, setRole]
  );

  // Auto-select first project if none selected (but NOT during manual switch)
  useEffect(() => {
    if (isManualSwitchRef.current) return; // Skip during manual switch

    if (roleId && projects.length > 0 && !projectId) {
      const firstProject = projects[0];
      setProjectId(firstProject.id);

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

  // ✅ Context Menu Handlers
  const handleMoreClick = (e: React.MouseEvent, projectId: number) => {
    e.stopPropagation();
    setContextMenuAnchor(e.currentTarget as HTMLElement);
    setSelectedProjectForMenu(projectId);
    setContextMenuOpen(true);
  };

  const handleOpenProjectSettings = () => {
    if (selectedProjectForMenu) {
      setProjectIdForSettings(selectedProjectForMenu);
      setSettingsModalOpen(true);
    }
  };

  const handleRenameProject = () => {
    // For now, just open settings modal (rename in General tab)
    handleOpenProjectSettings();
  };

  const handleDuplicateProject = async () => {
    if (!selectedProjectForMenu) return;
    const project = projects.find((p) => p.id === selectedProjectForMenu);
    if (!project) return;

    // TODO: Implement duplicate logic
    toast.info("Duplicate feature coming soon!");
  };

  const handleDeleteProject = async () => {
    if (!selectedProjectForMenu) return;
    const project = projects.find((p) => p.id === selectedProjectForMenu);
    if (!project) return;

    if (!confirm(`Are you sure you want to delete "${project.name}"?`)) {
      return;
    }

    try {
      await deleteProject(selectedProjectForMenu);
      toast.success(`Project "${project.name}" deleted`);

      if (roleId) {
        await forceRefreshProjects(roleId);
      }

      // If deleted project was active, clear it
      if (projectId === selectedProjectForMenu) {
        setProjectId(null);
      }

      window.dispatchEvent(new Event("projectsUpdated"));
    } catch (error) {
      console.error("Failed to delete project:", error);
      toast.error("Failed to delete project");
    }
  };

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
    <>
      <div className="space-y-2">
        {projects.map((project) => {
          const isActive = project.id === projectId;
          const hasGit = !!project.git_url;

          return (
            <div key={project.id} className="relative group">
              <div
                onClick={() => handleProjectSelect(project)}
                className={`w-full text-left p-3 rounded-lg border transition-all cursor-pointer ${
                  isActive
                    ? "bg-primary/10 border-primary shadow-sm"
                    : "bg-surface border-border hover:border-primary/50 hover:bg-surface/80"
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <Folder
                    size={14}
                    className={
                      isActive ? "text-primary" : "text-text-secondary"
                    }
                  />
                  <span
                    className={`text-sm font-medium flex-1 ${
                      isActive ? "text-primary" : "text-text-primary"
                    }`}
                  >
                    {project.name}
                  </span>

                  {/* Git Badge */}
                  {hasGit && (
                    <span
                      className="flex items-center gap-1 text-xs text-primary"
                      title={`Linked to ${project.git_url}`}
                    >
                      <Link2 size={12} />
                    </span>
                  )}


{/* Graph Button */}
<button
  onClick={(e) => {
    e.stopPropagation();
    navigate(`/project/${project.id}/graph`);
  }}
  className="opacity-0 group-hover:opacity-100 p-1 hover:bg-primary/10 rounded transition-opacity"
  title="View Dependency Graph"
>
  <BarChart3 size={14} className="text-primary" />
</button>

                  {/* More Button (shows on hover) */}
                  <button
                    onClick={(e) => handleMoreClick(e, project.id)}
                    className="opacity-0 group-hover:opacity-100 p-1 hover:bg-surface rounded transition-opacity"
                    title="Project options"
                  >
                    <MoreVertical size={14} className="text-text-secondary" />
                  </button>
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
              </div>
            </div>
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

      {/* Context Menu */}
      <ProjectContextMenu
        isOpen={contextMenuOpen}
        onClose={() => setContextMenuOpen(false)}
        onOpenSettings={handleOpenProjectSettings}
        onRename={handleRenameProject}
        onDuplicate={handleDuplicateProject}
        onDelete={handleDeleteProject}
        anchorEl={contextMenuAnchor}
      />

      {/* Project Settings Modal */}
      {projectIdForSettings && (
        <ProjectSettingsModal
          isOpen={settingsModalOpen}
          onClose={() => {
            setSettingsModalOpen(false);
            setProjectIdForSettings(null);
          }}
          projectId={projectIdForSettings}
        />
      )}
    </>
  );
};

export default ProjectSelector;
