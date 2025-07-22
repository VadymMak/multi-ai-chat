// File: src/controllers/runSessionFlow.ts
import api from "../services/api";
import { getChatHistory } from "../services/aiApi";
import { useChatStore } from "../store/chatStore";
import { useProjectStore } from "../store/projectStore";
import type { AxiosError } from "axios";

/** One-flight per (role,project) so parallel triggers don't race */
const inflightByKey = new Map<string, Promise<void>>();

/** Normalize any thrown error (Axios or not) into a loggable shape */
function describeError(
  err: unknown
): { status: number | string; message: string } {
  const ax = err as AxiosError | undefined;
  if (ax && (ax as any).isAxiosError) {
    const status = ax.response?.status ?? (ax as any).status ?? "n/a";
    const message =
      (ax.response?.data as any)?.detail ??
      (typeof ax.response?.data === "string"
        ? ax.response.data
        : ax.message || "Axios error");
    return { status, message };
  }
  const anyErr = err as
    | { status?: number | string; message?: string; detail?: string }
    | undefined;
  return {
    status: anyErr?.status ?? "n/a",
    message: anyErr?.detail || anyErr?.message || "Unknown error",
  };
}

/**
 * Main session initialization flow
 * - ensure a valid project (loads if missing)
 * - try to RESTORE last session (+ history)
 * - create a NEW session only if restore not possible
 * - per-(role,project) locking; always sets sessionReady(true)
 */
export async function runSessionFlow(
  roleId: number,
  projectId?: number,
  sourceTag: string = "unknown"
): Promise<void> {
  if (!roleId || typeof roleId !== "number") {
    console.warn(`[runSessionFlow][${sourceTag}] ❌ Invalid roleId:`, roleId);
    return;
  }

  const projStore = useProjectStore.getState();
  const chat = useChatStore.getState();

  const { fetchProjectsForRole, getCachedProjects, setProjectId } = projStore;
  const {
    syncAndInitSession,
    lastSessionMarker,
    setChatSessionId,
    setTyping,
    setLastSessionMarker,
    setSessionReady,
    clearMessages,
    resetFetchTracking,
    setMessages,
  } = chat;

  console.debug(
    `[runSessionFlow][${sourceTag}] 🔄 Start → role=${roleId}, project=${
      projectId ?? "undefined"
    }`
  );

  // 1) Ensure projects are available for this role
  let projects = getCachedProjects(roleId);
  if (!projects || projects.length === 0) {
    projects = await fetchProjectsForRole(roleId);
  }
  if (!projects || projects.length === 0) {
    console.warn(
      `[runSessionFlow][${sourceTag}] ❌ No projects available for role=${roleId}`
    );
    return;
  }

  // 2) Determine usable project ID
  const selectedProjectId = projectId || projects[0]?.id;
  if (!selectedProjectId) {
    console.warn(`[runSessionFlow][${sourceTag}] ❌ No valid project ID found`);
    return;
  }

  // 3) Sync project store if caller didn't provide it
  if (!projectId) {
    setProjectId(selectedProjectId);
    console.debug(
      `[runSessionFlow][${sourceTag}] 📁 Synced projectId=${selectedProjectId} to store`
    );
  }

  const targetKey = `${roleId}-${selectedProjectId}`;
  const currentKey = lastSessionMarker
    ? `${lastSessionMarker.roleId}-${lastSessionMarker.projectId}`
    : null;
  const currentSid = lastSessionMarker?.chatSessionId || "";

  // ✅ Only treat as already-synced when we ALSO have a session id
  if (currentKey === targetKey && currentSid) {
    console.debug(
      `[runSessionFlow][${sourceTag}] ✅ Already synced: ${targetKey}`
    );
    return;
  }

  // One-flight per (role,project)
  if (inflightByKey.has(targetKey)) {
    console.debug(
      `[runSessionFlow][${sourceTag}] ⏳ Already running, waiting for previous to finish...`
    );
    return inflightByKey.get(targetKey)!;
  }

  const job = (async () => {
    try {
      // 4) Prep UI; do NOT clear messages until we know we need a new session
      setSessionReady(false);
      setTyping(false);

      // 5) Try to RESTORE last session for (role, project)
      let restored = false;
      try {
        const res = await api.get("/chat/last-session-by-role", {
          params: {
            role_id: roleId,
            project_id: selectedProjectId,
            limit: 200,
          },
        });
        const data = res?.data;

        if (data?.chat_session_id) {
          const sid = String(data.chat_session_id);

          // Prefer freshness from /history; fallback to payload messages
          const history = await getChatHistory(
            String(selectedProjectId),
            String(roleId),
            sid
          );
          const msgs = history?.messages ?? data?.messages ?? [];

          setChatSessionId(sid);
          setMessages(msgs);
          setLastSessionMarker({
            projectId: selectedProjectId,
            roleId,
            chatSessionId: sid,
          });

          console.debug(
            `[runSessionFlow][${sourceTag}] ✅ Restored session ${sid} with ${msgs.length} messages`
          );
          restored = true;
        } else {
          console.debug(
            `[runSessionFlow][${sourceTag}] ℹ️ No previous session id for ${targetKey} — will create new`
          );
        }
      } catch (err) {
        const { status, message } = describeError(err);
        console.warn(
          `[runSessionFlow][${sourceTag}] ⚠️ Restore error (status ${status}): ${message}`
        );
      }

      // 6) If nothing restored, create a NEW session
      if (!restored) {
        console.debug(
          `[runSessionFlow][${sourceTag}] 🧼 Resetting old session state (creating new)`
        );
        clearMessages();
        resetFetchTracking();
        setChatSessionId(null);
        setLastSessionMarker(null);

        const session = await syncAndInitSession(roleId, selectedProjectId);

        const sid = session?.chat_session_id
          ? String(session.chat_session_id)
          : "";
        if (!sid) {
          // Important: leave UI ready; first /ask will create and return a sid.
          console.warn(
            `[runSessionFlow][${sourceTag}] ℹ️ Backend returned no chat_session_id — first /ask will create it`
          );
        } else {
          setChatSessionId(sid);
          setLastSessionMarker({
            projectId: selectedProjectId,
            roleId,
            chatSessionId: sid,
          });
          console.debug(
            `[runSessionFlow][${sourceTag}] ✅ New session: ${sid}`
          );
        }
      }
    } catch (err) {
      const { status, message } = describeError(err);
      console.error(
        `[runSessionFlow][${sourceTag}] ❌ Failed to sync session (status ${status}) — ${message}`
      );
    } finally {
      setSessionReady(true); // UI must not get stuck
      inflightByKey.delete(targetKey);
      console.debug(`[runSessionFlow][${sourceTag}] ✅ Ready`);
    }
  })();

  inflightByKey.set(targetKey, job);
  return job;
}

/** Optional helper to clear all in-flight locks (e.g., on logout) */
export function resetRunSessionFlowLocks() {
  inflightByKey.clear();
}

export default runSessionFlow;
