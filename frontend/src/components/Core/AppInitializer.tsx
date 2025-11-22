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
import { useAuthStore } from "@/store/authStore";
import { sessionManager } from "../../services/SessionManager";

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

  // Session restoration - delegated to SessionManager
  useEffect(() => {
    const checkAndRestore = async () => {
      // Wait for auth store to hydrate from localStorage
      let attempts = 0;
      const maxAttempts = 20; // 1 second max wait

      while (attempts < maxAttempts) {
        const { isAuthenticated, user } = useAuthStore.getState();

        // Check if hydration is complete (either authenticated with user, or not authenticated)
        const isHydrated = isAuthenticated ? !!user : true;

        if (isHydrated) {
          console.log("✅ [AppInitializer] Auth store hydrated");

          if (isAuthenticated) {
            console.log("🔄 [AppInitializer] Delegating to SessionManager...");
            await sessionManager.restoreSessionOnPageLoad();
            navigateOnce("/chat");
          } else {
            console.log(
              "⏸️ [AppInitializer] Not authenticated, redirecting to login"
            );
            navigateOnce("/login");
          }
          return;
        }

        console.log(
          `⏳ [AppInitializer] Waiting for auth hydration... (${
            attempts + 1
          }/${maxAttempts})`
        );
        await new Promise((resolve) => setTimeout(resolve, 50));
        attempts++;
      }

      console.warn(
        "⚠️ [AppInitializer] Auth hydration timeout, proceeding anyway"
      );
    };

    checkAndRestore();
  }, [navigateOnce]);

  return null;
};

export default AppInitializer;
