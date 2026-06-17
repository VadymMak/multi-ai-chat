import React, { useState, useEffect } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useAuthContext } from "../context/AuthContext";
import { STORAGE_KEYS } from "../lib/constants";
import { colors, spacing, borderRadius } from "../theme";

type ModelKey = "gpt" | "claude" | "grok";

const MODELS: { key: ModelKey; label: string }[] = [
  { key: "gpt", label: "GPT-4o" },
  { key: "claude", label: "Claude" },
  { key: "grok", label: "Grok" },
];

export default function SettingsScreen() {
  const { user, signOut } = useAuthContext();
  const [defaultModel, setDefaultModel] = useState<ModelKey | null>(null);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEYS.DEFAULT_MODEL).then((val) => {
      if (val === "gpt" || val === "claude" || val === "grok") {
        setDefaultModel(val as ModelKey);
      }
    });
  }, []);

  const selectModel = async (key: ModelKey) => {
    const next = defaultModel === key ? null : key;
    setDefaultModel(next);
    if (next) {
      await AsyncStorage.setItem(STORAGE_KEYS.DEFAULT_MODEL, next);
    } else {
      await AsyncStorage.removeItem(STORAGE_KEYS.DEFAULT_MODEL);
    }
  };

  const handleLogout = () => {
    Alert.alert("Выход", "Вы уверены, что хотите выйти?", [
      { text: "Отмена", style: "cancel" },
      { text: "Выйти", style: "destructive", onPress: signOut },
    ]);
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Настройки</Text>
      </View>

      <View style={styles.content}>
        <View style={styles.card}>
          <View style={styles.userRow}>
            <View style={styles.avatar}>
              <MaterialCommunityIcons name="account" size={28} color={colors.accent} />
            </View>
            <View style={styles.userInfo}>
              <Text style={styles.userName}>
                {user?.name || user?.email || "Пользователь"}
              </Text>
              {user?.email ? (
                <Text style={styles.userEmail}>{user.email}</Text>
              ) : null}
            </View>
          </View>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionLabel}>Модель по умолчанию</Text>
          <Text style={styles.sectionHint}>
            Применяется в режиме «Чат» (можно менять прямо в чате)
          </Text>
          <View style={styles.modelRow}>
            {MODELS.map(({ key, label }) => (
              <TouchableOpacity
                key={key}
                style={[styles.chip, defaultModel === key && styles.chipActive]}
                onPress={() => selectModel(key)}
                activeOpacity={0.7}
              >
                <Text
                  style={[
                    styles.chipText,
                    defaultModel === key && styles.chipTextActive,
                  ]}
                >
                  {label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
          {!defaultModel && (
            <Text style={styles.autoHint}>Авто — выбирается сервером</Text>
          )}
        </View>

        <TouchableOpacity
          style={styles.logoutBtn}
          onPress={handleLogout}
          activeOpacity={0.8}
        >
          <MaterialCommunityIcons name="logout" size={20} color="#E05D5D" />
          <Text style={styles.logoutText}>Выйти из аккаунта</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  header: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerTitle: { color: colors.textPrimary, fontSize: 24, fontWeight: "700" },
  content: { padding: spacing.md, gap: 12 },
  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 10,
  },
  userRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  avatar: {
    width: 50,
    height: 50,
    borderRadius: 25,
    backgroundColor: colors.inputBg,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: colors.borderHi,
  },
  userInfo: { flex: 1 },
  userName: { color: colors.textPrimary, fontSize: 17, fontWeight: "600" },
  userEmail: { color: colors.textSecondary, fontSize: 13, marginTop: 2 },
  sectionLabel: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  sectionHint: { color: colors.textHint, fontSize: 12, marginTop: -6 },
  modelRow: { flexDirection: "row", gap: 8 },
  chip: {
    flex: 1,
    paddingVertical: 10,
    alignItems: "center",
    borderRadius: borderRadius.md,
    backgroundColor: colors.inputBg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
  chipTextActive: { color: colors.onAccent },
  autoHint: { color: colors.textHint, fontSize: 12, textAlign: "center" },
  logoutBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    paddingVertical: 14,
    borderWidth: 1,
    borderColor: "#3A2020",
  },
  logoutText: { color: "#E05D5D", fontSize: 16, fontWeight: "600" },
});
