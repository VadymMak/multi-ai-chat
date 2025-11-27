// File: src/bootstrap/bootstrapApp.ts
import { useChatStore } from "../store/chatStore";
import { useMemoryStore } from "../store/memoryStore";
import { useProjectStore } from "../store/projectStore";
import api from "../services/api";
import { getChatHistory } from "../services/aiApi";
import { useAuthStore } from "@/store/authStore";

type Options = {
  nonBlocking?: boolean;
  maxTotalMs?: number; // soft budget for all work
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const withTimeout = <T>(p: Promise<T>, ms: number, tag: string): Promise<T> =>
  new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`${tag} timeout`)), ms);
    p.then((v) => {
      clearTimeout(t);
      resolve(v);
    }).catch((e) => {
      clearTimeout(t);
      reject(e);
    });
  });

const logBackendError = (err: any, label: string) => {
  const status = err?.status ?? err?.response?.status ?? "n/a";
  const msg =
    err?.detail ||
    err?.message ||
    (typeof err?.response?.data === "string"
      ? err.response.data.slice(0, 200)
      : "unknown");
  console.warn(
    `⚠️ Backend restore failed for ${label} (status ${status}): ${msg}`
  );
};

export async function bootstrapApp(opts: Options = {}) {
  const { isAuthenticated } = useAuthStore.getState();
  if (!isAuthenticated) {
    console.log("⏸️ [bootstrapApp] Not authenticated, skipping");
    return;
  }
  const { nonBlocking = false, maxTotalMs = 0 } = opts;
  const start = Date.now();

  const memory = useMemoryStore.getState();
  const projects = useProjectStore.getState();
  const chat = useChatStore.getState();

  const role = memory.role;
  const roleId = role?.id ?? null;
  const projectId = projects.projectId ?? null;

  // Try local restore quickly
  try {
    await withTimeout(chat.restoreSessionFromMarker(), 600, "local restore");
    // if it restored something, great — we’re done
    const marker = useChatStore.getState().lastSessionMarker;
    if (marker?.chatSessionId) return;
  } catch {
    // ignore
  }

  // Respect a soft time budget if nonBlocking
  const timeLeft = () =>
    maxTotalMs ? maxTotalMs - (Date.now() - start) : 99999;
  if (!roleId || !projectId) return;

  // Attempt a single fast backend restore; do not block UI
  try {
    const res = await withTimeout(
      api.get("/chat/last-session-by-role", {
        params: { role_id: roleId, project_id: projectId },
      }),
      Math.min(5000, Math.max(3000, timeLeft())),
      "/chat/last-session-by-role"
    );
    const data = res?.data;

    if (data?.chat_session_id) {
      const sid = String(data.chat_session_id);
      let history = null;

      try {
        history = await withTimeout(
          getChatHistory(String(projectId), String(roleId), sid),
          Math.min(5000, Math.max(3000, timeLeft())),
          "/chat/history"
        );
      } catch (e) {
        logBackendError(e, "/chat/history");
      }

      useChatStore.setState({
        chatSessionId: sid,
        messages: history?.messages ?? [],
        lastSessionMarker: { projectId, roleId, chatSessionId: sid },
        sessionReady: true,
      });
      return;
    }
  } catch (e) {
    logBackendError(e, "/chat/last-session-by-role");
  }

  // If we’re here, don’t block – seed a local session so the app is usable
  const fresh = crypto.randomUUID?.() ?? Math.random().toString(36).slice(2);
  useChatStore.setState({
    chatSessionId: fresh,
    messages: [],
    lastSessionMarker:
      roleId && projectId ? { projectId, roleId, chatSessionId: fresh } : null,
    sessionReady: true,
  });

  // If we still have “budget” and you *want* to try a background sync, do it quietly
  if (!nonBlocking) return;
  if (timeLeft() < 300) return;

  // Best-effort background sync (non-blocking)
  try {
    await sleep(0);
    await useChatStore.getState().syncAndInitSession(roleId, projectId);
  } catch (e) {
    logBackendError(e, "syncAndInitSession");
  }
}
