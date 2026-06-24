import React, { useState, useCallback, useEffect } from "react";
import {
  View,
  Text,
  TextInput,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Image,
  Pressable,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import AsyncStorage from "@react-native-async-storage/async-storage";
import Markdown from "react-native-markdown-display";
import { api } from "../lib/api";
import { useVoiceRecorder } from "../hooks/useVoiceRecorder";
import { STORAGE_KEYS } from "../lib/constants";
import { colors, spacing, borderRadius } from "../theme";
import { addReminder } from "../lib/reminders";
import { requestNotificationPermission } from "../lib/notifications";

type Mode = "chat" | "notes" | "web" | "save" | "reminder";
type ModelKey = "gpt" | "claude" | "grok";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  mode?: Mode;
  modelUsed?: string | null;
  sources?: unknown[];
  savedTitle?: string | null;
}

const MODE_OPTIONS: { key: Exclude<Mode, "reminder">; label: string }[] = [
  { key: "chat", label: "Чат" },
  { key: "notes", label: "Заметки" },
  { key: "web", label: "Поиск" },
  { key: "save", label: "Сохр." },
];

const MODEL_OPTIONS: { key: ModelKey; label: string }[] = [
  { key: "gpt", label: "GPT" },
  { key: "claude", label: "Claude" },
  { key: "grok", label: "Grok" },
];

const LOADING_ID = "__loading__";

const MODE_META: Record<Mode, { emoji: string; bg: string; color: string }> = {
  chat: { emoji: "💬", bg: colors.inputBg, color: colors.textSecondary },
  notes: { emoji: "🔎", bg: colors.tagNotesBg, color: colors.tagNotes },
  web: { emoji: "🌐", bg: colors.tagSearchBg, color: colors.tagSearch },
  save: { emoji: "✅", bg: colors.tagNotesBg, color: colors.tagNotes },
  reminder: { emoji: "🔔", bg: colors.tagSearchBg, color: colors.tagSearch },
};

const MODE_LABELS: Record<Mode, string> = {
  chat: "Чат",
  notes: "Заметки",
  web: "Поиск",
  save: "Сохранено",
  reminder: "Напоминание",
};

