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

  const { lastSessionMarker, chatSessionId } = chatStore;

  const markerMatchesTarget =
    !!lastSessionMarker &&
    lastSessionMarker.roleId === roleId &&
    lastSessionMarker.projectId === projectId;

  const sessionIsReady =
    markerMatchesTarget &&
    !!lastSessionMarker.chatSessionId &&
    chatSessionId === lastSessionMarker.chatSessionId;

  logSessionFlow("📦 sessionController.ts → Sync check", {
    currentRoleId: memoryStore.role?.id,
    targetRoleId: roleId,
    currentProjectId: projectStore.projectId,
    targetProjectId: projectId,
    chatSessionId,
    lastSessionMarker,
    markerMatchesTarget,
    sessionIsReady,
  });

  if (!sessionIsReady) {
    logSessionFlow("🔁 sessionController.ts → (Re)initializing session", {
      roleId,
      projectId,
      reason: markerMatchesTarget
        ? "marker matches but in-memory session id differs/empty"
        : "marker does not match target role/project",
    });

    // Use the store's lock-aware helper; it sets sessionReady internally.
    await chatStore.syncAndInitSession(roleId, projectId);
  } else {
    logSessionFlow("✅ sessionController.ts → Session already synced", {
      roleId,
      projectId,
    });
  }
};

export const queueSessionSync = async (
  roleId: number,
  projectId: number
): Promise<void> => {
  const lockKey = `${roleId}-${projectId}`;

  if (sessionLocks.has(lockKey)) {
    return sessionLocks.get(lockKey)!;
  }

  const syncPromise = (async () => {
    try {
      logSessionFlow("[🔒 queueSessionSync] Lock acquired", {
        roleId,
        projectId,
      });
      await syncAndInitSession(roleId, projectId);
    } finally {
      sessionLocks.delete(lockKey);
      logSessionFlow("[🔓 queueSessionSync] Lock released", {
        roleId,
        projectId,
      });
    }
  })();

  sessionLocks.set(lockKey, syncPromise);
  return syncPromise;
};

export const rehydrateLastSessionFromStorage = async (): Promise<void> => {
  const chatStore = useChatStore.getState();
  const projectStore = useProjectStore.getState();
  const memoryStore = useMemoryStore.getState();

  const marker = chatStore.lastSessionMarker;
  const targetRoleId = marker?.roleId ?? memoryStore.role?.id;
  const targetProjectId = marker?.projectId ?? projectStore.projectId;

  logSessionFlow("🚀 rehydrateLastSessionFromStorage", {
    marker,
    targetRoleId,
    targetProjectId,
  });

  if (!targetRoleId || !targetProjectId) {
    logSessionFlow(
      "⚠️ rehydrateLastSessionFromStorage → no role/project to restore",
      {}
    );
    return;
  }

  await queueSessionSync(targetRoleId, targetProjectId);
};
