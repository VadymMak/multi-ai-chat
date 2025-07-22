import React, { useEffect, useState, useCallback, useRef } from "react";
import { AxiosError } from "axios";
import api from "../../services/api";
import { useProjectStore } from "../../store/projectStore";
import { useMemoryStore } from "../../store/memoryStore";
import type { ProjectOption } from "../../types/projects";
import { runSessionFlow } from "../../controllers/runSessionFlow";

const ProjectSelector: React.FC = () => {
  const role = useMemoryStore((state) => state.role);
  const roleId = typeof role?.id === "number" ? role.id : null;

  const {
    projectId,
    setProjectId,
    fetchProjectsForRole,
    forceRefreshProjects,
  } = useProjectStore();

  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [custom, setCustom] = useState("");
  const [loading, setLoading] = useState(false);
  const selectVersion = useRef(0);

  // 🔄 Load projects for selected role
  const loadProjects = useCallback(async () => {
    const version = ++selectVersion.current;

    if (!roleId) {
      setProjects([]);
      return;
    }

    try {
      const loaded = await fetchProjectsForRole(roleId);
      const sanitized = loaded.map((p) => ({
        ...p,
        description: p.description ?? undefined,
      }));

      if (version !== selectVersion.current) return;
      setProjects(sanitized);
    } catch (err) {
      console.error("❌ [ProjectSelector] Failed to fetch projects:", err);
      setProjects([]);
    }
  }, [roleId, fetchProjectsForRole]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  // 🧠 Project selection handler
  const handleChange = useCallback(
    async (e: React.ChangeEvent<HTMLSelectElement>) => {
      const newId = parseInt(e.target.value, 10);
      if (Number.isNaN(newId) || !roleId || newId === projectId) return;

      const version = ++selectVersion.current;
      setLoading(true);
      setProjectId(newId);

      try {
        await runSessionFlow(roleId, newId, "ProjectSelector");
        if (version !== selectVersion.current) return;
      } catch (err) {
        console.error("❌ [ProjectSelector] Session init failed:", err);
      } finally {
        if (version === selectVersion.current) setLoading(false);
      }
    },
    [roleId, projectId, setProjectId]
  );

  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => setCustom(e.target.value),
    []
  );

  // ➕ Create new project
  const handleCreateProject = useCallback(async () => {
    const trimmed = custom.trim();
    if (!trimmed || !roleId) return;

    setLoading(true);
    const version = ++selectVersion.current;

    try {
      const response = await api.post<ProjectOption>(
        "/projects/create-and-link",
        {
          name: trimmed,
          description: "Custom user-created project",
          role_id: roleId,
        }
      );

      const newProject = response.data;
      setCustom("");

      // 🔁 Refresh from backend to populate into store cache
      await forceRefreshProjects(roleId);
      await loadProjects();

      setProjectId(newProject.id);
      await runSessionFlow(roleId, newProject.id, "ProjectSelector[Create]");

      if (version !== selectVersion.current) return;
    } catch (err) {
      const error = err as AxiosError;
      console.error("❌ [ProjectSelector] Create failed:", error.message);
    } finally {
      if (version === selectVersion.current) setLoading(false);
    }
  }, [custom, roleId, setProjectId, loadProjects, forceRefreshProjects]);

  return (
    <div className="flex flex-wrap items-center gap-2 ml-4 pl-2 p-2">
      <label
        htmlFor="project-select"
        className="text-sm font-medium text-gray-700 whitespace-nowrap"
      >
        📁 Project:
      </label>

      <select
        id="project-select"
        value={projectId ?? ""}
        onChange={handleChange}
        className="px-2 py-1 rounded border text-sm bg-white"
        disabled={loading || !roleId}
      >
        {projects.length === 0 && <option value="">No linked projects</option>}
        {projects.map((proj) => (
          <option key={proj.id} value={proj.id.toString()}>
            {proj.name}
          </option>
        ))}
      </select>

      <input
        type="text"
        value={custom}
        onChange={handleInput}
        placeholder="New project..."
        className="border rounded px-2 py-1 text-sm"
        disabled={loading}
      />

      <button
        onClick={handleCreateProject}
        disabled={!custom.trim() || !roleId || loading}
        className="bg-green-500 text-white px-3 py-1 text-sm rounded hover:bg-green-600 disabled:opacity-50"
      >
        Add
      </button>
    </div>
  );
};

export default ProjectSelector;
