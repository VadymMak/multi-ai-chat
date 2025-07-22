import React, { lazy, Suspense, useEffect, useRef, useMemo } from "react";
import { useMemoryStore } from "../../store/memoryStore";
import { useRoleStore } from "../../store/roleStore";
import { useProjectStore } from "../../store/projectStore";
import { useChatStore } from "../../store/chatStore";
import { runSessionFlow } from "../../controllers/runSessionFlow";

// Lazy-load dropdowns
const AiSelector = lazy(
  () => import("../../features/aiConversation/AiSelector")
);
const MemoryRoleSelector = lazy(
  () => import("../../features/aiConversation/MemoryRoleSelector")
);
const ProjectSelector = lazy(
  () => import("../../features/aiConversation/ProjectSelector")
);

const HeaderControls: React.FC = () => {
  const role = useMemoryStore((s) => s.role);
  const roleId = typeof role?.id === "number" ? role.id : null;

  const projectId = useProjectStore((s) => s.projectId);
  const { isLoading, initRoles } = useRoleStore();

  const consumeManualSessionSync = useChatStore(
    (s) => s.consumeManualSessionSync
  );
  const sessionReady = useChatStore((s) => s.sessionReady);

  // Track the last (role,project) we actually synced
  const lastKeyRef = useRef<string | null>(null);

  // Kick off roles fetch once
  useEffect(() => {
    initRoles();
  }, [initRoles]);

  const key = useMemo(
    () => (roleId && projectId ? `${roleId}-${projectId}` : null),
    [roleId, projectId]
  );

  useEffect(() => {
    if (!roleId || !projectId) {
      console.log("[HeaderControls] ⛔ Cannot run — missing role or project");
      return;
    }
    if (consumeManualSessionSync) {
      console.log(
        "[HeaderControls] 🛑 Skipped runSessionFlow due to manual sync flag"
      );
      return;
    }
    if (!sessionReady) {
      console.log(
        "[HeaderControls] ⏳ Waiting for session readiness before runSessionFlow"
      );
      return;
    }

    if (lastKeyRef.current === key) {
      console.log("[HeaderControls] ⏭️ Already synced for key", key);
      return;
    }

    console.log("[runSessionFlow][HeaderControls] 🔄 Kickoff →", {
      roleId,
      projectId,
    });
    runSessionFlow(roleId, projectId, "HeaderControls")
      .then(() => {
        lastKeyRef.current = key;
        console.log("[runSessionFlow][HeaderControls] ✅ Synced");
      })
      .catch((e) =>
        console.warn("[HeaderControls] ⚠️ runSessionFlow error:", e)
      );
  }, [roleId, projectId, sessionReady, consumeManualSessionSync, key]);

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
          {isLoading ? (
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

export default HeaderControls;
