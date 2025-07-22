import { useEffect } from "react";

export const useSessionCleanup = () => {
  useEffect(() => {
    const handleBeforeUnload = () => {
      try {
        // ✅ Read and parse last session marker safely
        const marker = localStorage.getItem("chat-storage");
        let preservedMarker: string | null = null;

        if (marker) {
          const parsed = JSON.parse(marker);
          const lastMarker = parsed?.state?.lastSessionMarker;

          if (lastMarker) {
            preservedMarker = JSON.stringify({
              state: { lastSessionMarker: lastMarker },
              version: parsed.version || 0,
            });
          }
        }

        // 🧹 Clear full chat storage
        localStorage.removeItem("chat-storage");

        // ✅ Restore only the lastSessionMarker
        if (preservedMarker) {
          localStorage.setItem("chat-storage", preservedMarker);
          console.log("💾 Preserved lastSessionMarker on unload.");
        } else {
          console.log("ℹ️ No session marker to preserve.");
        }
      } catch (err) {
        console.warn("⚠️ Session cleanup failed:", err);
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, []);
};
