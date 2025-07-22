// File: src/components/MemoryRoleSelector.tsx

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useMemoryStore } from "../../store/memoryStore";
import { useRoleStore } from "../../store/roleStore";
import type { MemoryRole } from "../../types/memory";
import { runSessionFlow } from "../../controllers/runSessionFlow";

const MemoryRoleSelector: React.FC = () => {
  const currentRole = useMemoryStore((state) => state.role);
  const setRole = useMemoryStore((state) => state.setRole);
  const { roles, fetchRoles, isLoading } = useRoleStore();

  const selectVersion = useRef(0);
  const [isWorking, setIsWorking] = useState(false);

  // 📥 Load roles on mount if empty
  useEffect(() => {
    if (roles.length === 0 && !isLoading) {
      fetchRoles();
    }
  }, [roles.length, isLoading, fetchRoles]);

  // 🎯 Handle role selection
  const handleSelect = useCallback(
    async (role: MemoryRole) => {
      if (!role || role.id === currentRole?.id) return;

      const version = ++selectVersion.current;
      setIsWorking(true);

      try {
        console.debug("🎯 Selecting role:", role);
        setRole(role); // ✅ Automatically clears stale projectId inside

        await runSessionFlow(role.id, undefined, "MemoryRoleSelector");

        if (version !== selectVersion.current) {
          console.debug("⏹️ Cancelled — stale version");
          return;
        }
      } catch (err) {
        console.error("❌ [MemoryRoleSelector] Session init failed:", err);
      } finally {
        if (version === selectVersion.current) setIsWorking(false);
      }
    },
    [currentRole?.id, setRole]
  );

  return (
    <div
      className="flex flex-wrap gap-2 bg-white border border-gray-200 p-3 rounded-xl shadow-sm min-w-[280px] min-h-[48px] items-center"
      style={{ flexShrink: 0 }}
    >
      {isLoading || isWorking ? (
        <div className="flex-1 text-center text-gray-500 text-sm">
          ⏳ Loading roles…
        </div>
      ) : roles.length === 0 ? (
        <div className="flex-1 text-center text-gray-500 text-sm">
          ❌ No roles available
        </div>
      ) : (
        roles.map((role) => {
          const memoryRole: MemoryRole = {
            id: role.id,
            name: role.name,
            description: role.description ?? undefined,
          };

          const isActive = currentRole?.id === role.id;

          return (
            <button
              key={role.id}
              onClick={() => handleSelect(memoryRole)}
              disabled={isWorking}
              className={`px-3 py-1.5 rounded-full text-sm font-medium border transition whitespace-nowrap
                ${
                  isActive
                    ? "bg-purple-600 text-white border-purple-600 ring-2 ring-purple-300"
                    : "bg-white text-gray-700 border-gray-300 hover:bg-purple-50"
                }`}
            >
              {role.name}
            </button>
          );
        })
      )}
    </div>
  );
};

export default MemoryRoleSelector;
