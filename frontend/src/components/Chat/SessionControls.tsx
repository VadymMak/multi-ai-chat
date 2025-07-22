// File: src/components/Chat/SessionControls.tsx
import React, { useCallback, useMemo } from "react";
import { v4 as uuidv4 } from "uuid";
import { useChatStore } from "../../store/chatStore";
import { useProjectStore } from "../../store/projectStore";
import { useMemoryStore } from "../../store/memoryStore";
import { syncAndInitSession } from "../../controllers/sessionController";

const SessionControls: React.FC = () => {
  const chatSessionId = useChatStore((s) => s.chatSessionId);
  const setChatSessionId = useChatStore((s) => s.setChatSessionId);
  const setMessages = useChatStore((s) => s.setMessages);
  const setLastSessionMarker = useChatStore((s) => s.setLastSessionMarker);

  const role = useMemoryStore((s) => s.role);
  const hasHydrated = useMemoryStore((s) => s.hasHydrated);
  const projectId = useProjectStore((s) => s.projectId);

  const sessionReady = useMemo(() => {
    return (
      hasHydrated &&
      typeof role?.id === "number" &&
      typeof projectId === "number"
    );
  }, [hasHydrated, role, projectId]);

  const handleNewSession = useCallback(async () => {
    if (!sessionReady || !role?.id || !projectId) {
      console.warn(
        "🚫 Cannot start session: missing role, hydration, or project."
      );
      return;
    }

    const newSessionId = uuidv4();
    console.log("🆕 Creating new session ID:", newSessionId);

    setChatSessionId(newSessionId);
    setMessages([]);

    // Update local session marker
    setLastSessionMarker({
      roleId: role.id,
      projectId,
      chatSessionId: newSessionId,
    });

    try {
      // ✅ Only pass roleId and projectId as required
      await syncAndInitSession(role.id, projectId);
    } catch (err) {
      console.error("❌ Failed to sync/init new session:", err);
    }
  }, [
    sessionReady,
    role,
    projectId,
    setChatSessionId,
    setMessages,
    setLastSessionMarker,
  ]);

  return (
    <div className="text-xs text-gray-600 border-t pt-3 mt-4">
      <div className="mb-2">
        <div className="font-semibold text-sm mb-1">🧩 Session Controls</div>
        <div className="break-all text-gray-500">
          <span className="font-medium">Current:</span>{" "}
          {chatSessionId || "None"}
        </div>
      </div>
      <button
        className="mt-2 w-full text-left px-3 py-1 bg-white text-blue-600 border border-blue-200 rounded hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed"
        onClick={handleNewSession}
        disabled={!sessionReady}
        title={
          !sessionReady
            ? "Role or project not ready yet"
            : "Start a new session"
        }
      >
        ➕ Start New Session
      </button>
    </div>
  );
};

export default SessionControls;
