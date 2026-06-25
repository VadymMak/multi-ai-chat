import React, { useState, useEffect, useCallback } from "react";
import { useFocusEffect } from "@react-navigation/native";
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  Alert,
  Modal,
  TextInput,
  ActivityIndicator,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import DateTimePicker, { DateTimePickerEvent } from "@react-native-community/datetimepicker";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { colors, spacing, borderRadius, typography } from "../theme";
import { STORAGE_KEYS } from "../lib/constants";
import {
  Reminder,
  loadReminders,
  addReminder,
  deleteReminder,
} from "../lib/reminders";
import {
  requestNotificationPermission,
  showMiuiHint,
} from "../lib/notifications";

const MIUI_HINT_KEY = "@multiaichat/miui_hint_shown";

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function RemindersScreen() {
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [modalVisible, setModalVisible] = useState(false);
  const [manualText, setManualText] = useState("");
  const [pickerDate, setPickerDate] = useState(new Date(Date.now() + 60 * 60 * 1000));
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [showTimePicker, setShowTimePicker] = useState(false);
  const [saving, setSaving] = useState(false);

  const reload = useCallback(async () => {
    setReminders(await loadReminders());
  }, []);

  // Reload every time this tab comes into focus so reminders added from
  // ChatScreen appear immediately without requiring a full unmount/remount.
  useFocusEffect(
    useCallback(() => {
      let active = true;
      (async () => {
        const r = await loadReminders();
        if (active) setReminders(r);
      })();
      return () => { active = false; };
    }, [])
  );

  useEffect(() => {
    ensurePermissions();
  }, []);

  async function ensurePermissions() {
    const granted = await requestNotificationPermission();
    if (!granted) return;
    const hintShown = await AsyncStorage.getItem(MIUI_HINT_KEY);
    if (!hintShown) {
      showMiuiHint();
      await AsyncStorage.setItem(MIUI_HINT_KEY, "1");
    }
  }

  async function handleAdd() {
    if (!manualText.trim()) {
      Alert.alert("Введите текст напоминания");
      return;
    }
    if (pickerDate.getTime() <= Date.now()) {
      Alert.alert("Выберите будущее время");
      return;
    }
    setSaving(true);
    try {
      await addReminder(manualText.trim(), pickerDate.toISOString());
      setManualText("");
      setPickerDate(new Date(Date.now() + 60 * 60 * 1000));
      setModalVisible(false);
      await reload();
    } catch (e) {
      Alert.alert("Ошибка", String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    Alert.alert("Удалить напоминание?", undefined, [
      { text: "Отмена", style: "cancel" },
      {
        text: "Удалить",
        style: "destructive",
        onPress: async () => {
          await deleteReminder(id);
          await reload();
        },
      },
    ]);
  }

  function onDateChange(_: DateTimePickerEvent, selected?: Date) {
    if (selected) {
      setPickerDate((prev) => {
        const next = new Date(selected);
        next.setHours(prev.getHours(), prev.getMinutes());
        return next;
      });
    }
    if (Platform.OS === "android") setShowDatePicker(false);
  }

  function onTimeChange(_: DateTimePickerEvent, selected?: Date) {
    if (selected) {
      setPickerDate((prev) => {
        const next = new Date(prev);
        next.setHours(selected.getHours(), selected.getMinutes());
        return next;
      });
    }
    if (Platform.OS === "android") setShowTimePicker(false);
  }

  const renderItem = ({ item }: { item: Reminder }) => (
    <View style={styles.card}>
      <View style={styles.cardBody}>
        <Text style={styles.cardText}>{item.text}</Text>
        <Text style={styles.cardTime}>{formatDateTime(item.fire_at)}</Text>
      </View>
      <TouchableOpacity onPress={() => handleDelete(item.id)} style={styles.deleteBtn}>
        <Ionicons name="trash-outline" size={20} color={colors.textHint} />
      </TouchableOpacity>
    </View>
  );

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      {/* Header */}
      <View style={styles.header}>
        <Ionicons name="alarm-outline" size={22} color={colors.accent} />
        <Text style={styles.headerTitle}>Напоминания</Text>
        <TouchableOpacity
          onPress={() => setModalVisible(true)}
          style={styles.addBtn}
          activeOpacity={0.7}
        >
          <Ionicons name="add" size={22} color={colors.onAccent} />
        </TouchableOpacity>
      </View>

      {reminders.length === 0 ? (
        <View style={styles.empty}>
          <Ionicons name="alarm-outline" size={56} color={colors.textHint} />
          <Text style={styles.emptyTitle}>Нет напоминаний</Text>
          <Text style={styles.emptyHint}>
            Напишите в чате «напомни завтра в 9 купить хлеб»{"\n"}или нажмите +
          </Text>
        </View>
      ) : (
        <FlatList
          data={reminders.slice().sort(
            (a, b) => new Date(a.fire_at).getTime() - new Date(b.fire_at).getTime()
          )}
          keyExtractor={(item) => item.id}
          renderItem={renderItem}
          contentContainerStyle={styles.list}
        />
      )}

      {/* Add reminder modal */}
      <Modal
        visible={modalVisible}
        animationType="slide"
        transparent
        onRequestClose={() => setModalVisible(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalSheet}>
            <Text style={styles.modalTitle}>Новое напоминание</Text>

            <TextInput
              style={styles.textInput}
              placeholder="Текст напоминания..."
              placeholderTextColor={colors.textHint}
              value={manualText}
              onChangeText={setManualText}
              multiline
              maxLength={200}
            />

            {/* Date / time pickers */}
            <View style={styles.pickerRow}>
              <TouchableOpacity
                style={styles.pickerBtn}
                onPress={() => setShowDatePicker(true)}
              >
                <Ionicons name="calendar-outline" size={16} color={colors.accent} />
                <Text style={styles.pickerBtnText}>
                  {pickerDate.toLocaleDateString("ru-RU", {
                    day: "2-digit",
                    month: "2-digit",
                    year: "2-digit",
                  })}
                </Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={styles.pickerBtn}
                onPress={() => setShowTimePicker(true)}
              >
                <Ionicons name="time-outline" size={16} color={colors.accent} />
                <Text style={styles.pickerBtnText}>
                  {pickerDate.toLocaleTimeString("ru-RU", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </Text>
              </TouchableOpacity>
            </View>

            {showDatePicker && (
              <DateTimePicker
                value={pickerDate}
                mode="date"
                display={Platform.OS === "ios" ? "spinner" : "default"}
                minimumDate={new Date()}
                onChange={onDateChange}
                themeVariant="dark"
              />
            )}
            {showTimePicker && (
              <DateTimePicker
                value={pickerDate}
                mode="time"
                display={Platform.OS === "ios" ? "spinner" : "default"}
                onChange={onTimeChange}
                themeVariant="dark"
              />
            )}

            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.cancelBtn}
                onPress={() => setModalVisible(false)}
              >
                <Text style={styles.cancelBtnText}>Отмена</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={[styles.saveBtn, saving && styles.saveBtnOff]}
                onPress={handleAdd}
                disabled={saving}
              >
                {saving ? (
                  <ActivityIndicator color={colors.onAccent} size="small" />
                ) : (
                  <Text style={styles.saveBtnText}>Добавить</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },

  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerTitle: {
    flex: 1,
    color: colors.textPrimary,
    ...typography.h3,
    letterSpacing: 0.5,
  },
  addBtn: {
    width: 36,
    height: 36,
    borderRadius: borderRadius.full,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },

  list: { padding: spacing.md, gap: spacing.sm },

  card: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  cardBody: { flex: 1, gap: 4 },
  cardText: { color: colors.textPrimary, fontSize: 15, lineHeight: 21 },
  cardTime: { color: colors.accent, fontSize: 12, fontWeight: "600" },
  deleteBtn: { padding: 6 },

  empty: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    paddingHorizontal: spacing.xl,
  },
  emptyTitle: { color: colors.textSecondary, ...typography.h3 },
  emptyHint: {
    color: colors.textHint,
    fontSize: 14,
    textAlign: "center",
    lineHeight: 20,
  },

  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.6)",
    justifyContent: "flex-end",
  },
  modalSheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: borderRadius.xl,
    borderTopRightRadius: borderRadius.xl,
    padding: spacing.lg,
    gap: spacing.md,
    paddingBottom: spacing.xl,
  },
  modalTitle: {
    color: colors.textPrimary,
    ...typography.h3,
    textAlign: "center",
  },

  textInput: {
    backgroundColor: colors.inputBg,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    minHeight: 72,
    textAlignVertical: "top",
  },

  pickerRow: { flexDirection: "row", gap: spacing.sm },
  pickerBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.inputBg,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.borderHi,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
  },
  pickerBtnText: { color: colors.textPrimary, fontSize: 14, fontWeight: "500" },

  modalActions: { flexDirection: "row", gap: spacing.sm, marginTop: 4 },
  cancelBtn: {
    flex: 1,
    paddingVertical: 13,
    borderRadius: borderRadius.md,
    backgroundColor: colors.inputBg,
    alignItems: "center",
  },
  cancelBtnText: { color: colors.textSecondary, fontSize: 15, fontWeight: "600" },
  saveBtn: {
    flex: 1,
    paddingVertical: 13,
    borderRadius: borderRadius.md,
    backgroundColor: colors.accent,
    alignItems: "center",
  },
  saveBtnOff: { backgroundColor: colors.inputBg },
  saveBtnText: { color: colors.onAccent, fontSize: 15, fontWeight: "700" },
});
