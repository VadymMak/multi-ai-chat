// src/components/Settings/ProjectSettingsModal.tsx
import React, { useState, useEffect } from "react";
import { X, FolderOpen, GitBranch, BarChart3 } from "lucide-react";
import GitIntegrationPanel from "./GitIntegrationPanel";
import { useProjectStore } from "../../store/projectStore";
import { toast } from "../../store/toastStore";
import type { Project } from "../../types/projects";

interface ProjectSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: number;
}

type TabType = "general" | "git" | "stats";

const ProjectSettingsModal: React.FC<ProjectSettingsModalProps> = ({
  isOpen,
  onClose,
  projectId,
}) => {
  const [activeTab, setActiveTab] = useState<TabType>("general");
  const [project, setProject] = useState<Project | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Form state for General tab
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const updateProject = useProjectStore((state) => state.updateProject);
  const forceRefreshProjects = useProjectStore(
    (state) => state.forceRefreshProjects
  );

  // Load project data
  useEffect(() => {
    if (isOpen && projectId) {
      loadProject();
    }
  }, [isOpen, projectId]);

  const loadProject = async () => {
    setIsLoading(true);
    try {
      // Get project from store or fetch
      const allProjects = useProjectStore.getState().allProjects;
      let proj = allProjects.find((p) => p.id === projectId);

      if (!proj) {
        // Fetch if not in cache
        await useProjectStore.getState().fetchAllProjects();
        const updated = useProjectStore.getState().allProjects;
        proj = updated.find((p) => p.id === projectId);
      }

      if (proj) {
        setProject(proj);
        setName(proj.name);
        setDescription(proj.description || "");
      }
    } catch (error) {
      console.error("Failed to load project:", error);
      toast.error("Failed to load project");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveGeneral = async () => {
    if (!name.trim()) {
      toast.error("Project name is required");
      return;
    }

    try {
      await updateProject(projectId, {
        name: name.trim(),
        description: description.trim(),
      });

      toast.success("Project updated successfully!");

      // Refresh projects in all roles
      const projectsByRole = useProjectStore.getState().projectsByRole;
      const roleIds = Object.keys(projectsByRole).map(Number);

      for (const roleId of roleIds) {
        await forceRefreshProjects(roleId);
      }

      // Dispatch event for ProjectSelector
      window.dispatchEvent(new Event("projectsUpdated"));

      onClose();
    } catch (error) {
      console.error("Failed to update project:", error);
      toast.error("Failed to update project");
    }
  };

  const handleProjectUpdated = () => {
    // Reload project data after Git operations
    loadProject();
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl max-h-[90vh] bg-panel border border-border rounded-2xl shadow-2xl overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-surface">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center">
              <FolderOpen className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h2 className="text-xl font-semibold text-text-primary">
                Project Settings
              </h2>
              <p className="text-xs text-text-secondary">
                {project?.name || "Loading..."}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-surface transition text-text-secondary hover:text-text-primary"
          >
            <X size={20} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-border bg-surface/50 px-6">
          <TabButton
            active={activeTab === "general"}
            onClick={() => setActiveTab("general")}
            icon={<FolderOpen size={16} />}
            label="General"
          />
          <TabButton
            active={activeTab === "git"}
            onClick={() => setActiveTab("git")}
            icon={<GitBranch size={16} />}
            label="Git"
          />
          <TabButton
            active={activeTab === "stats"}
            onClick={() => setActiveTab("stats")}
            icon={<BarChart3 size={16} />}
            label="Stats"
          />
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <div className="text-text-secondary">Loading...</div>
            </div>
          ) : (
            <>
              {/* GENERAL TAB */}
              {activeTab === "general" && project && (
                <div className="space-y-6">
                  <Section title="Basic Information">
                    <div className="space-y-4">
                      <div>
                        <label className="block text-sm font-medium text-text-primary mb-2">
                          Project Name *
                        </label>
                        <input
                          type="text"
                          value={name}
                          onChange={(e) => setName(e.target.value)}
                          placeholder="Enter project name"
                          className="w-full px-4 py-2 bg-surface border border-border rounded-lg text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-primary transition"
                        />
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-text-primary mb-2">
                          Description
                        </label>
                        <textarea
                          value={description}
                          onChange={(e) => setDescription(e.target.value)}
                          placeholder="Enter project description (optional)"
                          rows={4}
                          className="w-full px-4 py-2 bg-surface border border-border rounded-lg text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-primary transition resize-none"
                        />
                      </div>
                    </div>
                  </Section>

                  <Section title="Assistant">
                    <div className="p-4 bg-surface border border-border rounded-lg">
                      {project.assistant ? (
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                            <span className="text-lg">🤖</span>
                          </div>
                          <div>
                            <p className="text-sm font-medium text-text-primary">
                              {project.assistant.name}
                            </p>
                            <p className="text-xs text-text-secondary">
                              {project.assistant.description}
                            </p>
                          </div>
                        </div>
                      ) : (
                        <p className="text-sm text-text-secondary">
                          No assistant assigned
                        </p>
                      )}
                    </div>
                  </Section>
                </div>
              )}

              {/* GIT TAB */}
              {activeTab === "git" && project && (
                <GitIntegrationPanel
                  project={project}
                  onProjectUpdated={handleProjectUpdated}
                />
              )}

              {/* STATS TAB */}
              {activeTab === "stats" && project && (
                <div className="space-y-6">
                  <Section title="Project Information">
                    <div className="grid grid-cols-2 gap-4">
                      <StatCard
                        label="Project ID"
                        value={project.id.toString()}
                      />
                      <StatCard
                        label="Created"
                        value={
                          project.created_at
                            ? new Date(project.created_at).toLocaleDateString()
                            : "N/A"
                        }
                      />
                      <StatCard
                        label="Last Updated"
                        value={
                          project.updated_at
                            ? new Date(project.updated_at).toLocaleDateString()
                            : "N/A"
                        }
                      />
                      <StatCard
                        label="Git Status"
                        value={
                          project.git_url
                            ? project.git_sync_status || "Linked"
                            : "Not linked"
                        }
                      />
                    </div>
                  </Section>

                  {project.git_url && (
                    <Section title="Git Repository">
                      <div className="p-4 bg-surface border border-border rounded-lg">
                        <p className="text-xs text-text-secondary mb-1">
                          Repository URL
                        </p>
                        <p className="text-sm text-text-primary font-mono break-all">
                          {project.git_url}
                        </p>
                        {project.git_updated_at && (
                          <p className="text-xs text-text-secondary mt-2">
                            Last synced:{" "}
                            {new Date(project.git_updated_at).toLocaleString()}
                          </p>
                        )}
                      </div>
                    </Section>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {activeTab === "general" && !isLoading && (
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border bg-surface">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-text-secondary hover:text-text-primary transition"
            >
              Cancel
            </button>
            <button
              onClick={handleSaveGeneral}
              className="px-6 py-2 text-sm font-medium bg-primary text-white rounded-lg hover:opacity-90 transition"
            >
              Save Changes
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

// ========== HELPER COMPONENTS ==========

const TabButton: React.FC<{
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}> = ({ active, onClick, icon, label }) => (
  <button
    onClick={onClick}
    className={`px-4 py-3 text-sm font-medium transition border-b-2 whitespace-nowrap ${
      active
        ? "border-primary text-primary"
        : "border-transparent text-text-secondary hover:text-text-primary"
    }`}
  >
    <div className="flex items-center gap-2">
      {icon}
      {label}
    </div>
  </button>
);

const Section: React.FC<{
  title: string;
  children: React.ReactNode;
}> = ({ title, children }) => (
  <div>
    <h3 className="text-base font-semibold text-text-primary mb-4">{title}</h3>
    {children}
  </div>
);

const StatCard: React.FC<{
  label: string;
  value: string;
}> = ({ label, value }) => (
  <div className="p-4 bg-surface border border-border rounded-lg">
    <p className="text-xs text-text-secondary mb-1">{label}</p>
    <p className="text-sm font-medium text-text-primary">{value}</p>
  </div>
);

export default ProjectSettingsModal;
