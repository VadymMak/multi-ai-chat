import React, { useEffect, useState, useCallback } from "react";
import { Folder, Plus, Edit2, Trash2, Check, X } from "lucide-react";
import { useProjectStore } from "../../store/projectStore";
import { toast } from "../../store/toastStore";
import type { Project } from "../../store/projectStore";

const ProjectsTab: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);

  // Form states
  const [createForm, setCreateForm] = useState({ name: "", description: "" });
  const [editForm, setEditForm] = useState({ name: "", description: "" });

  const { fetchAllProjects, createProject, updateProject, deleteProject } =
    useProjectStore();

  // Wrap loadProjects in useCallback to prevent infinite loop
  const loadProjects = useCallback(async () => {
    setIsLoading(true);
    const data = await fetchAllProjects();
    setProjects(data);
    setIsLoading(false);
  }, [fetchAllProjects]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const handleCreate = async () => {
    if (!createForm.name.trim()) {
      toast.error("Project name is required");
      return;
    }
    const newProject = await createProject(createForm);
    if (newProject) {
      toast.success("Project created!");
      setShowCreate(false);
      setCreateForm({ name: "", description: "" });
      await loadProjects();

      // Trigger refresh in ProjectSelector
      window.dispatchEvent(new Event("projectsUpdated"));
    } else {
      toast.error("Failed to create project");
    }
  };

  const startEdit = (project: Project) => {
    setEditingId(project.id);
    setEditForm({
      name: project.name,
      description: project.description || "",
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditForm({ name: "", description: "" });
  };

  const handleUpdate = async (id: number) => {
    if (!editForm.name.trim()) {
      toast.error("Project name is required");
      return;
    }
    try {
      await updateProject(id, editForm);
      toast.success("Project updated!");
      setEditingId(null);
      await loadProjects();

      // Trigger refresh in ProjectSelector
      window.dispatchEvent(new Event("projectsUpdated"));
    } catch (error) {
      toast.error("Failed to update project");
    }
  };

  const handleDelete = async (id: number, name: string) => {
    if (window.confirm(`Delete project "${name}"?`)) {
      try {
        await deleteProject(id);
        toast.success("Project deleted!");
        await loadProjects();

        // Trigger refresh in ProjectSelector
        window.dispatchEvent(new Event("projectsUpdated"));
      } catch (error) {
        toast.error("Failed to delete project");
      }
    }
  };

  if (isLoading && projects.length === 0) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-100">Projects</h3>
          <p className="text-sm text-gray-400">
            Manage your projects and contexts
          </p>
        </div>
      </div>

      {/* Projects List */}
      <div className="space-y-3">
        {projects.map((project) => (
          <div
            key={project.id}
            className="bg-gray-800 rounded-lg p-4 border border-gray-700"
          >
            {editingId === project.id ? (
              // Edit Mode
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">
                    Name
                  </label>
                  <input
                    type="text"
                    value={editForm.name}
                    onChange={(e) =>
                      setEditForm({ ...editForm, name: e.target.value })
                    }
                    className="w-full bg-gray-700 text-gray-100 rounded px-3 py-2 text-sm border border-gray-600 focus:outline-none focus:border-blue-500"
                    placeholder="Project name"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">
                    Description
                  </label>
                  <textarea
                    value={editForm.description}
                    onChange={(e) =>
                      setEditForm({ ...editForm, description: e.target.value })
                    }
                    className="w-full bg-gray-700 text-gray-100 rounded px-3 py-2 text-sm border border-gray-600 focus:outline-none focus:border-blue-500"
                    placeholder="Project description (optional)"
                    rows={2}
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleUpdate(project.id)}
                    className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors"
                  >
                    <Check size={14} />
                    Save
                  </button>
                  <button
                    onClick={cancelEdit}
                    className="flex items-center gap-1 px-3 py-1.5 bg-gray-600 hover:bg-gray-700 text-white text-sm rounded transition-colors"
                  >
                    <X size={14} />
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              // View Mode
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <Folder size={16} className="text-blue-400" />
                    <h4 className="font-medium text-gray-100">
                      {project.name}
                    </h4>
                  </div>
                  {project.description && (
                    <p className="text-sm text-gray-400 ml-6">
                      {project.description}
                    </p>
                  )}
                </div>
                <div className="flex gap-2 ml-4">
                  <button
                    onClick={() => startEdit(project)}
                    className="p-1.5 text-gray-400 hover:text-blue-400 hover:bg-gray-700 rounded transition-colors"
                    title="Edit project"
                  >
                    <Edit2 size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(project.id, project.name)}
                    className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-gray-700 rounded transition-colors"
                    title="Delete project"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}

        {projects.length === 0 && !showCreate && (
          <div className="text-center py-8 text-gray-400">
            <Folder size={48} className="mx-auto mb-3 opacity-50" />
            <p>No projects yet. Create your first project!</p>
          </div>
        )}
      </div>

      {/* Create Form */}
      {showCreate && (
        <div className="bg-gray-800 rounded-lg p-4 border border-blue-500">
          <h4 className="text-sm font-semibold text-gray-100 mb-3">
            Create New Project
          </h4>
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">
                Name
              </label>
              <input
                type="text"
                value={createForm.name}
                onChange={(e) =>
                  setCreateForm({ ...createForm, name: e.target.value })
                }
                className="w-full bg-gray-700 text-gray-100 rounded px-3 py-2 text-sm border border-gray-600 focus:outline-none focus:border-blue-500"
                placeholder="Project name"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">
                Description
              </label>
              <textarea
                value={createForm.description}
                onChange={(e) =>
                  setCreateForm({ ...createForm, description: e.target.value })
                }
                className="w-full bg-gray-700 text-gray-100 rounded px-3 py-2 text-sm border border-gray-600 focus:outline-none focus:border-blue-500"
                placeholder="Project description (optional)"
                rows={2}
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleCreate}
                className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors"
              >
                <Check size={14} />
                Create
              </button>
              <button
                onClick={() => {
                  setShowCreate(false);
                  setCreateForm({ name: "", description: "" });
                }}
                className="flex items-center gap-1 px-3 py-1.5 bg-gray-600 hover:bg-gray-700 text-white text-sm rounded transition-colors"
              >
                <X size={14} />
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Button */}
      {!showCreate && (
        <button
          onClick={() => setShowCreate(true)}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-gray-800 hover:bg-gray-700 text-blue-400 rounded-lg border border-gray-700 hover:border-blue-500 transition-colors"
        >
          <Plus size={18} />
          <span className="font-medium">Create New Project</span>
        </button>
      )}
    </div>
  );
};

export default ProjectsTab;
