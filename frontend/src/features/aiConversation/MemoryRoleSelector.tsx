import React, { useEffect, useCallback, useMemo } from "react";
import { useMemoryStore } from "../../store/memoryStore";

interface MemoryRole {
  id: number;
  name: string;
}

const MemoryRoleSelector: React.FC = () => {
  const currentRole = useMemoryStore((state) => state.role);
  const setRole = useMemoryStore((state) => state.setRole);

  const roles = useMemo<MemoryRole[]>(
    () => [
      { id: 1, name: "LLM Engineer" },
      { id: 2, name: "Vessel Engineer" },
      { id: 3, name: "ML Engineer" },
      { id: 4, name: "Data Scientist" },
      { id: 5, name: "Frontend Developer" },
      { id: 6, name: "Python Developer" },
      { id: 7, name: "Esoteric Knowledge" },
    ],
    []
  );

  // ✅ Auto-set default role if none selected
  useEffect(() => {
    if (!currentRole) {
      console.log("🧠 No role selected — setting default role");
      setRole(roles[0]);
    }
  }, [currentRole, setRole, roles]);

  const handleSelect = useCallback(
    (role: MemoryRole) => {
      console.log("🟪 Role selected:", role);
      setRole(role);
    },
    [setRole]
  );

  return (
    <div className="flex flex-wrap gap-2 bg-white border border-gray-200 p-3 rounded-xl shadow-sm">
      {roles.map((role) => (
        <button
          key={role.id}
          onClick={() => handleSelect(role)}
          className={`px-3 py-1.5 rounded-full text-sm font-medium border transition whitespace-nowrap
            ${
              currentRole?.id === role.id
                ? "bg-purple-600 text-white border-purple-600 ring-2 ring-purple-300"
                : "bg-white text-gray-700 border-gray-300 hover:bg-purple-50"
            }`}
        >
          {role.name}
        </button>
      ))}
    </div>
  );
};

export default MemoryRoleSelector;
