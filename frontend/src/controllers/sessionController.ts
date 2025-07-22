// File: src/controllers/sessionController.ts

import { useChatStore } from "../store/chatStore";
import { useProjectStore } from "../store/projectStore";
import { useMemoryStore } from "../store/memoryStore";
import { logSessionFlow } from "../utils/debugSessionFlow";

const sessionLocks = new Map<string, Promise<void>>();

export const syncAndInitSession = async (
  roleId: number,
  projectId: number
): Promise<void> => {
  const chatStore = useChatStore.getState();
  const projectStore = useProjectStore.getState();
  const memoryStore = useMemoryStore.getState();

  const lastMarker = chatStore.lastSessionMarker;

  const sessionIsReady =
    lastMarker &&
    lastMarker.roleId === roleId &&
    lastMarker.projectId === projectId;

  logSessionFlow("📦 sessionController.ts → Sync check", {
    currentRoleId: memoryStore.role?.id,
    targetRoleId: roleId,
    currentProjectId: projectStore.projectId,
    targetProjectId: projectId,
    chatSessionId: chatStore.chatSessionId,
    lastSessionMarker: lastMarker,
    sessionIsReady,
  });

  if (!sessionIsReady) {
    logSessionFlow("🔁 sessionController.ts → Forcing session init", {
      roleId,
      projectId,
    });

    await chatStore.loadOrInitSessionForRoleProject(roleId, projectId);
  } else {
    logSessionFlow("✅ sessionController.ts → Session already synced", {
      roleId,
      projectId,
    });
  }
};

// 🧠 Queued session sync (avoids rapid double init)
export const queueSessionSync = async (
  roleId: number,
  projectId: number
): Promise<void> => {
  const lockKey = `${roleId}-${projectId}`;

  // If already locking this combination, return that Promise
  if (sessionLocks.has(lockKey)) {
    return sessionLocks.get(lockKey)!;
  }

  const syncPromise = (async () => {
    try {
      logSessionFlow("[🔒 queueSessionSync] Lock acquired:", {
        roleId,
        projectId,
      });
      await syncAndInitSession(roleId, projectId);
    } finally {
      sessionLocks.delete(lockKey);
    }
  })();

  sessionLocks.set(lockKey, syncPromise);
  return syncPromise;
};
