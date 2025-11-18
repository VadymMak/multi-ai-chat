import React, { useEffect, useState, useCallback } from "react";
import { Bot, Plus, Edit2, Trash2, Check, X, Sparkles } from "lucide-react";
import { useRoleStore } from "../../store/roleStore";
import { toast } from "../../store/toastStore";
import type { Role } from "../../store/roleStore";

const TEMPLATES = [
  {
    name: "Coding Helper",
    description:
      "You are an expert programming assistant. You help with coding tasks, debugging, code reviews, and technical questions. You write clean, efficient, and well-documented code.",
  },
  {
    name: "Writing Assistant",
    description:
      "You are a professional writing assistant. You help with writing, editing, proofreading, and content creation. You focus on clarity, grammar, and engaging storytelling.",
  },
  {
    name: "Data Analyst",
    description:
      "You are a data analysis expert. You help analyze data, create visualizations, provide insights, and explain statistical concepts. You're proficient with data analysis tools and methods.",
  },
  {
    name: "Creative Helper",
    description:
      "You are a creative assistant. You help brainstorm ideas, develop concepts, and think outside the box. You encourage innovative thinking and creative problem-solving.",
  },
];

const AssistantsTab: React.FC = () => {
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [createForm, setCreateForm] = useState({ name: "", description: "" });
  const [editForm, setEditForm] = useState({ name: "", description: "" });
  const [showTemplates, setShowTemplates] = useState(false);

  const { roles, isLoading, fetchRoles, addRole, updateRole, deleteRole } =
    useRoleStore();

  const loadRoles = useCallback(async () => {
    await fetchRoles();
  }, [fetchRoles]);

  useEffect(() => {
    loadRoles();
  }, [loadRoles]);

  const handleCreate = async () => {
    if (!createForm.name.trim() || !createForm.description.trim()) {
      toast.error("Name and description are required");
      return;
    }
    await addRole(createForm.name, createForm.description);
    toast.success("Assistant created!");
    setShowCreate(false);
    setShowTemplates(false);
    setCreateForm({ name: "", description: "" });
    await fetchRoles();

    // Trigger refresh in AssistantSelector
    window.dispatchEvent(new Event("assistantsUpdated"));
  };

  const applyTemplate = (template: (typeof TEMPLATES)[0]) => {
    setCreateForm({
      name: template.name,
      description: template.description,
    });
    setShowTemplates(false);
  };

  const startEdit = (role: Role) => {
    setEditingId(role.id);
    setEditForm({
      name: role.name,
      description: role.description || "",
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditForm({ name: "", description: "" });
  };

  const handleUpdate = async (id: number) => {
    if (!editForm.name.trim()) {
      toast.error("Name is required");
      return;
    }
    await updateRole(id, editForm);
    toast.success("Assistant updated!");
    setEditingId(null);
    await fetchRoles();

    // Trigger refresh in AssistantSelector
    window.dispatchEvent(new Event("assistantsUpdated"));
  };

  const handleDelete = async (id: number, name: string) => {
    if (window.confirm(`Delete assistant "${name}"?`)) {
      await deleteRole(id);
      toast.success("Assistant deleted!");
      await fetchRoles();

      // Trigger refresh in AssistantSelector
      window.dispatchEvent(new Event("assistantsUpdated"));
    }
  };

  if (isLoading && roles.length === 0) {
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
          <h3 className="text-lg font-semibold text-gray-100">Assistants</h3>
          <p className="text-sm text-gray-400">
            Manage your AI assistant roles and personas
          </p>
        </div>
      </div>

      {/* Assistants List */}
      <div className="space-y-3">
        {roles.map((role) => (
          <div
            key={role.id}
            className="bg-gray-800 rounded-lg p-4 border border-gray-700"
          >
            {editingId === role.id ? (
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
                    placeholder="Assistant name"
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
                    placeholder="Assistant role and behavior description"
                    rows={3}
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleUpdate(role.id)}
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
                    <Bot size={16} className="text-blue-400" />
                    <h4 className="font-medium text-gray-100">{role.name}</h4>
                  </div>
                  {role.description && (
                    <p className="text-sm text-gray-400 ml-6 line-clamp-2">
                      {role.description}
                    </p>
                  )}
                </div>
                <div className="flex gap-2 ml-4">
                  <button
                    onClick={() => startEdit(role)}
                    className="p-1.5 text-gray-400 hover:text-blue-400 hover:bg-gray-700 rounded transition-colors"
                    title="Edit assistant"
                  >
                    <Edit2 size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(role.id, role.name)}
                    className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-gray-700 rounded transition-colors"
                    title="Delete assistant"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}

        {roles.length === 0 && !showCreate && (
          <div className="text-center py-8 text-gray-400">
            <Bot size={48} className="mx-auto mb-3 opacity-50" />
            <p>No assistants yet. Create your first assistant!</p>
          </div>
        )}
      </div>

      {/* Templates */}
      {showCreate && showTemplates && (
        <div className="bg-gray-800 rounded-lg p-4 border border-purple-500">
          <h4 className="text-sm font-semibold text-gray-100 mb-3 flex items-center gap-2">
            <Sparkles size={16} className="text-purple-400" />
            Choose a Template
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {TEMPLATES.map((template) => (
              <button
                key={template.name}
                onClick={() => applyTemplate(template)}
                className="text-left p-3 bg-gray-700 hover:bg-gray-600 rounded border border-gray-600 hover:border-purple-400 transition-colors"
              >
                <div className="font-medium text-sm text-gray-100 mb-1">
                  {template.name}
                </div>
                <div className="text-xs text-gray-400 line-clamp-2">
                  {template.description}
                </div>
              </button>
            ))}
          </div>
          <button
            onClick={() => setShowTemplates(false)}
            className="mt-3 text-sm text-gray-400 hover:text-gray-300"
          >
            ← Back to custom
          </button>
        </div>
      )}

      {/* Create Form */}
      {showCreate && !showTemplates && (
        <div className="bg-gray-800 rounded-lg p-4 border border-blue-500">
          <h4 className="text-sm font-semibold text-gray-100 mb-3">
            Create New Assistant
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
                placeholder="Assistant name"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">
                Description / Instructions
              </label>
              <textarea
                value={createForm.description}
                onChange={(e) =>
                  setCreateForm({ ...createForm, description: e.target.value })
                }
                className="w-full bg-gray-700 text-gray-100 rounded px-3 py-2 text-sm border border-gray-600 focus:outline-none focus:border-blue-500"
                placeholder="Describe the assistant's role and behavior..."
                rows={4}
              />
              <button
                onClick={() => setShowTemplates(true)}
                className="mt-2 text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1"
              >
                <Sparkles size={12} />
                Use a template
              </button>
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
                  setShowTemplates(false);
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
          <span className="font-medium">Create New Assistant</span>
        </button>
      )}
    </div>
  );
};

export default AssistantsTab;
