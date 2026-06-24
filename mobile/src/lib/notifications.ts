import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import { Alert, Platform } from "react-native";

// ─── Permission request ───────────────────────────────────────────────────────

export async function requestNotificationPermission(): Promise<boolean> {
  if (!Device.isDevice) return false;

  const { status: existing } = await Notifications.getPermissionsAsync();
  if (existing === "granted") return true;

  const { status } = await Notifications.requestPermissionsAsync();
  if (status !== "granted") return false;

  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("reminders", {
      name: "Напоминания",
      importance: Notifications.AndroidImportance.HIGH,
      sound: "default",
      vibrationPattern: [0, 250, 250, 250],
    });
  }

  return true;
}

// ─── MIUI / Xiaomi hint ───────────────────────────────────────────────────────
// Shows once on first-launch for Xiaomi devices where background notifications
// are off by default. Caller is responsible for tracking "shown" state.

export function showMiuiHint(): void {
  Alert.alert(
    "Xiaomi / MIUI",
    "Для надёжной доставки напоминаний:\n\n" +
      "1. Настройки → Приложения → Multi-AI Chat → Автозапуск → Вкл.\n" +
      "2. Настройки → Батарея → Экономия энергии → выберите приложение → Нет ограничений.",
    [{ text: "Понятно" }]
  );
}

// ─── Push token registration (optional, for future server-push) ───────────────

export async function registerForPushNotifications(): Promise<string | null> {
  if (!Device.isDevice) return null;

  const granted = await requestNotificationPermission();
  if (!granted) return null;

  try {
    const result = await Notifications.getExpoPushTokenAsync();
    return result.data;
  } catch {
    return null;
  }
}

// ─── Legacy daily reminder (Mamalog compat) ───────────────────────────────────

export async function scheduleDailyReminder(
  hour: number,
  minute: number
): Promise<void> {
  await Notifications.cancelAllScheduledNotificationsAsync();
  await Notifications.scheduleNotificationAsync({
    content: {
      title: "Дневник Mamalog",
      body: "Не забудьте записать наблюдения за сегодня",
      sound: true,
    },
    trigger: {
      type: Notifications.SchedulableTriggerInputTypes.DAILY,
      hour,
      minute,
    },
  });
}

export async function cancelAllNotifications(): Promise<void> {
  await Notifications.cancelAllScheduledNotificationsAsync();
}
