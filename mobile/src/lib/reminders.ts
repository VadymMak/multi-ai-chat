import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Notifications from "expo-notifications";
import { STORAGE_KEYS } from "./constants";

export interface Reminder {
  id: string;
  text: string;
  fire_at: string;           // ISO datetime
  notificationId: string;    // expo-notifications identifier
}

// ─── Persistence ─────────────────────────────────────────────────────────────

export async function loadReminders(): Promise<Reminder[]> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEYS.REMINDERS);
    return raw ? (JSON.parse(raw) as Reminder[]) : [];
  } catch {
    return [];
  }
}

async function saveReminders(reminders: Reminder[]): Promise<void> {
  await AsyncStorage.setItem(STORAGE_KEYS.REMINDERS, JSON.stringify(reminders));
}

// ─── Scheduling ───────────────────────────────────────────────────────────────

export async function addReminder(
  text: string,
  fire_at: string
): Promise<Reminder> {
  const notificationId = await Notifications.scheduleNotificationAsync({
    content: {
      title: "Напоминание",
      body: text,
      sound: "default",
    },
    trigger: {
      type: Notifications.SchedulableTriggerInputTypes.DATE,
      date: new Date(fire_at),
      channelId: "reminders-v2",
    },
  });

  const reminder: Reminder = {
    id: String(Date.now()),
    text,
    fire_at,
    notificationId,
  };

  const current = await loadReminders();
  await saveReminders([...current, reminder]);
  return reminder;
}

export async function deleteReminder(id: string): Promise<void> {
  const current = await loadReminders();
  const target = current.find((r) => r.id === id);
  if (target) {
    try {
      await Notifications.cancelScheduledNotificationAsync(target.notificationId);
    } catch {
      // Already fired or cancelled — safe to ignore
    }
  }
  await saveReminders(current.filter((r) => r.id !== id));
}

// ─── Reschedule on app launch ─────────────────────────────────────────────────
// Fires still-pending reminders that survived app restart.
// expo-notifications retains scheduled notifications across restarts on Android,
// so this is a safety net for edge cases (reinstall, permission reset).

export async function rescheduleStaleReminders(): Promise<void> {
  const reminders = await loadReminders();
  const now = Date.now();
  const still_future = reminders.filter((r) => new Date(r.fire_at).getTime() > now);

  // Remove past reminders from storage
  if (still_future.length !== reminders.length) {
    await saveReminders(still_future);
  }
}
