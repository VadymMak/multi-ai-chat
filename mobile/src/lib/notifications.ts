import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import { Alert, Platform } from "react-native";

// ─── Notification channel ─────────────────────────────────────────────────────
// "reminders-v2" uses a new id so Android picks up MAX importance/sound
// (existing channel settings cannot be changed after first creation).

export async function ensureReminderChannel(): Promise<void> {
  if (Platform.OS !== "android") return;
  await Notifications.setNotificationChannelAsync("reminders-v2", {
    name: "Напоминания",
    importance: Notifications.AndroidImportance.MAX,
    sound: "default",
    vibrationPattern: [0, 400, 250, 400],
    lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
    bypassDnd: false,
  });
}

// ─── Permission request ───────────────────────────────────────────────────────

export async function requestNotificationPermission(): Promise<boolean> {
  if (!Device.isDevice) return false;

  const { status: existing } = await Notifications.getPermissionsAsync();
  if (existing === "granted") {
    await ensureReminderChannel();
    return true;
  }

  const { status } = await Notifications.requestPermissionsAsync();
  if (status !== "granted") return false;

  await ensureReminderChannel();
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
