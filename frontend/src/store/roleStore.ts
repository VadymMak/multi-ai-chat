// File: src/store/roleStore.ts
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import api from "../services/api";

export interface Role {
  id: number;
  name: string;
  description?: string | null;
}

interface RoleState {
  roles: Role[];
  isLoading: boolean;
  fetchRoles: () => Promise<void>;
  initRoles: () => void;
  clearRoles: () => void;
  addRole: (name: string, description: string) => Promise<void>;
  updateRole: (
    id: number,
    data: { name: string; description: string }
  ) => Promise<void>;
  deleteRole: (id: number) => Promise<void>;
}

export const useRoleStore = create<RoleState>()(
  persist(
    (set, get) => ({
      roles: [],
      isLoading: false,

      fetchRoles: async () => {
        const { roles, isLoading } = get();

        // Skip if already loading or roles are already fetched
        if (isLoading || roles.length > 0) {
          console.log(
            "⏭️ [roleStore] Skipping fetch (loading or already loaded)"
          );
          return;
        }

        set({ isLoading: true });
        console.log("📥 [roleStore] Fetching roles...");

        try {
          const response = await api.get("/roles");
          const fetchedRoles: Role[] = response.data;

          set({
            roles: fetchedRoles,
            isLoading: false,
          });

          console.log("✅ [roleStore] Roles fetched:", fetchedRoles.length);
        } catch (error) {
          console.error("❌ [roleStore] Error fetching roles:", error);
          set({ isLoading: false });
          throw error;
        }
      },

      initRoles: () => {
        const { roles, fetchRoles } = get();

        if (roles.length === 0) {
          console.log("🔄 [roleStore] Initializing roles...");
          fetchRoles();
        } else {
          console.log(
            "✅ [roleStore] Roles already initialized:",
            roles.length
          );
        }
      },

      clearRoles: () => {
        console.log("🗑️ [roleStore] Clearing roles");
        set({ roles: [], isLoading: false });
      },

      addRole: async (name: string, description: string) => {
        try {
          console.log("➕ [roleStore] Adding role:", name);
          const response = await api.post("/roles", { name, description });
          const newRole: Role = response.data;

          set((state) => ({
            roles: [...state.roles, newRole],
          }));

          console.log("✅ [roleStore] Role added:", newRole.id);
        } catch (error) {
          console.error("❌ [roleStore] Error adding role:", error);
          throw error;
        }
      },

      updateRole: async (
        id: number,
        data: { name: string; description: string }
      ) => {
        try {
          console.log("✏️ [roleStore] Updating role:", id);
          const response = await api.put(`/roles/${id}`, data);
          const updatedRole: Role = response.data;

          set((state) => ({
            roles: state.roles.map((role) =>
              role.id === id ? updatedRole : role
            ),
          }));

          console.log("✅ [roleStore] Role updated:", id);
        } catch (error) {
          console.error("❌ [roleStore] Error updating role:", error);
          throw error;
        }
      },

      deleteRole: async (id: number) => {
        try {
          console.log("🗑️ [roleStore] Deleting role:", id);
          await api.delete(`/roles/${id}`);

          set((state) => ({
            roles: state.roles.filter((role) => role.id !== id),
          }));

          console.log("✅ [roleStore] Role deleted:", id);
        } catch (error) {
          console.error("❌ [roleStore] Error deleting role:", error);
          throw error;
        }
      },
    }),
    {
      name: "role-store",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        roles: state.roles,
      }),
    }
  )
);
