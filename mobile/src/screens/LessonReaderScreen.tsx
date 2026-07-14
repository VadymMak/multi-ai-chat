import React from "react";
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
import { colors, spacing, borderRadius, typography } from "../theme";
import { Lesson } from "../lib/lessonApi";

interface Props {
  lesson: Lesson;
  onClose: () => void;
}

export default function LessonReaderScreen({ lesson, onClose }: Props) {
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
          <TouchableOpacity onPress={handleShare} style={styles.toolbarBtn} activeOpacity={0.7}>
            <Ionicons name="share-outline" size={22} color={colors.accent} />
          </TouchableOpacity>
        </View>

        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          <Text style={styles.title}>{lesson.title}</Text>

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

const mdStyles = {
  body: { color: colors.textPrimary, fontSize: 16, lineHeight: 26 },
  paragraph: { color: colors.textPrimary, marginBottom: 8 },
  heading1: { color: colors.textPrimary, fontSize: 22, fontWeight: "700" as const, marginBottom: 8 },
  heading2: { color: colors.textPrimary, fontSize: 18, fontWeight: "600" as const, marginBottom: 6 },
  heading3: { color: colors.textSecondary, fontSize: 16, fontWeight: "600" as const },
  code_block: {
    backgroundColor: colors.inputBg,
    padding: 12,
    borderRadius: borderRadius.md,
    fontSize: 13,
    lineHeight: 20,
  },
  code_inline: {
    backgroundColor: colors.inputBg,
    color: colors.accentHi,
    fontSize: 14,
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

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },

  toolbar: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.sm,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: spacing.sm,
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

  scroll: { flex: 1 },
  scrollContent: {
    padding: spacing.md,
    paddingBottom: spacing.xxl,
  },

  title: {
    color: colors.textPrimary,
    fontSize: typography.h2.fontSize,
    fontWeight: typography.h2.fontWeight,
    lineHeight: 30,
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
