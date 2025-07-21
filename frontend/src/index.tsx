// File: src/index.tsx

import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import "./styles/tailwind.css";

import Landing from "./pages/Landing";
import AiChat from "./features/aiConversation/AiChat";

const root = ReactDOM.createRoot(document.getElementById("root")!);

root.render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/chat" element={<AiChat />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
