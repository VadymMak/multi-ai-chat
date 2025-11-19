import React, { useEffect, useState } from "react";
import {
  Folder,
  Plus,
  Edit2,
  Trash2,
  Check,
  X,
  Sparkles,
  ArrowLeft,
} from "lucide-react";
import { useProjectStore } from "../../store/projectStore";
import { useRoleStore } from "../../store/roleStore";
import { toast } from "../../store/toastStore";
import type { Project } from "../../types/projects";
import {
  ASSISTANT_TEMPLATES,
  type AssistantTemplate,
} from "../../constants/assistantTemplates";

const ProjectsTab: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);

  // Assistant selection states
  const [selectedAssistantId, setSelectedAssistantId] = useState<number | null>(
    null
  );
  const [showAssistantModal, setShowAssistantModal] = useState(false);
  const [customAssistantForm, setCustomAssistantForm] = useState({
    name: "",
    description: "",
  });

  // Form states
  const [createForm, setCreateForm] = useState({ name: "", description: "" });
  const [editForm, setEditForm] = useState({ name: "", description: "" });

  const { fetchAllProjects, createProject, updateProject, deleteProject } =
    useProjectStore();
  const { roles, fetchRoles, addRole } = useRoleStore();

  // Load data once on mount
  useEffect(() => {
    const loadData = async () => {
      setIsLoading(true);
      try {
        const projectData = await fetchAllProjects();
        setProjects(projectData);
        await fetchRoles();
      } catch (error) {
        console.error("Failed to load data:", error);
      } finally {
        setIsLoading(false);
      }
    };

    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Run once on mount - store methods are stable

  // Helper function to reload projects (used after create/update/delete)
  const loadProjects = async () => {
    setIsLoading(true);
    const data = await fetchAllProjects();
    setProjects(data);
    setIsLoading(false);
  };

  const handleSelectTemplate = async (template: AssistantTemplate) => {
    // Check if role already exists
    let role = roles.find((r) => r.name === template.name);

    if (!role) {
      // Role doesn't exist, create it
      console.log(`📝 Creating new role: ${template.name}`);
      await addRole(template.name, template.systemPrompt);
      await fetchRoles();

      // Find the newly created assistant
      role = roles.find((r) => r.name === template.name);
    } else {
      // Role exists, reuse it
      console.log(
        `✅ Reusing existing role: ${template.name} (id: ${role.id})`
      );
    }

    if (role) {
      setSelectedAssistantId(role.id);
      toast.success(`${template.name} template applied!`);
    }
  };

  const handleCreateCustomAssistant = async () => {
    if (
      !customAssistantForm.name.trim() ||
      !customAssistantForm.description.trim()
    ) {
      toast.error("Name and description are required");
      return;
    }

    // Check if role already exists
    let customRole = roles.find((r) => r.name === customAssistantForm.name);

    if (!customRole) {
      // Role doesn't exist, create it
      console.log(`📝 Creating new custom role: ${customAssistantForm.name}`);
      await addRole(customAssistantForm.name, customAssistantForm.description);
      await fetchRoles();

      // Find the newly created assistant
      customRole = roles.find((r) => r.name === customAssistantForm.name);
    } else {
      // Role exists, reuse it
      console.log(
        `✅ Reusing existing custom role: ${customAssistantForm.name} (id: ${customRole.id})`
      );
    }

    if (customRole) {
      setSelectedAssistantId(customRole.id);
      setShowAssistantModal(false);
      setCustomAssistantForm({ name: "", description: "" });
      toast.success("Custom assistant created!");
    }
  };

  const handleCreate = async () => {
    if (!createForm.name.trim()) {
      toast.error("Project name is required");
      return;
    }
    if (!selectedAssistantId) {
      toast.error("Please select an assistant");
      return;
    }

    const newProject = await createProject({
      ...createForm,
      assistant_id: selectedAssistantId,
    });

    if (newProject) {
      toast.success("Project created!");

      // Initialize session for the new project immediately
      console.log("✅ Project created, initializing session...");

      try {
        // Get the SessionManager
        const { sessionManager } = await import(
          "../../services/SessionManager"
        );

        // Get the newly created project ID and role ID
        const newProjectId = newProject.id;
        const roleId = selectedAssistantId;

        // Set the project in projectStore
        const { setProjectId } = useProjectStore.getState();
        setProjectId(newProjectId);

        // Set the role in memoryStore
        const selectedRole = roles.find((r) => r.id === roleId);
        if (selectedRole) {
          const { useMemoryStore } = await import("../../store/memoryStore");
          useMemoryStore.getState().setRole({
            id: selectedRole.id,
            name: selectedRole.name,
          });
        }

        // Initialize the chat session for this project
        const { useChatStore } = await import("../../store/chatStore");
        await useChatStore
          .getState()
          .initializeChatSession(newProjectId, roleId);

        console.log("✅ Session initialized for new project");
      } catch (error) {
        console.error("❌ Failed to initialize session:", error);
      }

      setShowCreate(false);
      setCreateForm({ name: "", description: "" });
      setSelectedAssistantId(null);
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

  const cancelCreate = () => {
    setShowCreate(false);
    setCreateForm({ name: "", description: "" });
    setSelectedAssistantId(null);
    setShowAssistantModal(false);
    setCustomAssistantForm({ name: "", description: "" });
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
            Create projects and choose assistants with specific expertise
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
                    <p className="text-sm text-gray-400 ml-6 mb-2">
                      {project.description}
                    </p>
                  )}
                  {project.assistant && (
                    <div className="flex items-center gap-2 ml-6 text-xs text-gray-500">
                      <span>🤖</span>
                      <span>{project.assistant.name}</span>
                    </div>
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
            {/* Project Name */}
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">
                Project Name
              </label>
              <input
                type="text"
                value={createForm.name}
                onChange={(e) =>
                  setCreateForm({ ...createForm, name: e.target.value })
                }
                className="w-full bg-gray-700 text-gray-100 rounded px-3 py-2 text-sm border border-gray-600 focus:outline-none focus:border-blue-500"
                placeholder="Enter project name"
                autoFocus
              />
            </div>

            {/* Project Description */}
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

            {/* Assistant Selection */}
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Choose Assistant
              </label>

              {!showAssistantModal ? (
                <div className="space-y-2">
                  {/* Template Grid */}
                  <div className="grid grid-cols-2 gap-2">
                    {ASSISTANT_TEMPLATES.map((template) => (
                      <button
                        key={template.id}
                        onClick={() => handleSelectTemplate(template)}
                        className={`text-left p-3 rounded-lg border transition-all ${
                          selectedAssistantId &&
                          roles.find((a) => a.id === selectedAssistantId)
                            ?.name === template.name
                            ? "border-blue-500 bg-blue-500/10"
                            : "border-gray-600 bg-gray-700 hover:border-blue-400"
                        }`}
                      >
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-lg">{template.icon}</span>
                          <span className="text-sm font-medium text-gray-100">
                            {template.name}
                          </span>
                        </div>
                        <p className="text-xs text-gray-400 line-clamp-2">
                          {template.description}
                        </p>
                      </button>
                    ))}
                  </div>

                  {/* Custom Assistant Option */}
                  <button
                    onClick={() => setShowAssistantModal(true)}
                    className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-gray-700 hover:bg-gray-600 text-purple-400 rounded-lg border border-gray-600 hover:border-purple-500 transition-colors"
                  >
                    <Sparkles size={16} />
                    <span className="text-sm font-medium">
                      Create Custom Assistant
                    </span>
                  </button>

                  {/* Show selected assistant */}
                  {selectedAssistantId && (
                    <div className="mt-2 p-2 bg-blue-500/10 border border-blue-500/30 rounded text-xs text-gray-300">
                      ✓ Selected:{" "}
                      {roles.find((a) => a.id === selectedAssistantId)?.name}
                    </div>
                  )}
                </div>
              ) : (
                // Custom Assistant Modal
                <div className="bg-gray-700 rounded-lg p-4 border border-purple-500">
                  <div className="flex items-center justify-between mb-3">
                    <h5 className="text-sm font-semibold text-gray-100">
                      Create Custom Assistant
                    </h5>
                    <button
                      onClick={() => {
                        setShowAssistantModal(false);
                        setCustomAssistantForm({ name: "", description: "" });
                      }}
                      className="text-gray-400 hover:text-gray-200"
                    >
                      <ArrowLeft size={16} />
                    </button>
                  </div>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-300 mb-1">
                        Assistant Name
                      </label>
                      <input
                        type="text"
                        value={customAssistantForm.name}
                        onChange={(e) =>
                          setCustomAssistantForm({
                            ...customAssistantForm,
                            name: e.target.value,
                          })
                        }
                        className="w-full bg-gray-600 text-gray-100 rounded px-3 py-2 text-sm border border-gray-500 focus:outline-none focus:border-purple-500"
                        placeholder="e.g., Business Analyst"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-300 mb-1">
                        Instructions / System Prompt
                      </label>
                      <textarea
                        value={customAssistantForm.description}
                        onChange={(e) =>
                          setCustomAssistantForm({
                            ...customAssistantForm,
                            description: e.target.value,
                          })
                        }
                        className="w-full bg-gray-600 text-gray-100 rounded px-3 py-2 text-sm border border-gray-500 focus:outline-none focus:border-purple-500"
                        placeholder="Describe the assistant's role and behavior..."
                        rows={4}
                      />
                    </div>
                    <button
                      onClick={handleCreateCustomAssistant}
                      className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white text-sm rounded transition-colors"
                    >
                      <Check size={14} />
                      Create Assistant
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Action Buttons */}
            <div className="flex gap-2 pt-2">
              <button
                onClick={handleCreate}
                disabled={!selectedAssistantId}
                className="flex items-center gap-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white text-sm rounded transition-colors"
              >
                <Check size={14} />
                Create Project
              </button>
              <button
                onClick={cancelCreate}
                className="flex items-center gap-1 px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white text-sm rounded transition-colors"
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
