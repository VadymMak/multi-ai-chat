// File: src/App.tsx
import React, { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Landing from "./pages/Landing";
import ChatPage from "./pages/ChatPage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import ProtectedRoute from "./components/Auth/ProtectedRoute";
import { useAppStore } from "./store/appStore";
import AppInitializer from "./components/Core/AppInitializer";
import LoadingOverlay from "./components/Shared/LoadingOverlay";
import { useSettingsStore } from "./store/settingsStore";
import ToastContainer from "./components/Shared/ToastContainer";
import { NetworkStatus } from "./components/NetworkStatus";
// ✅ ДОБАВИТЬ: Import auth и role stores
import { useAuthStore } from "./store/authStore";
import { useRoleStore } from "./store/roleStore";

const App: React.FC = () => {
  const isLoading = useAppStore((s) => s.isLoading);

  // ✅ ДОБАВИТЬ: Auth state
  const { isAuthenticated, user } = useAuthStore();

  // ✅ ДОБАВИТЬ: Role store
  const { roles, fetchRoles } = useRoleStore();

  // Theme system
  const theme = useSettingsStore((s) => s.theme);
  const fontSize = useSettingsStore((s) => s.fontSize);

  // ✅ ДОБАВИТЬ: Автоматическая загрузка данных при login
  useEffect(() => {
    if (isAuthenticated && user) {
      console.log(
        "🔄 [App] User authenticated:",
        user.username,
        "id:",
        user.id
      );

      // Загрузить roles если пусто
      if (!roles || roles.length === 0) {
        console.log("📥 [App] Fetching roles...");
        fetchRoles();
      } else {
        console.log("✅ [App] Roles already loaded:", roles.length);
      }
    } else {
      console.log("⏸️ [App] User not authenticated, skipping data load");
    }
  }, [isAuthenticated, user?.id]); // ← Зависимость от user.id

  // Apply theme
  useEffect(() => {
    const root = document.documentElement;

    console.log("🎨 Theme changed to:", theme);
    console.log("🎨 Root classes before:", root.className);

    if (theme === "light") {
      root.classList.remove("dark");
      root.classList.add("light");
    } else if (theme === "dark") {
      root.classList.add("dark");
      root.classList.remove("light");
    } else if (theme === "auto") {
      // Detect system preference
      const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      if (isDark) {
        root.classList.add("dark");
        root.classList.remove("light");
      } else {
        root.classList.remove("dark");
        root.classList.add("light");
      }

      // Listen for system theme changes
      const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
      const handleChange = (e: MediaQueryListEvent) => {
        if (e.matches) {
          root.classList.add("dark");
          root.classList.remove("light");
        } else {
          root.classList.remove("dark");
          root.classList.add("light");
        }
      };

      mediaQuery.addEventListener("change", handleChange);
      return () => mediaQuery.removeEventListener("change", handleChange);
    }

    console.log("🎨 Root classes after:", root.className);
  }, [theme]);

  // Apply font size to root
  useEffect(() => {
    document.documentElement.style.fontSize = `${fontSize}px`;
  }, [fontSize]);

  return (
    <BrowserRouter>
      <NetworkStatus />
      <AppInitializer />

      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/chat"
          element={
            <ProtectedRoute>
              <ChatPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="*"
          element={
            <div className="p-10 text-center text-error text-xl">
              404 - Page Not Found
            </div>
          }
        />
      </Routes>
      <ToastContainer />
    </BrowserRouter>
  );
};

export default App;
