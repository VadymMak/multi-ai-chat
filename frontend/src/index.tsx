import "promise-polyfill/src/finally";
import React from "react";
import ReactDOM from "react-dom/client";
import "./styles/tailwind.css";
import App from "./App";
import { bootstrapApp } from "./bootstrap/bootstrapApp";

const fadeOutPreloader = () => {
  const preloader = document.getElementById("preloader");
  if (!preloader) return;
  preloader.classList.add("fade-out");
  setTimeout(() => preloader.remove(), 500);
};

// Render immediately (no awaiting boot)
const root = ReactDOM.createRoot(document.getElementById("root")!);
const isInitialLoad = import.meta.env.MODE === "production";

root.render(
  <React.StrictMode>
    <div className={isInitialLoad ? "app-fade-in" : ""}>
      <App />
    </div>
  </React.StrictMode>
);

// Kick off bootstrap asynchronously and NEVER block UI
(async () => {
  try {
    await bootstrapApp({ nonBlocking: true, maxTotalMs: 1500 });
  } catch (e) {
    // Don’t care — UI must not be blocked
    console.warn("bootstrap skipped/failed (non-blocking):", e);
  } finally {
    requestAnimationFrame(fadeOutPreloader);
  }
})();
