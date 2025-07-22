import React, { lazy, Suspense, useEffect, useRef } from "react";
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
  const projectId = useProjectStore((s) => s.projectId);
  const { isLoading, initRoles } = useRoleStore();
  const consumeManualSessionSync = useChatStore(
    (s) => s.consumeManualSessionSync
  );

  const syncVersion = useRef(0);
  const hasSynced = useRef(false);

  // Load roles on mount
  useEffect(() => {
    initRoles();
  }, [initRoles]);

  // Only run sessionFlow once per role/project change
  useEffect(() => {
    if (!role?.id || !projectId) {
      console.log("[HeaderControls] ⛔ Cannot run — missing role or project");
      return;
    }

    if (consumeManualSessionSync) {
      console.log(
        "[HeaderControls] 🛑 Skipped runSessionFlow due to manual sync flag"
      );
      return;
    }

    const version = ++syncVersion.current;

    if (hasSynced.current) {
      console.log(
        "[HeaderControls] ⏭️ Already synced, skipping duplicate runSessionFlow."
      );
      return;
    }

    console.log("[runSessionFlow][HeaderControls] 🔄 Start →", {
      roleId: role.id,
      projectId,
    });

    runSessionFlow(role.id, projectId, "HeaderControls").then(() => {
      if (version !== syncVersion.current) return;
      hasSynced.current = true;
      console.log("[runSessionFlow][HeaderControls] ✅ Synced");
    });
  }, [role?.id, projectId, consumeManualSessionSync]);

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
