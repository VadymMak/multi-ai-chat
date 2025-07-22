// File: src/components/Core/AppInitializer.tsx

import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { getLastSession } from "../../services/aiApi";
import { useChatStore } from "../../store/chatStore";
import { useProjectStore } from "../../store/projectStore";
import { useMemoryStore } from "../../store/memoryStore";
import { useAppStore } from "../../store/appStore";

const AppInitializer = () => {
  const setLoading = useAppStore((s) => s.setLoading);
  const setProjectId = useProjectStore((s) => s.setProjectId);
  const setRole = useMemoryStore((s) => s.setRole);
  const setChatSessionId = useChatStore((s) => s.setChatSessionId);
  const navigate = useNavigate();

  const hasFetchedRef = useRef(false);

  useEffect(() => {
    setLoading(true);

    // ✅ Read from chat-storage (Zustand-persisted)
    const raw = localStorage.getItem("chat-storage");
    let restored = null;

    try {
      if (raw) {
        const parsed = JSON.parse(raw);
        restored = parsed?.state?.lastSessionMarker || null;
      }
    } catch (err) {
      console.warn("⚠️ Failed to parse local chat-storage:", err);
    }

    if (restored?.projectId && restored?.roleId && restored?.chatSessionId) {
      console.log("✅ Restoring session from localStorage:", restored);
      setProjectId(restored.projectId);
      setRole({ id: restored.roleId, name: "Unknown" }); // optionally fetch role name
      setChatSessionId(restored.chatSessionId);
      setLoading(false);
      return;
    }

    // Prevent re-fetching
    if (hasFetchedRef.current) return;
    hasFetchedRef.current = true;

    const loadFromBackend = async () => {
      try {
        const data = await getLastSession();
        if (data?.project_id && data?.role_id && data?.chat_session_id) {
          setProjectId(data.project_id);
          setRole({ id: data.role_id, name: data.role_name ?? "Unknown" });
          setChatSessionId(data.chat_session_id);

          // ✅ Save to localStorage for next reload
          const sessionMarker = {
            state: {
              lastSessionMarker: {
                projectId: data.project_id,
                roleId: data.role_id,
                chatSessionId: data.chat_session_id,
              },
            },
            version: 0,
          };
          localStorage.setItem("chat-storage", JSON.stringify(sessionMarker));

          console.log("🌐 Restored session from backend:", sessionMarker);
          navigate("/chat");
        }
      } catch (err) {
        console.warn("⚠️ No last session found or backend unavailable.");
      } finally {
        setLoading(false);
      }
    };

    loadFromBackend();
  }, [navigate, setLoading, setProjectId, setRole, setChatSessionId]);

  return null;
};

export default AppInitializer;
