// File: src/controllers/runSessionFlow.ts

import { useChatStore } from "../store/chatStore";
import { useProjectStore } from "../store/projectStore";

let sessionVersion = 0;
let flowLock: Promise<void> | null = null;

/**
 * Main session initialization flow
 * @param roleId - role ID to initialize
 * @param projectId - optional project ID to use
 * @param sourceTag - optional tag to identify which component triggered this
 */
export async function runSessionFlow(
  roleId: number,
  projectId?: number,
  sourceTag: string = "unknown"
) {
  if (!roleId || typeof roleId !== "number") {
    console.warn(`[runSessionFlow][${sourceTag}] ❌ Invalid roleId:`, roleId);
    return;
  }

  if (flowLock) {
    console.debug(
      `[runSessionFlow][${sourceTag}] ⏳ Already running, waiting for previous to finish...`
    );
    await flowLock;
    return;
  }

  flowLock = (async () => {
    const version = ++sessionVersion;

    const {
      fetchProjectsForRole,
      getCachedProjects,
      setProjectId,
    } = useProjectStore.getState();

    const {
      syncAndInitSession,
      lastSessionMarker,
      setChatSessionId,
      setMessages,
      setTyping,
      setLastSessionMarker,
    } = useChatStore.getState();

    console.debug(
      `[runSessionFlow][${sourceTag}] 🔄 Start → role=${roleId}, project=${
        projectId ?? "undefined"
      }`
    );

    // Step 1: Load projects for role
    let projects = getCachedProjects(roleId);
    if (!projects || projects.length === 0) {
      try {
        projects = await fetchProjectsForRole(roleId);
      } catch (err) {
        console.error(
          `[runSessionFlow][${sourceTag}] ❌ Failed to fetch projects`,
          err
        );
        return;
      }

      if (version !== sessionVersion) {
        console.debug(
          `[runSessionFlow][${sourceTag}] ⏹️ Cancelled — version changed`
        );
        return;
      }
    }

    // Step 2: Determine usable project ID
    const selectedProjectId = projectId || projects?.[0]?.id;

    if (!selectedProjectId) {
      console.warn(
        `[runSessionFlow][${sourceTag}] ❌ No valid project ID found`
      );
      return;
    }

    // Optionally sync frontend project store
    if (!projectId) {
      setProjectId(selectedProjectId);
      console.debug(
        `[runSessionFlow][${sourceTag}] 📁 Synced projectId=${selectedProjectId} to store`
      );
    }

    console.debug(
      `[runSessionFlow][${sourceTag}] 📁 Using project ID: ${selectedProjectId}`
    );

    // Step 3: Check if session already synced
    const currentKey = lastSessionMarker
      ? `${lastSessionMarker.roleId}-${lastSessionMarker.projectId}`
      : null;
    const targetKey = `${roleId}-${selectedProjectId}`;

    if (currentKey === targetKey) {
      console.debug(
        `[runSessionFlow][${sourceTag}] ✅ Already synced: ${targetKey}`
      );
      return;
    }

    // Step 4: Reset state before switching
    console.debug(
      `[runSessionFlow][${sourceTag}] 🧼 Resetting old session state`
    );
    setTyping(false);
    setMessages([]);
    setChatSessionId(null);
    setLastSessionMarker(null);

    // Step 5: Sync and initialize new session
    try {
      const session = await syncAndInitSession(roleId, selectedProjectId);

      if (version !== sessionVersion || !session?.chat_session_id) {
        console.debug(
          `[runSessionFlow][${sourceTag}] ⏹️ Cancelled — stale version or missing session`
        );
        return;
      }

      console.debug(
        `[runSessionFlow][${sourceTag}] ✅ New session: ${session.chat_session_id}`
      );
    } catch (err) {
      console.error(
        `[runSessionFlow][${sourceTag}] ❌ Failed to sync session`,
        err
      );
    }
  })();

  await flowLock;
  flowLock = null;
}
