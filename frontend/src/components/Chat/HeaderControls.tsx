import React, { lazy, Suspense } from "react";

const AiSelector = lazy(
  () => import("../../features/aiConversation/AiSelector")
);
const MemoryRoleSelector = lazy(
  () => import("../../features/aiConversation/MemoryRoleSelector")
);
const ProjectSelector = lazy(
  () => import("../../features/aiConversation/ProjectSelector")
);

interface HeaderControlsProps {}

const HeaderControls: React.FC<HeaderControlsProps> = () => {
  return (
    <div className="sticky top-0 z-10 bg-white border-b p-3 shadow-sm">
      <div className="flex flex-wrap gap-2 justify-center sm:justify-start mb-2">
        <Suspense
          fallback={
            <div className="text-sm text-gray-400">Loading AI Selector…</div>
          }
        >
          <AiSelector />
        </Suspense>
      </div>

      <div className="flex flex-wrap gap-2 justify-center sm:justify-start">
        <Suspense
          fallback={
            <div className="text-sm text-gray-400">Loading Memory Roles…</div>
          }
        >
          <MemoryRoleSelector />
        </Suspense>

        <Suspense
          fallback={
            <div className="text-sm text-gray-400">Loading Projects…</div>
          }
        >
          <ProjectSelector />
        </Suspense>
      </div>
    </div>
  );
};

export default HeaderControls;
