// File: src/App.tsx
import React, { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Landing from "./pages/Landing";
import ChatPage from "./pages/ChatPage";
import { useAppStore } from "./store/appStore";
import AppInitializer from "./components/Core/AppInitializer";
import LoadingOverlay from "./components/Shared/LoadingOverlay";
import { useSettingsStore } from "./store/settingsStore";
import ToastContainer from "./components/Shared/ToastContainer";

const App: React.FC = () => {
  const isLoading = useAppStore((s) => s.isLoading);

  // Theme system
  const theme = useSettingsStore((s) => s.theme);
  const fontSize = useSettingsStore((s) => s.fontSize);

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
      <AppInitializer />

      {isLoading && <LoadingOverlay />}

      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/chat" element={<ChatPage />} />
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
