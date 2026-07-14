import React, { useState, useEffect } from "react";
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Share,
  Modal,
  ScrollView,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import Markdown from "react-native-markdown-display";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { colors, spacing, borderRadius, typography } from "../theme";
import { Lesson } from "../lib/lessonApi";

const FONT_SCALE_KEY = "@lessons/font_scale";
const FONT_SCALE_MIN = 0.85;
const FONT_SCALE_MAX = 1.6;
const FONT_SCALE_STEP = 0.1;
const FONT_SCALE_DEFAULT = 1.0;

interface Props {
  lesson: Lesson;
  onClose: () => void;
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

export default function LessonReaderScreen({ lesson, onClose }: Props) {
  const [fontScale, setFontScale] = useState(FONT_SCALE_DEFAULT);

  useEffect(() => {
    AsyncStorage.getItem(FONT_SCALE_KEY).then((val) => {
      if (val) {
        const n = parseFloat(val);
        if (!isNaN(n)) setFontScale(n);
      }
    });
  }, []);

  const changeFontScale = (delta: number) => {
    setFontScale((prev) => {
      const next = Math.min(FONT_SCALE_MAX, Math.max(FONT_SCALE_MIN, parseFloat((prev + delta).toFixed(2))));
      AsyncStorage.setItem(FONT_SCALE_KEY, String(next));
      return next;
    });
  };

  const handleShare = async () => {
    try {
      await Share.share({
        message: `${lesson.title}\n\n${lesson.content}`,
        title: lesson.title,
      });
    } catch {
      Alert.alert("Ошибка", "Не удалось открыть шаринг.");
    }
  };

  const mdStyles = buildMdStyles(fontScale);
  const canDecrease = fontScale > FONT_SCALE_MIN + 0.001;
  const canIncrease = fontScale < FONT_SCALE_MAX - 0.001;

  return (
    <Modal
      visible
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
        {/* Toolbar */}
        <View style={styles.toolbar}>
          <TouchableOpacity onPress={onClose} style={styles.toolbarBtn} activeOpacity={0.7}>
            <Ionicons name="chevron-down" size={24} color={colors.textSecondary} />
          </TouchableOpacity>

          <Text style={styles.toolbarTitle} numberOfLines={1}>
            {lesson.title}
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

          <TouchableOpacity onPress={handleShare} style={styles.toolbarBtn} activeOpacity={0.7}>
            <Ionicons name="share-outline" size={22} color={colors.accent} />
          </TouchableOpacity>
        </View>

        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          <Text style={[styles.title, { fontSize: Math.round(22 * fontScale), lineHeight: Math.round(30 * fontScale) }]}>
            {lesson.title}
          </Text>

          {lesson.tags && (
            <View style={styles.tagRow}>
              {lesson.tags
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

          <Markdown style={mdStyles}>{lesson.content}</Markdown>
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },

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
});
