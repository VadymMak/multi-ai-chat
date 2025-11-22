// File: src/store/authStore.ts
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import api from "../services/api";
import { AxiosError } from "axios"; // ← ДОБАВИТЬ
import { sessionManager } from "../services/SessionManager";

interface User {
  id: number;
  username: string;
  email: string;
  status?: string;
  trial_ends_at?: string;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (
    email: string,
    username: string,
    password: string
  ) => Promise<void>;
  logout: () => void;
  clearAuth: () => void;
  setUser: (user: User, token: string) => void;
  checkAuth: () => Promise<void>;
}

const clearAllUserData = () => {
  const keysToKeep = [
    "auth-storage",
    "role-store",
    "project-store",
    "chat-storage",
    "theme",
    "language",
  ];

  const keysToRemove: string[] = [];

  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && !keysToKeep.includes(key)) {
      keysToRemove.push(key);
    }
  }

  keysToRemove.forEach((key) => {
    localStorage.removeItem(key);
    console.log(`🗑️ Removed: ${key}`);
  });

  sessionStorage.clear();
  console.log("🧹 User data cleared (stores preserved)");
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,
      isLoading: false,

      login: async (username: string, password: string) => {
        try {
          set({ isLoading: true });

          const formData = new URLSearchParams();
          formData.append("username", username);
          formData.append("password", password);

          const response = await api.post("/auth/login", formData, {
            headers: {
              "Content-Type": "application/x-www-form-urlencoded",
            },
          });

          const user = response.data.user;
          const token =
            response.data.access_token || response.data.token || null;

          const currentUser = get().user;
          if (currentUser && currentUser.id !== user.id) {
            console.log("⚠️ Different user detected, clearing old data");
            clearAllUserData();
          }

          set({
            user,
            token,
            isAuthenticated: true,
            isLoading: false,
          });

          console.log("✅ [authStore] Login successful:", user.username);
        } catch (err) {
          set({ isLoading: false });
          console.error("❌ [authStore] Login failed:", err);

          // ✅ ПРАВИЛЬНАЯ обработка AxiosError
          let errorMessage = "Login failed";
          if (err instanceof AxiosError) {
            errorMessage =
              err.response?.data?.detail || err.message || errorMessage;
          } else if (err instanceof Error) {
            errorMessage = err.message;
          }

          throw new Error(errorMessage);
        }
      },

      register: async (email: string, username: string, password: string) => {
        try {
          set({ isLoading: true });

          console.log("📤 [authStore] Sending register request:", {
            email,
            username,
            password: "***",
          });

          const response = await api.post("/auth/register", {
            email,
            username,
            password,
          });

          const user = response.data.user;
          const token =
            response.data.access_token || response.data.token || null;

          const currentUser = get().user;
          if (currentUser && currentUser.id !== user.id) {
            console.log("⚠️ Different user detected, clearing old data");
            clearAllUserData();
          }

          set({
            user,
            token,
            isAuthenticated: true,
            isLoading: false,
          });

          console.log("✅ [authStore] Registration successful:", user.username);
        } catch (err) {
          set({ isLoading: false });
          console.error("❌ [authStore] Registration failed:", err);

          // ✅ ПРАВИЛЬНАЯ обработка AxiosError
          let errorMessage = "Registration failed";
          if (err instanceof AxiosError) {
            errorMessage =
              err.response?.data?.detail || err.message || errorMessage;
          } else if (err instanceof Error) {
            errorMessage = err.message;
          }

          throw new Error(errorMessage);
        }
      },

      logout: () => {
        console.log("👋 [authStore] Delegating to SessionManager...");
        sessionManager.handleLogout();
      },

      clearAuth: () => {
        // Clear localStorage for auth-related data
        localStorage.removeItem("auth-storage");
        localStorage.removeItem("chat-storage");
        localStorage.removeItem("project-store");
        localStorage.removeItem("memory-role-store");
        sessionStorage.clear();

        // Clear state
        set({
          user: null,
          token: null,
          isAuthenticated: false,
        });

        console.log("✅ [authStore] Auth cleared");
      },

      setUser: (user: User, token: string) => {
        set({
          user,
          token,
          isAuthenticated: true,
        });
        console.log("✅ [authStore] User set:", user.username);
      },

      checkAuth: async () => {
        const { token } = get();

        if (!token) {
          set({ isAuthenticated: false });
          return;
        }

        try {
          const response = await api.get("/auth/me");
          const user = response.data;

          const currentUser = get().user;
          if (currentUser && currentUser.id !== user.id) {
            console.log("⚠️ User ID changed in checkAuth");
            clearAllUserData();
          }

          set({
            user,
            isAuthenticated: true,
          });

          console.log("✅ [authStore] Auth check successful:", user.username);
        } catch (err) {
          console.error("❌ [authStore] Auth check failed:", err);

          localStorage.clear();
          sessionStorage.clear();

          set({
            user: null,
            token: null,
            isAuthenticated: false,
          });
        }
      },
    }),
    {
      name: "auth-storage",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        user: state.user,
        token: state.token,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);
