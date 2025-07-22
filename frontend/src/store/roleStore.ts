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
  addRole: (name: string, description?: string) => Promise<void>;
  updateRole: (
    id: number,
    data: { name?: string; description?: string }
  ) => Promise<void>;
  deleteRole: (id: number) => Promise<void>;
}

export const useRoleStore = create<RoleState>()(
  persist(
    (set, get) => ({
      roles: [],
      isLoading: false,

      fetchRoles: async () => {
        if (get().isLoading) {
          console.debug("⏳ fetchRoles already in progress, skipping...");
          return;
        }

        set({ isLoading: true });

        try {
          const res = await api.get("/roles");
          const roles = Array.isArray(res.data) ? res.data : [];

          if (!roles.length) {
            console.warn("⚠️ No roles returned from API.");
          }

          set({ roles });
        } catch (err) {
          console.error("❌ Failed to fetch roles:", err);
          set({ roles: [] });
        } finally {
          set({ isLoading: false });
        }
      },

      initRoles: () => {
        const { roles, fetchRoles } = get();
        if (!Array.isArray(roles) || roles.length === 0) {
          console.debug("📥 Initializing role list from backend...");
          fetchRoles();
        } else {
          console.debug("✅ Roles already initialized");
          set({ isLoading: false });
        }
      },

      addRole: async (name: string, description: string = "") => {
        if (!name || typeof name !== "string" || !name.trim()) {
          console.warn("⚠️ Invalid role name provided");
          return;
        }

        try {
          const res = await api.post("/roles", {
            name: name.trim(),
            description: description.trim(),
          });
          const newRole = res?.data;
          if (newRole && typeof newRole.id === "number") {
            set({ roles: [...get().roles, newRole] });
          }
        } catch (err) {
          console.error("❌ Failed to add role:", err);
        }
      },

      updateRole: async (
        id: number,
        data: { name?: string; description?: string }
      ) => {
        if (
          (!data.name || !data.name.trim()) &&
          data.description === undefined
        ) {
          console.warn("⚠️ No valid data provided for role update");
          return;
        }

        try {
          const payload: { name?: string; description?: string } = {};
          if (data.name !== undefined) {
            payload.name = data.name.trim();
          }
          if (data.description !== undefined) {
            payload.description = data.description.trim();
          }

          const res = await api.put(`/roles/${id}`, payload);
          const updated = res?.data;
          if (updated && typeof updated.id === "number") {
            set({
              roles: get().roles.map((role) =>
                role.id === id ? updated : role
              ),
            });
          }
        } catch (err) {
          console.error("❌ Failed to update role:", err);
        }
      },

      deleteRole: async (id: number) => {
        if (typeof id !== "number") return;

        try {
          await api.delete(`/roles/${id}`);
          set({
            roles: get().roles.filter((role) => role.id !== id),
          });
        } catch (err) {
          console.error("❌ Failed to delete role:", err);
        }
      },
    }),
    {
      name: "role-store",
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        roles: state.roles,
      }),
    }
  )
);
