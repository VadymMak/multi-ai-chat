import React, { useState, useEffect } from "react";
import { useNetworkStatus } from "../hooks/useNetworkStatus";
import { useBackendStatus } from "../hooks/useBackendStatus";

export const NetworkStatus: React.FC = () => {
  const { isOnline } = useNetworkStatus();
  const { isBackendOnline } = useBackendStatus();
  const [showRecovery, setShowRecovery] = useState(false);
  const [wasOffline, setWasOffline] = useState(false);

  // Track recovery
  useEffect(() => {
    const currentlyOffline = !isOnline || !isBackendOnline;

    // If we were offline and now we're online
    if (wasOffline && !currentlyOffline) {
      setShowRecovery(true);
      // Hide recovery message after 3 seconds
      const timer = setTimeout(() => {
        setShowRecovery(false);
        setWasOffline(false);
      }, 3000);
      return () => clearTimeout(timer);
    }

    // Update offline tracking
    if (currentlyOffline) {
      setWasOffline(true);
    }
  }, [isOnline, isBackendOnline, wasOffline]);

  // Show recovery message
  if (showRecovery) {
    return (
      <div
        className="fixed top-0 left-0 right-0 z-[9999] bg-green-600 text-white px-4 py-3 text-center shadow-lg"
        role="alert"
      >
        <span className="font-medium">✅ Connected!</span>
      </div>
    );
  }

  // Don't show anything if everything is working
  if (isOnline && isBackendOnline) {
    return null;
  }

  // Determine which error message to show
  let message = "";
  if (!isOnline) {
    message = "⚠️ No internet connection. Please check your network.";
  } else if (!isBackendOnline) {
    message = "⚠️ Server unavailable. Trying to reconnect...";
  }

  return (
    <div
      className="fixed top-0 left-0 right-0 z-[9999] bg-red-600 text-white px-4 py-3 text-center shadow-lg"
      role="alert"
    >
      <span className="font-medium">{message}</span>
    </div>
  );
};
