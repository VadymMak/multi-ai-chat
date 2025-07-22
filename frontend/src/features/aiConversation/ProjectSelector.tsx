// File: src/features/aiConversation/ProjectSelector.tsx
import React, { useEffect, useState, useCallback, useRef } from "react";
import { AxiosError } from "axios";
import api from "../../services/api";
import { useProjectStore } from "../../store/projectStore";
import { useMemoryStore } from "../../store/memoryStore";
import type { ProjectOption } from "../../types/projects";
import { runSessionFlow } from "../../controllers/runSessionFlow";
import { useShallow } from "zustand/shallow";

const ProjectSelector: React.FC = () => {
  // Stable selector for roleId (prevents extra renders)
  const roleId = useMemoryStore(
    useCallback((s) => (typeof s.role?.id === "number" ? s.role!.id : null), [])
  );

  // Pull only what we need from the store (shallow compare)
  const {
    projectId,
    setProjectId,
    fetchProjectsForRole,
    forceRefreshProjects,
  } = useProjectStore(
    useShallow((s) => ({
      projectId: s.projectId,
      setProjectId: s.setProjectId,
      fetchProjectsForRole: s.fetchProjectsForRole,
      forceRefreshProjects: s.forceRefreshProjects,
    }))
  );

  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [custom, setCustom] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false); // UI spinner only; never disables the <select>
  const selectVersion = useRef(0);

  // ────────────────────────────────────────────────────────────────────────────
  // Load projects for current role (race-safe)
  // ────────────────────────────────────────────────────────────────────────────
  const loadProjects = useCallback(async () => {
    const version = ++selectVersion.current;

    if (!roleId) {
      setProjects([]);
      return;
    }

    try {
      const loaded = (await fetchProjectsForRole(roleId)) as ProjectOption[];
      const sanitized = loaded.map((p) => ({
        ...p,
        description: p.description ?? undefined,
      }));

      if (version !== selectVersion.current) return; // stale
      setProjects(sanitized);

      // Auto-select first if none selected yet (one-time per role)
      if (!projectId && sanitized.length > 0) {
        const firstId = sanitized[0].id;
        setProjectId(firstId);
        // fire-and-forget (flow is internally idempotent)
        void runSessionFlow(roleId, firstId, "ProjectSelector[Auto]");
      }
    } catch (err) {
      console.error("❌ [ProjectSelector] Failed to fetch projects:", err);
      if (version === selectVersion.current) setProjects([]);
    }
  }, [roleId, projectId, fetchProjectsForRole, setProjectId]);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  // Reset local list when role clears
  useEffect(() => {
    if (!roleId) {
      setProjects([]);
    }
  }, [roleId]);

  // ────────────────────────────────────────────────────────────────────────────
  // Handlers
  // ────────────────────────────────────────────────────────────────────────────
  const handleChange = useCallback(
    async (e: React.ChangeEvent<HTMLSelectElement>) => {
      const newId = parseInt(e.target.value, 10);
      if (Number.isNaN(newId) || !roleId || newId === projectId) return;

      ++selectVersion.current;
      setLoading(true);
      setProjectId(newId);

      try {
        await runSessionFlow(roleId, newId, "ProjectSelector");
      } catch (err) {
        console.error("❌ [ProjectSelector] Session init failed:", err);
      } finally {
        setLoading(false);
      }
    },
    [roleId, projectId, setProjectId]
  );

  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => setCustom(e.target.value),
    []
  );

  const handleCreateProject = useCallback(async () => {
    const trimmed = custom.trim();
    if (!trimmed || !roleId) return;

    setLoading(true);
    ++selectVersion.current;

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

      // Refresh caches & local list
      await forceRefreshProjects(roleId);
      await loadProjects();

      setProjectId(newProject.id);
      await runSessionFlow(roleId, newProject.id, "ProjectSelector[Create]");
    } catch (err) {
      const error = err as AxiosError;
      console.error("❌ [ProjectSelector] Create failed:", error.message);
    } finally {
      setLoading(false);
    }
  }, [custom, roleId, setProjectId, loadProjects, forceRefreshProjects]);

  // ────────────────────────────────────────────────────────────────────────────
  // UI
  // ────────────────────────────────────────────────────────────────────────────
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
        // Keep interactive even while loading to avoid “stuck” state
        disabled={!roleId}
        aria-busy={loading || undefined}
      >
        {projects.length === 0 && <option value="">No linked projects</option>}
        {projects.map((proj: ProjectOption) => (
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
        disabled={!roleId}
      />

      <button
        type="button"
        onClick={handleCreateProject}
        disabled={!custom.trim() || !roleId}
        className="bg-green-500 text-white px-3 py-1 text-sm rounded hover:bg-green-600 disabled:opacity-50"
        aria-busy={loading || undefined}
      >
        {loading ? "Working…" : "Add"}
      </button>
    </div>
  );
};

export default ProjectSelector;
