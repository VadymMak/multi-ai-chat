// File: src/components/Chat/HeaderControls.tsx
import React, { lazy, Suspense, useEffect, useRef, useMemo } from "react";
import { useMemoryStore } from "../../store/memoryStore";
import { useRoleStore } from "../../store/roleStore";
import { useProjectStore } from "../../store/projectStore";
import { useChatStore } from "../../store/chatStore";
import { runSessionFlow } from "../../controllers/runSessionFlow";

const AiSelector = lazy(
  () => import("../../features/aiConversation/AiSelector")
);
const MemoryRoleSelector = lazy(
  () => import("../../features/aiConversation/MemoryRoleSelector")
);
const ProjectSelector = lazy(
  () => import("../../features/aiConversation/ProjectSelector")
);

const DEBUG = process.env.NODE_ENV !== "production";

const HeaderControls: React.FC = () => {
  const roleId = useMemoryStore((s) =>
    typeof s.role?.id === "number" ? s.role.id : null
  );
  const projectId = useProjectStore((s) => s.projectId);
  const { isLoading: rolesLoading, initRoles } = useRoleStore();

  // NOTE: Some versions expose this as a boolean; others as () => boolean
  const rawManualSync = useChatStore(
    (s) => (s as any).consumeManualSessionSync
  ) as boolean | (() => boolean) | undefined;

  const sessionReady = useChatStore((s) => s.sessionReady);

  const lastKeyRef = useRef<string | null>(null);
  const inFlightRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    initRoles();
  }, [initRoles]);

  const key = useMemo(() => {
    if (!roleId || !projectId) return null;
    return `${roleId}-${projectId}`;
  }, [roleId, projectId]);

  useEffect(() => {
    if (!roleId || !projectId) {
      lastKeyRef.current = null;
      inFlightRef.current.clear();
    }
  }, [roleId, projectId]);

  useEffect(() => {
    if (!roleId || !projectId || !key) {
      DEBUG && console.debug("[HeaderControls] ⛔ Missing role or project");
      return;
    }
    if (!sessionReady) {
      DEBUG &&
        console.debug("[HeaderControls] ⏳ Waiting for session readiness");
      return;
    }

    // Handle both boolean and function forms
    const manualSkip =
      typeof rawManualSync === "function"
        ? rawManualSync()
        : Boolean(rawManualSync);

    if (manualSkip) {
      DEBUG &&
        console.debug(
          "[HeaderControls] 🛑 Manual session sync consumed/flagged — skipping this tick"
        );
      return;
    }

    if (lastKeyRef.current === key) {
      DEBUG &&
        console.debug("[HeaderControls] ⏭️ Already synced for key:", key);
      return;
    }
    if (inFlightRef.current.has(key)) {
      DEBUG &&
        console.debug("[HeaderControls] ⏳ Sync already in-flight for", key);
      return;
    }

    DEBUG &&
      console.debug("[runSessionFlow][HeaderControls] 🔄 Kickoff →", {
        roleId,
        projectId,
      });
    inFlightRef.current.add(key);

    runSessionFlow(roleId, projectId, "HeaderControls")
      .then(() => {
        lastKeyRef.current = key;
        DEBUG && console.debug("[runSessionFlow][HeaderControls] ✅ Synced");
      })
      .catch((e) =>
        console.warn("[HeaderControls] ⚠️ runSessionFlow error:", e)
      )
      .finally(() => {
        inFlightRef.current.delete(key);
      });
  }, [roleId, projectId, key, sessionReady, rawManualSync]);

  return (
    <div className="sticky top-0 z-10 bg-white border-b shadow-sm w-full">
      <div className="w-full max-w-[1200px] mx-auto">
        {/* AI Selector */}
        <div className="flex flex-row flex-wrap items-center gap-2 px-3 py-2">
          <Suspense
            fallback={
              <div className="text-sm text-gray-400">Loading AI Selector…</div>
            }
          >
            <AiSelector />
          </Suspense>
        </div>

        {/* Role + Project Selection */}
        <div className="flex flex-row flex-wrap items-center gap-3 px-3 py-2">
          {rolesLoading ? (
            <div className="text-sm text-gray-400">Loading roles…</div>
          ) : (
            <Suspense
              fallback={
                <div className="text-sm text-gray-400">
                  Loading Memory Roles…
                </div>
              }
            >
              <MemoryRoleSelector />
            </Suspense>
          )}
          <Suspense
            fallback={
              <div className="text-sm text-gray-400">Loading Projects…</div>
            }
          >
            <ProjectSelector />
          </Suspense>
        </div>
      </div>
    </div>
  );
};

export default React.memo(HeaderControls);