export default function ChatScreen() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [mode, setMode] = useState<Mode>("chat");
  const [selectedModel, setSelectedModel] = useState<ModelKey | null>(null);
  const [inputText, setInputText] = useState("");
  const [pendingImage, setPendingImage] =
    useState<ImagePicker.ImagePickerAsset | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEYS.DEFAULT_MODEL).then((val) => {
      if (val === "gpt" || val === "claude" || val === "grok") {
        setSelectedModel(val as ModelKey);
      }
    });
  }, []);

  const REMINDER_RE = /^\s*(напомн\w*|напомин\w*|remind\w*|reminder)\b[\s,:\-—]*/i;
  const DEVICE_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

  const sendReminder = useCallback(
    async (displayText: string, apiText: string) => {
      if (isLoading) return;
      const payload = apiText.trim() || displayText.trim();
      setMessages((prev) => [
        { id: String(Date.now()), role: "user", content: displayText },
        { id: "__loading__", role: "assistant", content: "" },
        ...prev,
      ]);
      setInputText("");
      setIsLoading(true);
      try {
        const granted = await requestNotificationPermission();
        if (!granted) {
          throw new Error("Разрешение на уведомления не выдано");
        }
        const { data } = await api.post("/api/app/parse-reminder", { text: payload, tz: DEVICE_TZ });
        await addReminder(data.text, data.fire_at);
        const when = new Date(data.fire_at).toLocaleString("ru-RU", {
          day: "2-digit", month: "2-digit", year: "2-digit",
          hour: "2-digit", minute: "2-digit",
        });
        setMessages((prev) => [
          {
            id: String(Date.now() + 1),
            role: "assistant",
            content: `⏰ Напоминание: ${data.text} — ${when}`,
            mode: "reminder" as Mode,
          },
          ...prev.filter((m) => m.id !== "__loading__"),
        ]);
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } }; message?: string })
          ?.response?.data?.detail ?? (err as { message?: string })?.message ?? "Ошибка";
        setMessages((prev) => [
          { id: String(Date.now() + 1), role: "assistant", content: `❌ ${msg}`, mode: "chat" },
          ...prev.filter((m) => m.id !== "__loading__"),
        ]);
      } finally {
        setIsLoading(false);
      }
    },
    [isLoading]
  );

  const send = useCallback(
    async (opts?: { audioUri?: string }) => {
      const text = inputText.trim();
      const audioUri = opts?.audioUri;
      if (!text && !pendingImage && !audioUri) return;
      if (isLoading) return;

      // Reminder shortcut — text only, no audio/image
      if (text && !audioUri && !pendingImage && REMINDER_RE.test(text)) {
        const stripped = text.replace(REMINDER_RE, "").trim();
        await sendReminder(text, stripped);
        return;
      }

      const imgCopy = pendingImage;

      const userContent =
        audioUri && imgCopy
          ? "🎤📷 Голосовое + фото"
          : audioUri
          ? "🎤 Голосовое сообщение"
          : imgCopy
          ? (text ? `📷 ${text}` : "📷 Фото")
          : text;

      setMessages((prev) => [
        { id: String(Date.now()), role: "user", content: userContent },
        ...prev,
      ]);
      setInputText("");
      setPendingImage(null);
      setIsLoading(true);

      try {
        const formData = new FormData();
        formData.append("mode", mode);
        formData.append("tz", DEVICE_TZ);
        if (selectedModel) formData.append("model", selectedModel);

        if (audioUri) {
          formData.append("audio", {
            uri: audioUri,
            type: "audio/m4a",
            name: "voice.m4a",
          } as unknown as Blob);
        } else if (text) {
          formData.append("text", text);
        }
        if (imgCopy) {
          formData.append("image", {
            uri: imgCopy.uri,
            type: imgCopy.mimeType || "image/jpeg",
            name: "photo.jpg",
          } as unknown as Blob);
        }

        const { data } = await api.post("/api/app/message", formData, {
          headers: { "Content-Type": "multipart/form-data" },
          timeout: 90_000,
        });

        // Reminder from backend (voice, text, or photo): schedule local notification
        if (data.kind === "reminder" && data.fire_at) {
          try {
            await requestNotificationPermission();
            await addReminder(data.text, data.fire_at);
          } catch {
            // Non-fatal
          }
        }

        const content =
          data.mode === "save"
            ? `✅ Сохранено${data.saved_title ? `: ${data.saved_title}` : ""}`
            : data.kind === "reminder" && data.fire_at
            ? (() => {
                const when = new Date(data.fire_at).toLocaleString("ru-RU", {
                  day: "2-digit", month: "2-digit", year: "2-digit",
                  hour: "2-digit", minute: "2-digit",
                });
                return `⏰ Напоминание: ${data.text} — ${when}`;
              })()
            : data.answer || "⚠️ Пустой ответ от сервера";

        setMessages((prev) => [
          {
            id: String(Date.now() + 1),
            role: "assistant",
            content,
            mode: (data.kind === "reminder" ? "reminder" : data.mode) as Mode,
            modelUsed: data.model_used,
            sources: data.sources,
            savedTitle: data.saved_title,
          },
          ...prev,
        ]);
      } catch (err: unknown) {
        const axiosErr = err as { response?: { data?: { detail?: string } }; message?: string };
        const detail = axiosErr.response?.data?.detail || axiosErr.message || "Ошибка";
        setMessages((prev) => [
          {
            id: String(Date.now() + 1),
            role: "assistant",
            content: `❌ ${detail}`,
            mode,
          },
          ...prev,
        ]);
      } finally {
        setIsLoading(false);
      }
    },
    [inputText, pendingImage, isLoading, mode, selectedModel, sendReminder]
  );

  const { isRecording, startRecording, stopRecording } = useVoiceRecorder({
    onRecordingComplete: (uri) => send({ audioUri: uri }),
  });

  const pickImage = async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== "granted") return;
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: "images",
      quality: 0.8,
    });
    if (!result.canceled && result.assets[0]) {
      setPendingImage(result.assets[0]);
    }
  };

  const toggleModel = (key: ModelKey) =>
    setSelectedModel((prev) => (prev === key ? null : key));

  const listData: Message[] = isLoading
    ? [{ id: LOADING_ID, role: "assistant", content: "" }, ...messages]
    : messages;

  const renderItem = ({ item }: { item: Message }) => {
    if (item.id === LOADING_ID) {
      return (
        <View style={[styles.bubble, styles.bubbleAssistant]}>
          <ActivityIndicator color={colors.textHint} size="small" />
        </View>
      );
    }

    if (item.role === "user") {
      return (
        <View style={styles.rowRight}>
          <View style={[styles.bubble, styles.bubbleUser]}>
            <Text style={styles.userText}>{item.content}</Text>
          </View>
        </View>
      );
    }

    const m = item.mode ?? "chat";
    const meta = MODE_META[m];

    return (
      <View style={[styles.bubble, styles.bubbleAssistant]}>
        <View style={styles.metaRow}>
          <View style={[styles.modeTag, { backgroundColor: meta.bg }]}>
            <Text style={[styles.modeTagText, { color: meta.color }]}>
              {meta.emoji} {MODE_LABELS[m]}
            </Text>
          </View>
          {item.modelUsed ? (
            <View style={styles.modelTag}>
              <Text style={styles.modelTagText}>{item.modelUsed}</Text>
            </View>
          ) : null}
        </View>

        <Markdown style={mdStyles}>{item.content}</Markdown>

        {item.sources && item.sources.length > 0 ? (
          <SourcesList mode={m} sources={item.sources} />
        ) : null}
      </View>
    );
  };

  const canSend = (inputText.trim().length > 0 || pendingImage !== null) && !isLoading;

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        {/* Header */}
        <View style={styles.header}>
          <MaterialCommunityIcons name="brain" size={22} color={colors.accent} />
          <Text style={styles.headerTitle}>Brain</Text>
        </View>

        {/* Messages / empty state — empty rendered OUTSIDE inverted FlatList to avoid mirroring */}
        {listData.length === 0 ? (
          <View style={styles.emptyOuter}>
            <MaterialCommunityIcons name="brain" size={60} color={colors.textHint} />
            <Text style={styles.emptyTitle}>Привет! Я Brain</Text>
            <Text style={styles.emptyHint}>
              Задайте вопрос, поищите в заметках или сохраните идею
            </Text>
          </View>
        ) : (
          <FlatList
            data={listData}
            keyExtractor={(item) => item.id}
            renderItem={renderItem}
            inverted
            contentContainerStyle={styles.listContent}
            style={styles.list}
            keyboardShouldPersistTaps="handled"
          />
        )}

        {/* Mode bar */}
        <View style={styles.modeBar}>
          {MODE_OPTIONS.map(({ key, label }) => (
            <TouchableOpacity
              key={key}
              style={[styles.modeBtn, mode === key && styles.modeBtnActive]}
              onPress={() => setMode(key)}
              activeOpacity={0.7}
            >
              <Text
                style={[styles.modeBtnText, mode === key && styles.modeBtnTextActive]}
              >
                {label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* Model picker — shown for chat / web */}
        {(mode === "chat" || mode === "web") ? (
          <View style={styles.modelBar}>
            {MODEL_OPTIONS.map(({ key, label }) => (
              <TouchableOpacity
                key={key}
                style={[styles.modelChip, selectedModel === key && styles.modelChipActive]}
                onPress={() => toggleModel(key)}
                activeOpacity={0.7}
              >
                <Text
                  style={[
                    styles.modelChipText,
                    selectedModel === key && styles.modelChipTextActive,
                  ]}
                >
                  {label}
                </Text>
              </TouchableOpacity>
            ))}
            <Text style={styles.autoLabel}>
              {selectedModel ? "" : "авто"}
            </Text>
          </View>
        ) : null}

        {/* Pending image preview */}
        {pendingImage ? (
          <View style={styles.pendingRow}>
            <Image source={{ uri: pendingImage.uri }} style={styles.pendingThumb} />
            <TouchableOpacity onPress={() => setPendingImage(null)} style={styles.removeBtn}>
              <Ionicons name="close-circle" size={22} color={colors.textSecondary} />
            </TouchableOpacity>
          </View>
        ) : null}

        {/* Input bar */}
        <View style={styles.inputBar}>
          <TouchableOpacity onPress={pickImage} style={styles.iconBtn} activeOpacity={0.7}>
            <Ionicons name="camera-outline" size={24} color={colors.textSecondary} />
          </TouchableOpacity>

          <TextInput
            style={styles.textInput}
            placeholder={
              mode === "save"
                ? "Что сохранить..."
                : mode === "notes"
                ? "Что найти в заметках..."
                : mode === "web"
                ? "Что поискать в интернете..."
                : "Напишите сообщение..."
            }
            placeholderTextColor={colors.textHint}
            value={inputText}
            onChangeText={setInputText}
            multiline
            maxLength={2000}
          />

          <Pressable
            onPressIn={startRecording}
            onPressOut={stopRecording}
            style={[styles.iconBtn, isRecording && styles.micActive]}
          >
            <Ionicons
              name={isRecording ? "mic" : "mic-outline"}
              size={24}
              color={isRecording ? "#E05D5D" : colors.textSecondary}
            />
          </Pressable>

          <TouchableOpacity
            onPress={() => send()}
            style={[styles.sendBtn, !canSend && styles.sendBtnOff]}
            disabled={!canSend}
            activeOpacity={0.8}
          >
            {isLoading ? (
              <ActivityIndicator color={colors.onAccent} size="small" />
            ) : (
              <Ionicons name="send" size={17} color={colors.onAccent} />
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function SourcesList({ mode, sources }: { mode: Mode; sources: unknown[] }) {
  if (mode === "web") {
    return (
      <View style={styles.sources}>
        <Text style={styles.sourcesLabel}>Источники:</Text>
        {(sources as string[]).slice(0, 5).map((url, i) => (
          <Text key={i} style={styles.sourceUrl} numberOfLines={1}>
            • {typeof url === "string" ? url : JSON.stringify(url)}
          </Text>
        ))}
      </View>
    );
  }

  if (mode === "notes") {
    return (
      <View style={styles.sources}>
        <Text style={styles.sourcesLabel}>Из заметок:</Text>
        {(sources as Array<{ id: number; title?: string }>)
          .slice(0, 3)
          .map((note) => (
            <View key={note.id} style={styles.sourceNote}>
              <Text style={styles.sourceNoteText} numberOfLines={1}>
                {note.title || "Заметка"}
              </Text>
            </View>
          ))}
      </View>
    );
  }

  return null;
}

const mdStyles = {
  body: { color: colors.textPrimary, fontSize: 15, lineHeight: 22 },
  paragraph: { color: colors.textPrimary, marginBottom: 4 },
  code_block: {
    backgroundColor: colors.inputBg,
    padding: 8,
    borderRadius: borderRadius.sm,
    fontSize: 13,
  },
  code_inline: {
    backgroundColor: colors.inputBg,
    color: colors.accentHi,
    fontSize: 13,
  },
  fence: { backgroundColor: colors.inputBg, borderRadius: borderRadius.sm },
  link: { color: colors.accent },
  bullet_list: { marginBottom: 4 },
  list_item: { marginBottom: 2 },
};

const styles = StyleSheet.create({
  flex: { flex: 1 },
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
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: "700",
    letterSpacing: 1,
  },

  list: { flex: 1, backgroundColor: colors.bgChat },
  listContent: { paddingHorizontal: 12, paddingVertical: 12 },

  emptyOuter: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    backgroundColor: colors.bgChat,
  },
  emptyTitle: { color: colors.textSecondary, fontSize: 18, fontWeight: "600" },
  emptyHint: {
    color: colors.textHint,
    fontSize: 14,
    textAlign: "center",
    paddingHorizontal: spacing.lg,
    lineHeight: 20,
  },

  modeBar: {
    flexDirection: "row",
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingHorizontal: 8,
    paddingVertical: 8,
    gap: 6,
  },
  modeBtn: {
    flex: 1,
    paddingVertical: 8,
    alignItems: "center",
    borderRadius: borderRadius.md,
    backgroundColor: colors.inputBg,
  },
  modeBtnActive: { backgroundColor: colors.accent },
  modeBtnText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  modeBtnTextActive: { color: colors.onAccent },

  modelBar: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surface,
    paddingHorizontal: 12,
    paddingBottom: 8,
    gap: 8,
  },
  modelChip: {
    paddingHorizontal: 14,
    paddingVertical: 5,
    borderRadius: borderRadius.full,
    backgroundColor: colors.inputBg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  modelChipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  modelChipText: { color: colors.textHint, fontSize: 12, fontWeight: "600" },
  modelChipTextActive: { color: colors.onAccent },
  autoLabel: { color: colors.textHint, fontSize: 12, marginLeft: 4 },

  pendingRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surface,
    paddingHorizontal: 12,
    paddingBottom: 8,
    gap: 8,
  },
  pendingThumb: {
    width: 56,
    height: 56,
    borderRadius: borderRadius.md,
    backgroundColor: colors.inputBg,
  },
  removeBtn: { padding: 4 },

  inputBar: {
    flexDirection: "row",
    alignItems: "flex-end",
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingHorizontal: 8,
    paddingVertical: 8,
    gap: 6,
  },
  iconBtn: { padding: 8, borderRadius: borderRadius.md },
  micActive: { backgroundColor: "#3A1515" },
  textInput: {
    flex: 1,
    backgroundColor: colors.inputBg,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: 12,
    paddingVertical: 9,
    color: colors.textPrimary,
    fontSize: 15,
    maxHeight: 100,
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  sendBtnOff: { backgroundColor: colors.inputBg },

  rowRight: { flexDirection: "row", justifyContent: "flex-end" },
  bubble: {
    maxWidth: "85%",
    borderRadius: borderRadius.lg,
    padding: 12,
    marginBottom: 8,
    gap: 8,
  },
  bubbleUser: {
    backgroundColor: colors.accent,
    alignSelf: "flex-end",
    borderBottomRightRadius: borderRadius.sm,
    gap: 0,
  },
  bubbleAssistant: {
    backgroundColor: colors.surface,
    alignSelf: "flex-start",
    borderBottomLeftRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  userText: { color: colors.onAccent, fontSize: 15, lineHeight: 21 },

  metaRow: { flexDirection: "row", gap: 6, flexWrap: "wrap" },
  modeTag: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10 },
  modeTagText: { fontSize: 11, fontWeight: "600" },
  modelTag: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 10,
    backgroundColor: colors.inputBg,
  },
  modelTagText: { color: colors.textHint, fontSize: 11 },

  sources: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: 8,
    gap: 4,
  },
  sourcesLabel: { color: colors.textHint, fontSize: 12, fontWeight: "600" },
  sourceUrl: { color: colors.accent, fontSize: 12 },
  sourceNote: {
    backgroundColor: colors.inputBg,
    borderRadius: borderRadius.sm,
    padding: 6,
  },
  sourceNoteText: { color: colors.textSecondary, fontSize: 12 },
});
