// File: src/App.tsx
import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Landing from "./pages/Landing";
import ChatPage from "./pages/ChatPage";
import { useAppStore } from "./store/appStore";
import AppInitializer from "./components/Core/AppInitializer";
import LoadingOverlay from "./components/Shared/LoadingOverlay";

const App: React.FC = () => {
  const isLoading = useAppStore((s) => s.isLoading);

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
            <div className="p-10 text-center text-red-500 text-xl">
              404 - Page Not Found
            </div>
          }
        />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
