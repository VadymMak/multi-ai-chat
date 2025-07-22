// File: src/index.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/tailwind.css"; // or your global styles

// ✅ Remove preloader before rendering React
const preloader = document.getElementById("preloader");
if (preloader) {
  preloader.remove();
}

const root = ReactDOM.createRoot(document.getElementById("root")!);
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
