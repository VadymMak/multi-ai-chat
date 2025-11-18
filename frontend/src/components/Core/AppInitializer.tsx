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
import api from "../../services/api";

import {
  rehydrateLastSessionFromStorage,
  queueSessionSync,
} from "../../controllers/sessionController";

const AppInitializer = () => {
  const setLoading = useAppStore((s) => s.setLoading);

  const setProjectId = useProjectStore((s) => s.setProjectId);
  const setRole = useMemoryStore((s) => s.setRole);
  const setChatSessionId = useChatStore((s) => s.setChatSessionId);
  const setConsumeManualSessionSync = useChatStore(
    (s) => s.setConsumeManualSessionSync
  );

  const initRoles = useRoleStore((s) => s.initRoles);

  const navigate = useNavigate();
  const startedRef = useRef(false);
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

  // --- memoized helpers to avoid redundant store updates ---
  const safeSetRole = useCallback(
    (next: MemoryRole | null | undefined) => {
      if (!next) return;
      const curr = useMemoryStore.getState().role;
      if (curr?.id !== next.id || curr?.name !== next.name) {
        setRole(next);
      }
    },
    [setRole]
  );

  const safeSetProjectId = useCallback(
    (next: number) => {
      const curr = useProjectStore.getState().projectId;
      if (curr !== next) setProjectId(next);
    },
    [setProjectId]
  );

  const safeSetChatSessionId = useCallback(
    (next: string) => {
      const curr = useChatStore.getState().chatSessionId ?? "";
      if ((curr || "") !== (next || "")) setChatSessionId(next || "");
    },
    [setChatSessionId]
  );

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    let cancelled = false;

    const done = () => {
      if (!cancelled) {
        setLoading(false);
        // Safety: if something bailed early without queueing, clear the flag.
        setConsumeManualSessionSync(false);
      }
    };

    (async () => {
      setLoading(true);
      // 🚫 Block HeaderControls (or other places) from kicking their own sync during boot
      setConsumeManualSessionSync(true);

      try {
        // 0) Initialize backend (create default roles/projects if needed)
        try {
          const res = await api.get("/init");
          if (process.env.NODE_ENV !== "production") {
            console.debug("✅ App initialized:", res.data);
          }
        } catch (err) {
          console.error("❌ Init failed:", err);
        }

        // 1) Make sure roles are loading (safe to call repeatedly)
        await Promise.resolve(initRoles?.());

        // 2) Try ultra-fast local rehydrate (this may enqueue its own sync)
        await rehydrateLastSessionFromStorage();

        const marker = useChatStore.getState().lastSessionMarker;
        if (marker?.projectId && marker?.roleId) {
          // Use a fresh roles snapshot (not the one captured at render)
          const rolesNow = useRoleStore.getState().roles;
          const matchedRole = rolesNow.find((r) => r.id === marker.roleId);
          if (matchedRole) {
            const memoryRole: MemoryRole = {
              id: matchedRole.id,
              name: matchedRole.name,
            };
            // ✅ keep role → project → session ordering
            safeSetRole(memoryRole);
          }

          safeSetProjectId(Number(marker.projectId));
          safeSetChatSessionId(marker.chatSessionId || "");

          // 👉 Kick a background sync specifically for this marker and
          // release the manual-sync flag when it completes.
          queueSessionSync(marker.roleId, marker.projectId)
            .catch(() => {})
            .finally(() => setConsumeManualSessionSync(false));

          navigateOnce("/chat");
          setLoading(false);
          return; // all good
        }
      } catch {
        // fall through to backend fallback
      }

      // 3) Backend fallback: last session (don’t block on sync)
      try {
        const data = await getLastSession();
        if (
          data?.project_id &&
          data?.role_id !== undefined &&
          (data?.chat_session_id || data?.chat_session_id === "")
        ) {
          const rolesNow = useRoleStore.getState().roles;
          const matchedRole = rolesNow.find((r) => r.id === data.role_id);

          if (matchedRole) {
            // ✅ keep role → project → session ordering
            safeSetRole({ id: matchedRole.id, name: matchedRole.name });
          }
          safeSetProjectId(Number(data.project_id));
          safeSetChatSessionId(data.chat_session_id || "");

          // 👉 Fire-and-forget & clear the manual flag when done
          queueSessionSync(Number(data.role_id), Number(data.project_id))
            .catch(() => {})
            .finally(() => setConsumeManualSessionSync(false));

          navigateOnce("/chat");
        }
      } finally {
        done();
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    setLoading,
    initRoles,
    setConsumeManualSessionSync,
    navigateOnce,
    safeSetRole,
    safeSetProjectId,
    safeSetChatSessionId,
  ]);

  return null;
};

export default AppInitializer;
