import React from "react";
import { useMemoryStore } from "../../store/memoryStore";
import { MemoryRole } from "../../types/memory";

const roles: MemoryRole[] = [
  "LLM Engineer",
  "Vessel Engineer",
  "ML Engineer",
  "Data Scientist",
  "Frontend Developer",
  "Python Developer",
  "Esoteric Knowledge",
];

const MemoryRoleSelector: React.FC = () => {
  const currentRole = useMemoryStore((state) => state.role);
  const setRole = useMemoryStore((state) => state.setRole);

  return (
    <div className="flex flex-wrap gap-2 bg-white border border-gray-200 p-3 rounded-xl shadow-sm">
      {roles.map((role) => (
        <button
          key={role}
          onClick={() => setRole(role)}
          className={`px-3 py-1.5 rounded-full text-sm font-medium border transition whitespace-nowrap
            ${
              currentRole === role
                ? "bg-purple-600 text-white border-purple-600 ring-2 ring-purple-300"
                : "bg-white text-gray-700 border-gray-300 hover:bg-purple-50"
            }`}
        >
          {role}
        </button>
      ))}
    </div>
  );
};

export default MemoryRoleSelector;
