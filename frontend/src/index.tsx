import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/tailwind.css";
import { useChatStore } from "./store/chatStore";
import { useMemoryStore } from "./store/memoryStore";
import { useProjectStore } from "./store/projectStore";
import { getChatHistory } from "./services/aiApi";
import { runSessionFlow } from "./controllers/runSessionFlow"; // ✅ fixed import

// ✅ Helper: fade out and remove preloader
const fadeOutPreloader = () => {
  const preloader = document.getElementById("preloader");
  if (preloader) {
    preloader.classList.add("fade-out");
    setTimeout(() => {
      preloader.remove();
    }, 500); // matches CSS transition
  }
};

// ✅ Helper: load chat history safely with timeout
const safeGetHistory = async (
  projectId: number,
  roleId: number,
  sessionId: string
) => {
  type HistoryType = Awaited<ReturnType<typeof getChatHistory>>;
  try {
    return await Promise.race<HistoryType>([
      getChatHistory(String(projectId), String(roleId), sessionId),
      new Promise<HistoryType>((_, reject) =>
        setTimeout(() => reject(new Error("History load timeout")), 5000)
      ),
    ]);
  } catch (err) {
    console.error("⚠️ Failed to load chat history:", err);
    return null;
  }
};

(async () => {
  let restored = false;
  const isInitialLoad = process.env.NODE_ENV === "production";

  const chatStore = useChatStore.getState();
  const memoryStore = useMemoryStore.getState();
  const projectStore = useProjectStore.getState();

  // 0️⃣ Ensure fallback role/project if missing
  const { fallbackRole, fallbackProjectId } =
    memoryStore.ensureRoleAndProjectInitialized();

  const role = memoryStore.role;
  const projectId = projectStore.projectId;
  const roleId = role?.id || null;

  try {
    // 1️⃣ Try restoring from sessionStorage
    restored = await Promise.race<boolean>([
      chatStore.restoreSessionFromMarker(),
      new Promise<boolean>((_, reject) =>
        setTimeout(() => reject(new Error("Local restore timeout")), 3000)
      ),
    ]);

    // 2️⃣ If no restore and role/project are known, try backend restore
    if (!restored && roleId && projectId) {
      console.log("📭 No local marker — calling backend for last session...");

      try {
        const res = await Promise.race<Response>([
          fetch(
            `/chat/last-session-by-role?role_id=${roleId}&project_id=${projectId}`
          ),
          new Promise<Response>((_, reject) =>
            setTimeout(() => reject(new Error("Backend fetch timeout")), 5000)
          ),
        ]);

        if (res && res.ok) {
          const data = await res.json();
          if (data?.chat_session_id) {
            console.log("📥 Backend restored session:", data.chat_session_id);

            const history = await safeGetHistory(
              projectId,
              roleId,
              data.chat_session_id
            );

            chatStore.setChatSessionId(data.chat_session_id);
            chatStore.setMessages(history?.messages || []);
            chatStore.setLastSessionMarker({
              projectId,
              roleId,
              chatSessionId: data.chat_session_id,
            });

            restored = true;
          }
        }
      } catch (err) {
        console.error("⚠️ Backend restore failed:", err);
      }
    }

    // 3️⃣ Validate session marker matches role/project
    const marker = chatStore.lastSessionMarker;
    const markerMismatch =
      roleId &&
      projectId &&
      (!marker || marker.roleId !== roleId || marker.projectId !== projectId);

    if (markerMismatch) {
      console.log("♻️ Forcing sync with current role/project:", {
        roleId,
        projectId,
        lastSessionMarker: marker,
      });
      await chatStore.syncAndInitSession(roleId, projectId);
    }
  } catch (err) {
    console.error("❌ Startup restore error:", err);
  } finally {
    console.log(
      restored
        ? "♻️ Chat session restored successfully"
        : "⚠️ No chat session restored — fallback complete"
    );

    fadeOutPreloader();

    // ✅ If fallback was set (due to missing role/project), trigger runSessionFlow
    if (fallbackRole?.id && fallbackProjectId) {
      console.log("🧪 Running fallback session init:", {
        fallbackRole,
        fallbackProjectId,
      });
      runSessionFlow(fallbackRole.id, fallbackProjectId);
    }

    const root = ReactDOM.createRoot(document.getElementById("root")!);
    root.render(
      <React.StrictMode>
        <div className={isInitialLoad ? "app-fade-in" : ""}>
          <App />
        </div>
      </React.StrictMode>
    );
  }
})();
