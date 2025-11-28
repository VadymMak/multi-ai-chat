// File: src/components/Chat/HeaderControls.tsx
import React, { lazy, Suspense, useEffect, useRef, useMemo } from "react";
import axios from "axios";
import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";
import { useChatStore } from "../../store/chatStore";
import { useToastStore } from "../../store/toastStore";
import { runSessionFlow } from "../../controllers/runSessionFlow";
import ExportButton from "./ExportButton";
import { TokenBudgetIndicator } from "./TokenBudgetIndicator";
import { TokenLimitBadge } from "./TokenLimitBadge";

const AiSelector = lazy(
  () => import("../../features/aiConversation/AiSelector")
);
const BalanceIndicator = lazy(() => import("../Shared/BalanceIndicator"));

const DEBUG = process.env.NODE_ENV !== "production";

const HeaderControls: React.FC = () => {
  const roleId = useMemoryStore((s) =>
    typeof s.role?.id === "number" ? s.role.id : null
  );
  const projectId = useProjectStore((s) => s.projectId);

  // NOTE: Some versions expose this as a boolean; others as () => boolean
  const rawManualSync = useChatStore(
    (s) => (s as any).consumeManualSessionSync
  ) as boolean | (() => boolean) | undefined;

  const sessionReady = useChatStore((s) => s.sessionReady);

  // Token budget tracking
  const totalTokens = useChatStore((state) => state.totalTokens);
  const maxTokens = useChatStore((state) => state.maxTokens);

  const lastKeyRef = useRef<string | null>(null);
  const inFlightRef = useRef<Set<string>>(new Set());

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

    // ✅ ADD DELAY: Wait for ProjectSelector to finish first
    const timeoutId = setTimeout(() => {
      // Re-check key hasn't changed during delay
      const currentKey = `${useMemoryStore.getState().role?.id}-${
        useProjectStore.getState().projectId
      }`;
      if (currentKey !== key) {
        DEBUG &&
          console.debug(
            "[HeaderControls] ⏭️ Key changed during delay, skipping:",
            key,
            "→",
            currentKey
          );
        return;
      }

      if (lastKeyRef.current === key) {
        DEBUG &&
          console.debug(
            "[HeaderControls] ⏭️ Already synced during delay for key:",
            key
          );
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
    }, 150); // ✅ 150ms delay to let ProjectSelector finish

    return () => clearTimeout(timeoutId); // ✅ Cleanup on re-render
  }, [roleId, projectId, key, sessionReady, rawManualSync]);

  return (
    <div className="sticky top-0 z-10 bg-panel border-b border-border w-full">
      <div className="w-full max-w-[1200px] mx-auto">
        {/* AI Selector + Balance + Export */}
        <div className="flex flex-row flex-wrap items-center justify-between gap-2 py-3 px-6">
          {/* Left side - AI Selector */}
          <Suspense
            fallback={
              <div className="text-sm text-text-secondary">
                Loading AI Selector…
              </div>
            }
          >
            <AiSelector />
          </Suspense>

          {/* Right side - Token Limit + Token Budget + Export + Balance */}
          <div className="flex items-center gap-2">
            {/* Token Limit Badge */}
            <TokenLimitBadge />

            {/* Token Budget Indicator */}
            {totalTokens > 0 && (
              <TokenBudgetIndicator
                usedTokens={totalTokens}
                maxTokens={maxTokens}
                onSummarize={async () => {
                  const { chatSessionId } = useChatStore.getState();
                  const { addToast } = useToastStore.getState();

                  if (!chatSessionId) {
                    addToast("No active session to summarize", "error");
                    return;
                  }

                  if (!roleId || !projectId) {
                    addToast("Missing role or project context", "error");
                    return;
                  }

                  try {
                    addToast("Creating summary...", "info");

                    const response = await axios.post(
                      "/api/chat/manual-summary",
                      null,
                      {
                        params: {
                          project_id: projectId,
                          role_id: roleId,
                          chat_session_id: chatSessionId,
                          message_count: 20,
                        },
                      }
                    );

                    if (response.data.success) {
                      const tokensSaved = response.data.tokens_saved || 0;
                      addToast(
                        `Summary created! Saved ${tokensSaved} tokens`,
                        "success"
                      );

                      // Reload messages to reflect summary
                      if (roleId && projectId) {
                        await runSessionFlow(roleId, projectId, "AfterSummary");
                      }
                    } else {
                      addToast(
                        `Failed to create summary: ${response.data.error}`,
                        "error"
                      );
                    }
                  } catch (error) {
                    console.error("Summarize error:", error);
                    addToast("Failed to create summary", "error");
                  }
                }}
              />
            )}

            {/* Export Button */}
            <ExportButton />

            {/* Balance Indicator */}
            <Suspense
              fallback={
                <div className="text-yellow-500">Loading balance...</div>
              }
            >
              <BalanceIndicator compact />
            </Suspense>
          </div>
        </div>
      </div>
    </div>
  );
};

export default React.memo(HeaderControls);
