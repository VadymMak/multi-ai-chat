import { useState, useEffect } from "react";
import axios from "axios";

interface BackendStatus {
  isBackendOnline: boolean;
  lastCheck: Date | null;
}

export const useBackendStatus = (): BackendStatus => {
  const [isBackendOnline, setIsBackendOnline] = useState<boolean>(true);
  const [lastCheck, setLastCheck] = useState<Date | null>(null);

  useEffect(() => {
    const checkBackend = async () => {
      let failureCount = 0;

      // Retry twice before marking as offline
      for (let attempt = 1; attempt <= 2; attempt++) {
        try {
          // Ping health endpoint with 5 second timeout
          await axios.get("/api/health", { timeout: 5000 });

          const now = new Date();
          setLastCheck(now);

          if (!isBackendOnline) {
            console.log("🟢 Backend status: ONLINE (recovered)");
            setIsBackendOnline(true);
          }
          return; // Success, exit early
        } catch (error) {
          failureCount++;
          console.log(`🔴 Backend health check attempt ${attempt}/2 failed`);

          if (attempt < 2) {
            // Wait 2 seconds before retry
            await new Promise((resolve) => setTimeout(resolve, 2000));
          }
        }
      }

      // Both attempts failed
      const now = new Date();
      setLastCheck(now);

      if (isBackendOnline) {
        console.log("🔴 Backend status: OFFLINE (2 checks failed)");
        setIsBackendOnline(false);
      }
    };

    // Check immediately on mount
    checkBackend();

    // Then check every 30 seconds
    const interval = setInterval(checkBackend, 30000);

    return () => clearInterval(interval);
  }, [isBackendOnline]);

  return { isBackendOnline, lastCheck };
};
