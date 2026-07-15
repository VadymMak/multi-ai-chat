import React, { useState, useEffect, useRef } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Share,
  Modal,
  ScrollView,
  Alert,
  Platform,
  KeyboardAvoidingView,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import Markdown from "react-native-markdown-display";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Speech from "expo-speech";
import { colors, spacing, borderRadius, typography } from "../theme";
import { Lesson, lessonApi } from "../lib/lessonApi";
import {
  stripMarkdownToSpeakable,
  stripTtsMarkers,
  detectTtsLanguage,
  hasTtsMarkers,
  extractSpeakable,
  splitForTts,
} from "../lib/ttsText";

const FONT_SCALE_KEY = "@lessons/font_scale";
const TTS_RATE_KEY = "@lessons/tts_rate";
const TTS_SELECTIVE_KEY = "@lessons/tts_selective";
const FONT_SCALE_MIN = 0.85;
const FONT_SCALE_MAX = 1.6;
const FONT_SCALE_STEP = 0.1;
const FONT_SCALE_DEFAULT = 1.0;
const TTS_RATES = [0.75, 1.0, 1.25, 1.5] as const;
type TtsRate = (typeof TTS_RATES)[number];
type TtsState = "idle" | "speaking" | "paused";

interface Props {
  lesson: Lesson;
  onClose: () => void;
  onUpdate?: (updated: Lesson) => void;
}

function buildMdStyles(scale: number) {
  const base = 16 * scale;
  const lh = (size: number) => Math.round(size * 1.65);
  return {
    body: { color: colors.textPrimary, fontSize: base, lineHeight: lh(base) },
    paragraph: { color: colors.textPrimary, marginBottom: 10 },
    heading1: {
      color: colors.textPrimary,
      fontSize: Math.round(22 * scale),
      fontWeight: "700" as const,
      lineHeight: lh(22 * scale),
      marginTop: 8,
      marginBottom: 6,
    },
    heading2: {
      color: colors.textPrimary,
      fontSize: Math.round(18 * scale),
      fontWeight: "600" as const,
      lineHeight: lh(18 * scale),
      marginTop: 6,
      marginBottom: 4,
    },
    heading3: {
      color: colors.textSecondary,
      fontSize: Math.round(16 * scale),
      fontWeight: "600" as const,
      lineHeight: lh(16 * scale),
      marginBottom: 4,
    },
    code_block: {
      backgroundColor: colors.inputBg,
      padding: 12,
      borderRadius: borderRadius.md,
      fontSize: Math.round(13 * scale),
      lineHeight: lh(13 * scale),
    },
    code_inline: {
      backgroundColor: colors.inputBg,
      color: colors.accentHi,
      fontSize: Math.round(14 * scale),
      paddingHorizontal: 4,
    },
    fence: { backgroundColor: colors.inputBg, borderRadius: borderRadius.md },
    link: { color: colors.accent },
    blockquote: {
      borderLeftWidth: 3,
      borderLeftColor: colors.accent,
      paddingLeft: 12,
      opacity: 0.85,
    },
    bullet_list: { marginBottom: 8 },
    list_item: { marginBottom: 4 },
    strong: { fontWeight: "700" as const, color: colors.textPrimary },
    em: { fontStyle: "italic" as const },
  };
}

