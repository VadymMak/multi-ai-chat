import { useState, useEffect } from "react";

interface NetworkStatus {
  isOnline: boolean;
  wasOffline: boolean;
}

export const useNetworkStatus = (): NetworkStatus => {
  const [isOnline, setIsOnline] = useState<boolean>(navigator.onLine);
  const [wasOffline, setWasOffline] = useState<boolean>(false);

  useEffect(() => {
    const handleOnline = () => {
      console.log("🌐 Network status: ONLINE");
      setIsOnline(true);
      setWasOffline(true);

      // Reset wasOffline after a delay
      setTimeout(() => {
        setWasOffline(false);
      }, 3000);
    };

    const handleOffline = () => {
      console.log("📡 Network status: OFFLINE");
      setIsOnline(false);
      setWasOffline(false);
    };

    // Add event listeners
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    // Log initial status
    console.log(
      `🌐 Initial network status: ${navigator.onLine ? "ONLINE" : "OFFLINE"}`
    );

    // Cleanup
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  return { isOnline, wasOffline };
};
