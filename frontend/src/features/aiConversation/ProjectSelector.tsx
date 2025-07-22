// src/features/aiConversations/ProjectSelector.tsx

import React, { useEffect, useState, useCallback } from "react";
import { AxiosError } from "axios";
import api from "../../services/api";
import { useProjectStore } from "../../store/projectStore";
import { useMemoryStore } from "../../store/memoryStore";
import { useChatStore } from "../../store/chatStore";
import { v4 as uuidv4 } from "uuid";

interface ProjectOption {
  id: number;
  name: string;
  description?: string;
}

const ProjectSelector: React.FC = () => {
  const role = useMemoryStore((state) => state.role);
  const roleId = typeof role?.id === "number" ? role.id : null;

  const { projectId, setProjectId } = useProjectStore();
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [custom, setCustom] = useState("");

  const setChatSessionId = useChatStore((state) => state.setChatSessionId);

  const refetchProjects = useCallback(async () => {
    if (!roleId) return;

    try {
      const res = await api.get<ProjectOption[]>("/projects/by-role", {
        params: { role_id: roleId },
      });
      setProjects(res.data);
    } catch (error) {
      const err = error as AxiosError;
      console.error("❌ Failed to fetch projects:", err.message);
    }
  }, [roleId]);

  useEffect(() => {
    if (roleId) {
      refetchProjects();
    }
  }, [refetchProjects, roleId]);

  const handleSet = useCallback(async () => {
    const trimmed = custom.trim();
    if (!trimmed || !roleId) return;

    try {
      await api.post("/projects/create-and-link", {
        name: trimmed,
        description: "Custom user-created project",
        role_id: roleId,
      });

      await refetchProjects();

      const created = projects.find((p) => p.name === trimmed);
      if (created) {
        setProjectId(created.id);
        const newSessionId = uuidv4();
        setChatSessionId(newSessionId);
        console.log("🆕 Chat session started for new project:", newSessionId);
      }

      setCustom("");
    } catch (error) {
      const err = error as AxiosError;
      console.error("❌ Failed to create/link project:", err.message);
    }
  }, [
    custom,
    roleId,
    setProjectId,
    refetchProjects,
    projects,
    setChatSessionId,
  ]);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const parsedId = parseInt(e.target.value, 10);
      if (!Number.isNaN(parsedId)) {
        setProjectId(parsedId);
        const newSessionId = uuidv4();
        setChatSessionId(newSessionId);
        console.log("🔁 Switched project — new chat session:", newSessionId);
      }
    },
    [setProjectId, setChatSessionId]
  );

  const handleInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setCustom(e.target.value);
  }, []);

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
      />

      <button
        onClick={handleSet}
        className="bg-green-500 text-white px-3 py-1 text-sm rounded hover:bg-green-600"
      >
        Add
      </button>
    </div>
  );
};

export default ProjectSelector;
