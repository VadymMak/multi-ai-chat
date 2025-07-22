// File: src/components/Core/AppInitializer.tsx
import { useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { getLastSession } from "../../services/aiApi";
import { useChatStore } from "../../store/chatStore";
import { useProjectStore } from "../../store/projectStore";
import { useMemoryStore } from "../../store/memoryStore";
import { useRoleStore } from "../../store/roleStore";
import { useAppStore } from "../../store/appStore";
import type { MemoryRole } from "../../types/memory";

const AppInitializer = () => {
  const setLoading = useAppStore((s) => s.setLoading);
  const setProjectId = useProjectStore((s) => s.setProjectId);
  const setRole = useMemoryStore((s) => s.setRole);
  const setChatSessionId = useChatStore((s) => s.setChatSessionId);

  const roles = useRoleStore((s) => s.roles);
  const initRoles = useRoleStore((s) => s.initRoles);

  const navigate = useNavigate();
  const hasFetchedRef = useRef(false);
  const hasNavigatedRef = useRef(false);

  const navigateOnce = useCallback(
    (path: string) => {
      if (!hasNavigatedRef.current) {
        hasNavigatedRef.current = true;
        navigate(path);
      }
    },
    [navigate]
  );

  useEffect(() => {
    setLoading(true);
    initRoles();

    // 1️⃣ Try localStorage
    try {
      const raw = localStorage.getItem("chat-storage");
      if (raw) {
        const parsed = JSON.parse(raw);
        const lastSession = parsed?.state?.lastSessionMarker;
        if (
          lastSession?.projectId &&
          lastSession?.roleId &&
          lastSession?.chatSessionId
        ) {
          const matchedRole = roles.find((r) => r.id === lastSession.roleId);
          if (matchedRole) {
            setProjectId(lastSession.projectId);
            const memoryRole: MemoryRole = {
              id: matchedRole.id,
              name: matchedRole.name,
            };
            setRole(memoryRole);
            setChatSessionId(lastSession.chatSessionId);
            hasFetchedRef.current = true;
            setLoading(false);
            navigateOnce("/chat");
            return;
          }
        }
      }
    } catch {}

    if (hasFetchedRef.current) return;
    hasFetchedRef.current = true;

    // 2️⃣ Backend fallback
    const loadFromBackend = async () => {
      try {
        const data = await getLastSession();

        if (data?.project_id && data?.role_id && data?.chat_session_id) {
          const matchedRole = roles.find((r) => r.id === data.role_id);
          if (!matchedRole) return;

          const restoredSession = {
            projectId: data.project_id,
            roleId: data.role_id,
            chatSessionId: data.chat_session_id,
          };

          setProjectId(restoredSession.projectId);
          const memoryRole: MemoryRole = {
            id: matchedRole.id,
            name: matchedRole.name,
          };
          setRole(memoryRole);
          setChatSessionId(restoredSession.chatSessionId);

          localStorage.setItem(
            "chat-storage",
            JSON.stringify({
              state: {
                lastSessionMarker: {
                  projectId: restoredSession.projectId,
                  roleId: restoredSession.roleId,
                  chatSessionId: restoredSession.chatSessionId,
                  roleName: matchedRole.name,
                },
              },
              version: 0,
            })
          );

          navigateOnce("/chat");
        }
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    };

    loadFromBackend();
  }, [
    setLoading,
    setProjectId,
    setRole,
    setChatSessionId,
    roles,
    initRoles,
    navigateOnce,
  ]);

  return null;
};

export default AppInitializer;
