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
      className="flex flex-wrap gap-2 min-w-[280px] min-h-[48px] items-center"
      style={{ flexShrink: 0 }}
    >
      {isLoading || isWorking ? (
        <div className="flex-1 text-center text-text-secondary text-sm">
          ⏳ Loading roles…
        </div>
      ) : roles.length === 0 ? (
        <div className="flex-1 text-center text-text-secondary text-sm">
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
          const isMLEngineer = role.name === "ML Engineer";

          // Define button classes based on state
          let buttonClasses = "";
          if (isActive) {
            if (isMLEngineer) {
              buttonClasses = "bg-purple text-white shadow-md shadow-purple/20";
            } else {
              buttonClasses = "bg-primary text-white";
            }
          } else {
            buttonClasses =
              "bg-surface text-text-secondary border border-border hover:bg-surface/80 hover:text-text-primary";
          }

          return (
            <button
              key={role.id}
              onClick={() => handleSelect(memoryRole)}
              disabled={isWorking}
              className={`px-4 py-2 rounded text-sm font-medium transition-all duration-200 whitespace-nowrap ${buttonClasses}`}
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
