// File: src/features/aiConversation/AssistantSelector.tsx
import React, { useEffect, useCallback, useMemo } from "react";
import { useRoleStore } from "../../store/roleStore";
import { useMemoryStore } from "../../store/memoryStore";
import { toast } from "../../store/toastStore";
import { useChatStore } from "../../store/chatStore";
import { useProjectStore } from "../../store/projectStore";

const AssistantSelector: React.FC = () => {
  // ✅ Proper Zustand subscription - component re-renders when store changes
  const rolesFromStore = useRoleStore((state) => state.roles);
  const fetchRoles = useRoleStore((state) => state.fetchRoles);

  // ✅ Memoize roles to prevent unnecessary callback recreations
  const roles = useMemo(() => rolesFromStore, [rolesFromStore]);

  const currentRole = useMemoryStore((state) => state.role);
  const setRole = useMemoryStore((state) => state.setRole);

  const loadOrInitSessionForRoleProject =
    useChatStore.use.loadOrInitSessionForRoleProject();
  const projectId = useProjectStore((state) => state.projectId);

  // Fetch roles on mount
  useEffect(() => {
    if (roles.length === 0) {
      void fetchRoles();
    }
  }, [roles.length, fetchRoles]);

  // Listen for updates from Settings
  useEffect(() => {
    const handleAssistantsUpdated = async () => {
      console.log("📥 AssistantSelector: Event received, refreshing...");
      await fetchRoles();
      console.log("✅ AssistantSelector: Refresh complete");
    };

    window.addEventListener("assistantsUpdated", handleAssistantsUpdated);

    return () => {
      window.removeEventListener("assistantsUpdated", handleAssistantsUpdated);
    };
  }, [fetchRoles]);

  const handleChange = useCallback(
    async (e: React.ChangeEvent<HTMLSelectElement>) => {
      const newRoleId = parseInt(e.target.value, 10);
      if (Number.isNaN(newRoleId) || !projectId) return;

      const selectedRole = roles.find((r) => r.id === newRoleId);
      if (!selectedRole) return;

      // Don't do anything if already selected
      if (currentRole?.id === newRoleId) return;

      try {
        // Update the role in memoryStore (convert null to undefined for type compatibility)
        setRole({
          id: selectedRole.id,
          name: selectedRole.name,
          description: selectedRole.description ?? undefined,
        });

        // Initialize a new session for the new role + current project
        await loadOrInitSessionForRoleProject(newRoleId, projectId);

        toast.success(`Switched to ${selectedRole.name}`);
      } catch (error) {
        console.error("Failed to switch assistant:", error);
        toast.error("Failed to switch assistant");
      }
    },
    [roles, currentRole, projectId, setRole, loadOrInitSessionForRoleProject]
  );

  return (
    <div className="flex flex-col gap-2">
      <select
        id="assistant-select"
        value={currentRole?.id ?? ""}
        onChange={handleChange}
        className="w-full px-3 py-2 rounded border border-border text-sm bg-surface text-text-primary focus:border-primary focus:outline-none transition-colors"
        disabled={roles.length === 0}
      >
        {roles.length === 0 && <option value="">No assistants</option>}
        {roles.map((role) => (
          <option key={role.id} value={role.id}>
            {role.name}
          </option>
        ))}
      </select>
    </div>
  );
};

export default AssistantSelector;
