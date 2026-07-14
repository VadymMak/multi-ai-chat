import React, { useState, useCallback } from "react";
import {
  View,
  Text,
  TextInput,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "@react-navigation/native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, borderRadius, typography } from "../theme";
import { Lesson, lessonApi } from "../lib/lessonApi";
import { lessonsCache } from "../lib/lessonsCache";
import LessonReaderScreen from "./LessonReaderScreen";

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("ru-RU", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return "";
  }
}

function parseTags(csv: string | null): string[] {
  if (!csv) return [];
  return csv
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

export default function LessonsScreen() {
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [loading, setLoading] = useState(false);
  const [offline, setOffline] = useState(false);
  const [search, setSearch] = useState("");
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [selectedLesson, setSelectedLesson] = useState<Lesson | null>(null);

  // Collect all unique tags across loaded lessons for filter chips
  const allTags = Array.from(
    new Set(lessons.flatMap((l) => parseTags(l.tags)))
  ).sort();

  const fetchLessons = useCallback(async (q?: string, tag?: string) => {
    setLoading(true);
    setOffline(false);
    try {
      const { data } = await lessonApi.list({ q: q || undefined, tag: tag || undefined });
      setLessons(data);
      await lessonsCache.saveList(data);
      // Pre-cache bodies for offline reading
      data.forEach((l) => lessonsCache.saveBody(l.id, l.content));
    } catch {
      setOffline(true);
      const cached = await lessonsCache.loadList();
      let filtered = cached;
      if (q) {
        const lq = q.toLowerCase();
        filtered = filtered.filter(
          (l) =>
            l.title.toLowerCase().includes(lq) ||
            l.content.toLowerCase().includes(lq)
        );
      }
      if (tag) {
        filtered = filtered.filter((l) =>
          parseTags(l.tags).includes(tag)
        );
      }
      setLessons(filtered);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      fetchLessons(search, activeTag ?? undefined).then(() => {
        if (!active) return;
      });
      return () => {
        active = false;
      };
    }, [fetchLessons, search, activeTag])
  );

  const handleDelete = (id: number) => {
    Alert.alert("Удалить урок?", "Это действие необратимо.", [
      { text: "Отмена", style: "cancel" },
      {
        text: "Удалить",
        style: "destructive",
        onPress: async () => {
          try {
            await lessonApi.remove(id);
            await lessonsCache.invalidate();
            setLessons((prev) => prev.filter((l) => l.id !== id));
          } catch {
            Alert.alert("Ошибка", "Не удалось удалить урок.");
          }
        },
      },
    ]);
  };

  const renderItem = ({ item }: { item: Lesson }) => {
    const tags = parseTags(item.tags);
    return (
      <TouchableOpacity
        style={styles.card}
        activeOpacity={0.75}
        onPress={() => setSelectedLesson(item)}
        onLongPress={() => handleDelete(item.id)}
      >
        <Text style={styles.cardTitle} numberOfLines={2}>
          {item.title}
        </Text>
        <Text style={styles.cardDate}>{formatDate(item.created_at)}</Text>
        {tags.length > 0 && (
          <View style={styles.tagRow}>
            {tags.map((tag) => (
              <View key={tag} style={styles.tagChip}>
                <Text style={styles.tagText}>{tag}</Text>
              </View>
            ))}
          </View>
        )}
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      {/* Header */}
      <View style={styles.header}>
        <Ionicons name="book-outline" size={22} color={colors.accent} />
        <Text style={styles.headerTitle}>Уроки</Text>
        {offline && (
          <View style={styles.offlineBadge}>
            <Text style={styles.offlineText}>офлайн</Text>
          </View>
        )}
        <TouchableOpacity
          style={styles.refreshBtn}
          onPress={() => fetchLessons(search, activeTag ?? undefined)}
          activeOpacity={0.7}
        >
          <Ionicons name="refresh-outline" size={20} color={colors.textSecondary} />
        </TouchableOpacity>
      </View>

      {/* Search */}
      <View style={styles.searchRow}>
        <Ionicons name="search-outline" size={16} color={colors.textHint} style={styles.searchIcon} />
        <TextInput
          style={styles.searchInput}
          placeholder="Поиск уроков..."
          placeholderTextColor={colors.textHint}
          value={search}
          onChangeText={(t) => {
            setSearch(t);
            fetchLessons(t, activeTag ?? undefined);
          }}
          clearButtonMode="while-editing"
        />
      </View>

      {/* Tag filter chips */}
      {allTags.length > 0 && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.tagFilterRow}
          contentContainerStyle={styles.tagFilterContent}
        >
          {allTags.map((tag) => (
            <TouchableOpacity
              key={tag}
              style={[styles.filterChip, activeTag === tag && styles.filterChipActive]}
              onPress={() => {
                const next = activeTag === tag ? null : tag;
                setActiveTag(next);
                fetchLessons(search, next ?? undefined);
              }}
              activeOpacity={0.7}
            >
              <Text
                style={[styles.filterChipText, activeTag === tag && styles.filterChipTextActive]}
              >
                {tag}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      )}

      {/* List */}
      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} size="large" />
        </View>
      ) : lessons.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="book-outline" size={52} color={colors.textHint} />
          <Text style={styles.emptyTitle}>Уроков пока нет</Text>
          <Text style={styles.emptyHint}>
            Долгий тап на ответ AI в чате → «Сохранить как урок»
          </Text>
        </View>
      ) : (
        <FlatList
          data={lessons}
          keyExtractor={(item) => String(item.id)}
          renderItem={renderItem}
          contentContainerStyle={styles.listContent}
        />
      )}

      {/* Reader modal */}
      {selectedLesson && (
        <LessonReaderScreen
          lesson={selectedLesson}
          onClose={() => setSelectedLesson(null)}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },

  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerTitle: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: typography.h3.fontSize,
    fontWeight: typography.h3.fontWeight,
    letterSpacing: 1,
  },
  offlineBadge: {
    backgroundColor: "#3A2010",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  offlineText: { color: colors.accent, fontSize: 11, fontWeight: "600" },
  refreshBtn: { padding: 4 },

  searchRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.inputBg,
    marginHorizontal: spacing.md,
    marginTop: spacing.sm,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.sm,
    height: 44,
  },
  searchIcon: { marginRight: 6 },
  searchInput: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: 15,
  },

  tagFilterRow: {
    marginTop: spacing.sm,
    maxHeight: 40,
  },
  tagFilterContent: {
    paddingHorizontal: spacing.md,
    gap: spacing.xs,
    alignItems: "center",
  },
  filterChip: {
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: borderRadius.full,
    backgroundColor: colors.inputBg,
    borderWidth: 1,
    borderColor: colors.border,
    marginRight: 6,
  },
  filterChipActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  filterChipText: { color: colors.textSecondary, fontSize: 12, fontWeight: "600" },
  filterChipTextActive: { color: colors.onAccent },

  listContent: { padding: spacing.md, gap: spacing.sm },

  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: spacing.xs,
    minHeight: 72,
  },
  cardTitle: {
    color: colors.textPrimary,
    fontSize: typography.body.fontSize,
    fontWeight: "600",
    lineHeight: 22,
  },
  cardDate: {
    color: colors.textHint,
    fontSize: typography.caption.fontSize,
  },
  tagRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 4,
    marginTop: 2,
  },
  tagChip: {
    backgroundColor: colors.inputBg,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  tagText: { color: colors.accent, fontSize: 11, fontWeight: "600" },

  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
  },
  emptyTitle: {
    color: colors.textSecondary,
    fontSize: typography.h3.fontSize,
    fontWeight: "600",
  },
  emptyHint: {
    color: colors.textHint,
    fontSize: 14,
    textAlign: "center",
    lineHeight: 20,
  },
});
