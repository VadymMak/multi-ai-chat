// src/features/aiConversation/ProjectSelector.tsx
import React, { useState } from "react";
import { useProjectStore } from "../../store/projectStore";

const ProjectSelector: React.FC = () => {
  const { projectId, recentProjects, setProjectId } = useProjectStore();
  const [custom, setCustom] = useState("");

  const handleSet = () => {
    const trimmed = custom.trim();
    if (trimmed && !recentProjects.includes(trimmed)) {
      setProjectId(trimmed);
      setCustom("");
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 ml-4 pl-2">
      <label
        htmlFor="project-select"
        className="text-sm font-medium text-gray-700 whitespace-nowrap"
      >
        📁 Project:
      </label>

      <select
        id="project-select"
        aria-label="Project selector"
        value={projectId}
        onChange={(e) => setProjectId(e.target.value)}
        className="px-2 py-1 rounded border text-sm bg-white"
      >
        {recentProjects.length === 0 && <option value="">No projects</option>}
        {recentProjects.map((proj, i) => (
          <option key={i} value={proj}>
            {proj}
          </option>
        ))}
      </select>

      <input
        type="text"
        value={custom}
        onChange={(e) => setCustom(e.target.value)}
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