export default function LessonReaderScreen({ lesson, onClose, onUpdate }: Props) {
  const [currentLesson, setCurrentLesson] = useState<Lesson>(lesson);
  const [fontScale, setFontScale] = useState(FONT_SCALE_DEFAULT);
  const [ttsState, setTtsState] = useState<TtsState>("idle");
  const [ttsRate, setTtsRate] = useState<TtsRate>(1.0);
  const [ttsSelective, setTtsSelective] = useState(true);

  // Edit modal state
  const [editModal, setEditModal] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editTags, setEditTags] = useState("");
  const [editCategory, setEditCategory] = useState("");
  const [editSaving, setEditSaving] = useState(false);

  const hasMarkers = hasTtsMarkers(currentLesson.content);

  // Chunk-based playback refs (survive re-renders without stale closures)
  const chunksRef = useRef<string[]>([]);
  const chunkIdxRef = useRef(0);
  const stoppedByUserRef = useRef(false);

  useEffect(() => {
    AsyncStorage.multiGet([FONT_SCALE_KEY, TTS_RATE_KEY, TTS_SELECTIVE_KEY]).then((pairs) => {
      const fontVal = pairs[0][1];
      const rateVal = pairs[1][1];
      const selectVal = pairs[2][1];
      if (fontVal) {
        const n = parseFloat(fontVal);
        if (!isNaN(n)) setFontScale(n);
      }
      if (rateVal) {
        const r = parseFloat(rateVal) as TtsRate;
        if ((TTS_RATES as readonly number[]).includes(r)) setTtsRate(r);
      }
      if (selectVal !== null) setTtsSelective(selectVal !== "false");
    });
  }, []);

  useEffect(() => {
    return () => {
      stoppedByUserRef.current = true;
      Speech.stop();
    };
  }, []);

  // ── Font scale ───────────────────────────────────────────────

  const changeFontScale = (delta: number) => {
    setFontScale((prev) => {
      const next = Math.min(
        FONT_SCALE_MAX,
        Math.max(FONT_SCALE_MIN, parseFloat((prev + delta).toFixed(2)))
      );
      AsyncStorage.setItem(FONT_SCALE_KEY, String(next));
      return next;
    });
  };

  // ── Share ────────────────────────────────────────────────────

  const handleShare = async () => {
    try {
      await Share.share({
        message: `${currentLesson.title}\n\n${stripTtsMarkers(currentLesson.content)}`,
        title: currentLesson.title,
      });
    } catch {
      Alert.alert("Ошибка", "Не удалось открыть шаринг.");
    }
  };

  // ── Close ────────────────────────────────────────────────────

  const handleClose = () => {
    stoppedByUserRef.current = true;
    Speech.stop();
    onClose();
  };

  // ── Edit ─────────────────────────────────────────────────────

  const openEdit = () => {
    setEditTitle(currentLesson.title);
    setEditContent(currentLesson.content);
    setEditTags(currentLesson.tags ?? "");
    setEditCategory(currentLesson.category ?? "");
    setEditModal(true);
  };

  const handleSaveEdit = async () => {
    if (!editTitle.trim() || !editContent.trim()) return;
    setEditSaving(true);
    try {
      // Stop TTS if running while editing
      if (ttsState !== "idle") {
        stoppedByUserRef.current = true;
        Speech.stop();
        chunksRef.current = [];
        chunkIdxRef.current = 0;
        setTtsState("idle");
      }
      const { data } = await lessonApi.update(currentLesson.id, {
        title: editTitle.trim(),
        content: editContent.trim(),
        tags: editTags.trim() || undefined,
        category: editCategory.trim() || undefined,
      });
      setCurrentLesson(data);
      setEditModal(false);
      onUpdate?.(data);
    } catch {
      Alert.alert("Ошибка", "Не удалось сохранить изменения.");
    } finally {
      setEditSaving(false);
    }
  };

  // ── TTS ──────────────────────────────────────────────────────

  const speakChunk = (idx: number, rate: TtsRate, language: string) => {
    const chunks = chunksRef.current;
    if (idx >= chunks.length) {
      setTtsState("idle");
      chunkIdxRef.current = 0;
      return;
    }
    chunkIdxRef.current = idx;
    Speech.speak(chunks[idx], {
      language,
      rate,
      onStart: () => setTtsState("speaking"),
      onDone: () => {
        if (!stoppedByUserRef.current) {
          speakChunk(idx + 1, rate, language);
        }
      },
      onStopped: () => {
        if (!stoppedByUserRef.current) {
          setTtsState("idle");
          chunkIdxRef.current = 0;
        }
        stoppedByUserRef.current = false;
      },
      onError: () => {
        setTtsState("idle");
        chunkIdxRef.current = 0;
        stoppedByUserRef.current = false;
      },
    });
  };

  const buildCleanText = (selective: boolean) =>
    selective && hasMarkers
      ? extractSpeakable(currentLesson.content)
      : stripMarkdownToSpeakable(currentLesson.content);

  const startSpeaking = (rate: TtsRate, selective = ttsSelective) => {
    const cleanText = buildCleanText(selective);
    const language = detectTtsLanguage(cleanText);
    chunksRef.current = splitForTts(cleanText);
    chunkIdxRef.current = 0;
    stoppedByUserRef.current = false;
    setTtsState("speaking");
    speakChunk(0, rate, language);
  };

  const handlePlayPause = () => {
    if (ttsState === "idle") {
      startSpeaking(ttsRate);
    } else if (ttsState === "speaking") {
      if (Platform.OS === "ios") {
        Speech.pause();
        setTtsState("paused");
      } else {
        stoppedByUserRef.current = true;
        Speech.stop();
        setTtsState("paused");
      }
    } else {
      if (Platform.OS === "ios") {
        Speech.resume();
      } else {
        const cleanText = buildCleanText(ttsSelective);
        const language = detectTtsLanguage(cleanText);
        stoppedByUserRef.current = false;
        speakChunk(chunkIdxRef.current, ttsRate, language);
      }
      setTtsState("speaking");
    }
  };

  const handleStop = () => {
    stoppedByUserRef.current = true;
    Speech.stop();
    chunkIdxRef.current = 0;
    chunksRef.current = [];
    setTtsState("idle");
  };

  const handleRateChange = (rate: TtsRate) => {
    setTtsRate(rate);
    AsyncStorage.setItem(TTS_RATE_KEY, String(rate));
    if (ttsState === "speaking") {
      stoppedByUserRef.current = true;
      Speech.stop();
      setTimeout(() => startSpeaking(rate), 120);
    }
  };

  const handleSelectiveToggle = (value: boolean) => {
    setTtsSelective(value);
    AsyncStorage.setItem(TTS_SELECTIVE_KEY, String(value));
    if (ttsState === "speaking") {
      stoppedByUserRef.current = true;
      Speech.stop();
      setTimeout(() => startSpeaking(ttsRate, value), 120);
    }
  };

  // ── Derived state ────────────────────────────────────────────

  const mdStyles = buildMdStyles(fontScale);
  const canDecrease = fontScale > FONT_SCALE_MIN + 0.001;
  const canIncrease = fontScale < FONT_SCALE_MAX - 0.001;
  const isStopped = ttsState === "idle";

  return (
    <Modal
      visible
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={handleClose}
    >
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        {/* ── Toolbar ── */}
        <View style={styles.toolbar}>
          <TouchableOpacity onPress={handleClose} style={styles.toolbarBtn} activeOpacity={0.7}>
            <Ionicons name="chevron-down" size={24} color={colors.textSecondary} />
          </TouchableOpacity>

          <Text style={styles.toolbarTitle} numberOfLines={1}>
            {currentLesson.title}
          </Text>

          {/* A- / A+ font size stepper */}
          <View style={styles.fontStepper}>
            <TouchableOpacity
              onPress={() => changeFontScale(-FONT_SCALE_STEP)}
              disabled={!canDecrease}
              style={[styles.fontBtn, !canDecrease && styles.fontBtnOff]}
              activeOpacity={0.7}
              hitSlop={{ top: 8, bottom: 8, left: 4, right: 4 }}
            >
              <Text style={[styles.fontBtnText, !canDecrease && styles.fontBtnTextOff]}>A-</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => changeFontScale(FONT_SCALE_STEP)}
              disabled={!canIncrease}
              style={[styles.fontBtn, !canIncrease && styles.fontBtnOff]}
              activeOpacity={0.7}
              hitSlop={{ top: 8, bottom: 8, left: 4, right: 4 }}
            >
              <Text style={[styles.fontBtnText, !canIncrease && styles.fontBtnTextOff]}>A+</Text>
            </TouchableOpacity>
          </View>

          {/* Edit */}
          <TouchableOpacity onPress={openEdit} style={styles.toolbarBtn} activeOpacity={0.7}>
            <Ionicons name="pencil-outline" size={20} color={colors.textSecondary} />
          </TouchableOpacity>

          {/* Share */}
          <TouchableOpacity onPress={handleShare} style={styles.toolbarBtn} activeOpacity={0.7}>
            <Ionicons name="share-outline" size={22} color={colors.accent} />
          </TouchableOpacity>
        </View>

        {/* ── Content ── */}
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          <Text
            style={[
              styles.title,
              { fontSize: Math.round(22 * fontScale), lineHeight: Math.round(30 * fontScale) },
            ]}
          >
            {currentLesson.title}
          </Text>

          {currentLesson.tags && (
            <View style={styles.tagRow}>
              {currentLesson.tags
                .split(",")
                .map((t) => t.trim())
                .filter(Boolean)
                .map((tag) => (
                  <View key={tag} style={styles.tagChip}>
                    <Text style={styles.tagText}>{tag}</Text>
                  </View>
                ))}
            </View>
          )}

          <Markdown style={mdStyles}>{stripTtsMarkers(currentLesson.content)}</Markdown>
        </ScrollView>

        {/* ── TTS Bar ── */}
        <View style={styles.ttsBar}>
          {hasMarkers && (
            <View style={styles.ttsSelectRow}>
              <Text style={styles.ttsSelectLabel}>Читать:</Text>
              <View style={styles.selectChips}>
                <TouchableOpacity
                  onPress={() => handleSelectiveToggle(true)}
                  style={[styles.selectChip, ttsSelective && styles.selectChipActive]}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.selectChipText, ttsSelective && styles.selectChipTextActive]}>
                    Ключевое
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => handleSelectiveToggle(false)}
                  style={[styles.selectChip, !ttsSelective && styles.selectChipActive]}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.selectChipText, !ttsSelective && styles.selectChipTextActive]}>
                    Весь текст
                  </Text>
                </TouchableOpacity>
              </View>
            </View>
          )}

          <View style={styles.ttsMainRow}>
            <View style={styles.ttsControls}>
              <TouchableOpacity
                onPress={handleStop}
                disabled={isStopped}
                style={[styles.ttsIconBtn, isStopped && styles.ttsBtnDisabled]}
                activeOpacity={0.7}
                hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              >
                <Ionicons
                  name="stop"
                  size={18}
                  color={isStopped ? colors.textHint : colors.textSecondary}
                />
              </TouchableOpacity>

              <TouchableOpacity
                onPress={handlePlayPause}
                style={styles.ttsPlayBtn}
                activeOpacity={0.7}
              >
                <Ionicons
                  name={ttsState === "speaking" ? "pause" : "play"}
                  size={22}
                  color={colors.onAccent}
                />
              </TouchableOpacity>
            </View>

            <View style={styles.rateRow}>
              {TTS_RATES.map((r) => (
                <TouchableOpacity
                  key={r}
                  onPress={() => handleRateChange(r)}
                  style={[styles.rateChip, ttsRate === r && styles.rateChipActive]}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.rateText, ttsRate === r && styles.rateTextActive]}>
                    {r}×
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        </View>
      </SafeAreaView>

      {/* ── Edit Modal ── */}
      <Modal
        visible={editModal}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => !editSaving && setEditModal(false)}
      >
        <KeyboardAvoidingView
          style={styles.editFlex}
          behavior={Platform.OS === "ios" ? "padding" : undefined}
        >
          <SafeAreaView style={styles.editContainer} edges={["top", "bottom"]}>
            <View style={styles.editHeader}>
              <TouchableOpacity
                onPress={() => setEditModal(false)}
                style={styles.editHeaderBtn}
                disabled={editSaving}
              >
                <Ionicons name="close" size={22} color={colors.textSecondary} />
              </TouchableOpacity>
              <Text style={styles.editHeaderTitle}>Редактировать</Text>
              <TouchableOpacity
                style={[
                  styles.editSaveBtn,
                  (!editTitle.trim() || !editContent.trim()) && styles.editSaveBtnOff,
                ]}
                onPress={handleSaveEdit}
                disabled={!editTitle.trim() || !editContent.trim() || editSaving}
                activeOpacity={0.8}
              >
                {editSaving ? (
                  <ActivityIndicator color={colors.onAccent} size="small" />
                ) : (
                  <Text style={styles.editSaveBtnText}>Сохранить</Text>
                )}
              </TouchableOpacity>
            </View>

            <ScrollView style={styles.editScroll} keyboardShouldPersistTaps="handled">
              <Text style={styles.editFieldLabel}>Тема (категория)</Text>
              <TextInput
                style={styles.editFieldInput}
                value={editCategory}
                onChangeText={setEditCategory}
                placeholder="Интервью, Эзотерика, General..."
                placeholderTextColor={colors.textHint}
                autoCapitalize="words"
                maxLength={100}
              />

              <Text style={styles.editFieldLabel}>Название</Text>
              <TextInput
                style={styles.editFieldInput}
                value={editTitle}
                onChangeText={setEditTitle}
                placeholder="Название урока..."
                placeholderTextColor={colors.textHint}
                maxLength={120}
              />

              <Text style={styles.editFieldLabel}>Содержимое (Markdown)</Text>
              <TextInput
                style={[styles.editFieldInput, styles.editContentInput]}
                value={editContent}
                onChangeText={setEditContent}
                placeholder={"# Заголовок\n\nТекст урока..."}
                placeholderTextColor={colors.textHint}
                multiline
                textAlignVertical="top"
              />

              <Text style={styles.editFieldLabel}>Теги (через запятую)</Text>
              <TextInput
                style={styles.editFieldInput}
                value={editTags}
                onChangeText={setEditTags}
                placeholder="python, async, sql..."
                placeholderTextColor={colors.textHint}
                autoCapitalize="none"
                maxLength={200}
              />
            </ScrollView>
          </SafeAreaView>
        </KeyboardAvoidingView>
      </Modal>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },

  // ── Toolbar ──
  toolbar: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.xs,
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: 4,
  },
  toolbarBtn: {
    padding: spacing.sm,
    borderRadius: borderRadius.md,
    minWidth: 44,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  toolbarTitle: {
    flex: 1,
    color: colors.textSecondary,
    fontSize: typography.bodySmall.fontSize,
    textAlign: "center",
  },
  fontStepper: {
    flexDirection: "row",
    alignItems: "center",
    gap: 2,
    backgroundColor: colors.inputBg,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  fontBtn: {
    paddingHorizontal: 10,
    paddingVertical: 8,
    minWidth: 38,
    alignItems: "center",
    justifyContent: "center",
  },
  fontBtnOff: { opacity: 0.3 },
  fontBtnText: {
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: "700",
    letterSpacing: -0.5,
  },
  fontBtnTextOff: { color: colors.textHint },

  // ── Content ──
  scroll: { flex: 1 },
  scrollContent: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xxl,
  },
  title: {
    color: colors.textPrimary,
    fontWeight: typography.h2.fontWeight,
    marginBottom: spacing.sm,
  },
  tagRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    marginBottom: spacing.md,
  },
  tagChip: {
    backgroundColor: colors.inputBg,
    borderRadius: borderRadius.sm,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  tagText: { color: colors.accent, fontSize: 12, fontWeight: "600" },

  // ── TTS Bar ──
  ttsBar: {
    flexDirection: "column",
    paddingHorizontal: spacing.md,
    paddingTop: 8,
    paddingBottom: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.surface,
    gap: 6,
  },
  ttsSelectRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  ttsSelectLabel: {
    color: colors.textHint,
    fontSize: 11,
    fontWeight: "500",
  },
  selectChips: {
    flexDirection: "row",
    backgroundColor: colors.inputBg,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
    padding: 2,
    gap: 2,
  },
  selectChip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: borderRadius.sm - 2,
    alignItems: "center",
  },
  selectChipActive: { backgroundColor: colors.accent },
  selectChipText: {
    color: colors.textSecondary,
    fontSize: 12,
    fontWeight: "600",
  },
  selectChipTextActive: { color: colors.onAccent },
  ttsMainRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  ttsControls: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  ttsIconBtn: {
    width: 36,
    height: 36,
    borderRadius: borderRadius.full,
    backgroundColor: colors.inputBg,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  ttsBtnDisabled: { opacity: 0.4 },
  ttsPlayBtn: {
    width: 44,
    height: 44,
    borderRadius: borderRadius.full,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  rateRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 2,
    backgroundColor: colors.inputBg,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
    padding: 2,
  },
  rateChip: {
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: borderRadius.sm - 2,
    minWidth: 42,
    alignItems: "center",
  },
  rateChipActive: { backgroundColor: colors.accent },
  rateText: {
    color: colors.textSecondary,
    fontSize: 12,
    fontWeight: "600",
  },
  rateTextActive: { color: colors.onAccent },

  // ── Edit Modal ──
  editFlex: { flex: 1 },
  editContainer: { flex: 1, backgroundColor: colors.bg },
  editHeader: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: spacing.sm,
  },
  editHeaderBtn: {
    padding: 8,
    borderRadius: borderRadius.md,
    minWidth: 36,
    minHeight: 36,
    alignItems: "center",
    justifyContent: "center",
  },
  editHeaderTitle: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "600",
    textAlign: "center",
  },
  editSaveBtn: {
    backgroundColor: colors.accent,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: borderRadius.md,
    minWidth: 90,
    alignItems: "center",
  },
  editSaveBtnOff: { backgroundColor: colors.inputBg },
  editSaveBtnText: { color: colors.onAccent, fontSize: 14, fontWeight: "600" },
  editScroll: { flex: 1, padding: spacing.md },
  editFieldLabel: {
    color: colors.textHint,
    fontSize: 12,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: 4,
  },
  editFieldInput: {
    backgroundColor: colors.inputBg,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    color: colors.textPrimary,
    fontSize: 15,
    marginBottom: spacing.md,
  },
  editContentInput: {
    minHeight: 220,
    lineHeight: 22,
    paddingTop: 12,
  },
});
