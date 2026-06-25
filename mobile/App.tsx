import React, { useEffect } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import * as Updates from "expo-updates";
import * as Notifications from "expo-notifications";
import { AuthProvider } from "./src/context/AuthContext";
import AppNavigator from "./src/navigation/AppNavigator";
import { ensureReminderChannel } from "./src/lib/notifications";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

async function checkForOTAUpdate() {
  try {
    const update = await Updates.checkForUpdateAsync();
    if (update.isAvailable) {
      await Updates.fetchUpdateAsync();
      await Updates.reloadAsync();
    }
  } catch {
    // Non-fatal: dev builds and first APK launch may not have a channel yet
  }
}

export default function App() {
  useEffect(() => {
    checkForOTAUpdate();
    ensureReminderChannel();
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <AuthProvider>
        <AppNavigator />
      </AuthProvider>
    </GestureHandlerRootView>
  );
}
