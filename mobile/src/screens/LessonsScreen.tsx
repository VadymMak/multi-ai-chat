import React, { useState, useCallback, useEffect } from "react";
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
  Modal,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "@react-navigation/native";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as DocumentPicker from "expo-document-picker";
import { colors, spacing, borderRadius, typography } from "../theme";
import { Lesson, lessonApi } from "../lib/lessonApi";
import { lessonsCache } from "../lib/lessonsCache";
import { api } from "../lib/api";
import LessonReaderScreen from "./LessonReaderScreen";

const CATEGORY_KEY = "@lessons/category";
const SORT_KEY = "@lessons/sort";

type SortOrder = "newest" | "oldest";

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
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [sort, setSort] = useState<SortOrder>("newest");
  const [selectedLesson, setSelectedLesson] = useState<Lesson | null>(null);

  // ── Manual add modal ───────────────────────────────────────
  const [addModal, setAddModal] = useState(false);
  const [addTitle, setAddTitle] = useState("");
  const [addContent, setAddContent] = useState("");
  const [addTags, setAddTags] = useState("");
  const [addCategory, setAddCategory] = useState("");
  const [addSaving, setAddSaving] = useState(false);

  // ── Import state ───────────────────────────────────────────
  const [importing, setImporting] = useState(false);
  const [importCatModal, setImportCatModal] = useState(false);
  const [importCatValue, setImportCatValue] = useState("General");
  const [importPendingAsset, setImportPendingAsset] = useState<{
    uri: string;
    name: string;
    mimeType?: string | null;
  } | null>(null);

  // Restore persisted category and sort on mount
  useEffect(() => {
    AsyncStorage.multiGet([CATEGORY_KEY, SORT_KEY]).then((pairs) => {
      const cat = pairs[0][1];
      const s = pairs[1][1];
      if (cat !== null) setActiveCategory(cat || null);
      if (s === "oldest") setSort("oldest");
    });
  }, []);

  const allTags = Array.from(
    new Set(lessons.flatMap((l) => parseTags(l.tags)))
  ).sort();

  const allCategories = Array.from(
    new Set(lessons.map((l) => l.category).filter(Boolean) as string[])
  ).sort();

  const fetchLessons = useCallback(
    async (
      q?: string,
      tag?: string,
      category?: string | null,
      sortOrder: SortOrder = "newest"
    ) => {
      setLoading(true);
      setOffline(false);
      try {
        const { data } = await lessonApi.list({
          q: q || undefined,
          tag: tag || undefined,
          category: category || undefined,
          sort: sortOrder,
        });
        setLessons(data);
        await lessonsCache.saveList(data);
        data.forEach((l) => lessonsCache.saveBody(l.id, l.content));
      } catch {
        setOffline(true);
        let cached = await lessonsCache.loadList();
        if (q) {
          const lq = q.toLowerCase();
          cached = cached.filter(
            (l) => l.title.toLowerCase().includes(lq) || l.content.toLowerCase().includes(lq)
          );
        }
        if (tag) cached = cached.filter((l) => parseTags(l.tags).includes(tag));
        if (category) cached = cached.filter((l) => l.category === category);
        cached = [...cached].sort((a, b) => {
          if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
          const diff = new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
          return sortOrder === "oldest" ? -diff : diff;
        });
        setLessons(cached);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useFocusEffect(
    useCallback(() => {
      let active = true;
      fetchLessons(search, activeTag ?? undefined, activeCategory, sort).then(() => {
        if (!active) return;
      });
      return () => {
        active = false;
      };
    }, [fetchLessons, search, activeTag, activeCategory, sort])
  );

  // ── Category ──────────────────────────────────────────────
  const handleCategoryChange = (cat: string | null) => {
    setActiveCategory(cat);
    AsyncStorage.setItem(CATEGORY_KEY, cat ?? "");
    fetchLessons(search, activeTag ?? undefined, cat, sort);
  };

  // ── Sort ──────────────────────────────────────────────────
  const handleSortToggle = () => {
    const next: SortOrder = sort === "newest" ? "oldest" : "newest";
    setSort(next);
    AsyncStorage.setItem(SORT_KEY, next);
    fetchLessons(search, activeTag ?? undefined, activeCategory, next);
  };

  // ── Manual add ────────────────────────────────────────────
  const openAddModal = () => {
    setAddTitle("");
    setAddContent("");
    setAddTags("");
    setAddCategory("");
    setAddModal(true);
  };

  const handleManualAdd = async () => {
    if (!addTitle.trim() || !addContent.trim()) return;
    setAddSaving(true);
    try {
      await lessonApi.create({
        title: addTitle.trim(),
        content: addContent.trim(),
        tags: addTags.trim() || undefined,
        category: addCategory.trim() || undefined,
        source: "manual",
      });
      setAddModal(false);
      await lessonsCache.invalidate();
      await fetchLessons(search, activeTag ?? undefined, activeCategory, sort);
    } catch {
      Alert.alert("Ошибка", "Не удалось сохранить урок.");
    } finally {
      setAddSaving(false);
    }
  };

  // ── File import ───────────────────────────────────────────
  const handleImport = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: [
          "text/plain",
          "text/markdown",
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "application/octet-stream",
        ],
        copyToCacheDirectory: true,
      });

      if (result.canceled || !result.assets?.length) return;

      const asset = result.assets[0];
      setImportPendingAsset({ uri: asset.uri, name: asset.name, mimeType: asset.mimeType });
      setImportCatValue("General");
      setImportCatModal(true);
    } catch {
      Alert.alert("Ошибка", "Не удалось выбрать файл.");
    }
  };

  const handleImportConfirm = async () => {
    if (!importPendingAsset) return;
    const asset = importPendingAsset;
    const category = importCatValue.trim() || "General";
    setImportCatModal(false);
    setImportPendingAsset(null);
    setImporting(true);
    try {
      const formData = new FormData();
      formData.append("file", {
        uri: asset.uri,
        name: asset.name,
        type: asset.mimeType ?? "application/octet-stream",
      } as unknown as Blob);

      const { data } = await api.post<Lesson>(
        `/api/app/lessons/import?category=${encodeURIComponent(category)}`,
        formData,
        { headers: { "Content-Type": "multipart/form-data" }, timeout: 30_000 }
      );

      await lessonsCache.invalidate();
      await lessonsCache.saveBody(data.id, data.content);
      await fetchLessons(search, activeTag ?? undefined, activeCategory, sort);
      Alert.alert("Импортировано", `«${data.title}» добавлен в уроки.`);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Не удалось импортировать файл.";
      Alert.alert("Ошибка импорта", detail);
    } finally {
      setImporting(false);
    }
  };

  // ── Lesson updated from reader ────────────────────────────
  const handleLessonUpdate = useCallback((updated: Lesson) => {
    setSelectedLesson(updated);
    setLessons((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
    lessonsCache.invalidate();
  }, []);

  // ── Pin / unpin ───────────────────────────────────────────
  const handleTogglePin = async (item: Lesson) => {
    const next = !item.pinned;
    setLessons((prev) =>
      prev
        .map((l) => (l.id === item.id ? { ...l, pinned: next } : l))
        .sort((a, b) => {
          if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
          const diff = new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
          return sort === "oldest" ? -diff : diff;
        })
    );
    try {
      await lessonApi.update(item.id, { pinned: next });
      await lessonsCache.invalidate();
    } catch {
      setLessons((prev) =>
        prev.map((l) => (l.id === item.id ? { ...l, pinned: item.pinned } : l))
      );
      Alert.alert("Ошибка", "Не удалось изменить закрепление.");
    }
  };

  // ── Delete ────────────────────────────────────────────────
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
        style={[styles.card, item.pinned && styles.cardPinned]}
        activeOpacity={0.75}
        onPress={() => setSelectedLesson(item)}
        onLongPress={() => handleDelete(item.id)}
      >
        {/* Title row with pin button */}
        <View style={styles.cardTitleRow}>
          <Text style={styles.cardTitle} numberOfLines={2}>
            {item.pinned ? "📌 " : ""}{item.title}
          </Text>
          <TouchableOpacity
            onPress={() => handleTogglePin(item)}
            style={styles.pinBtn}
            hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
            activeOpacity={0.7}
          >
            <Ionicons
              name={item.pinned ? "bookmark" : "bookmark-outline"}
              size={18}
              color={item.pinned ? colors.accent : colors.textHint}
            />
          </TouchableOpacity>
        </View>

        {/* Category badge */}
        {item.category ? (
          <Text style={styles.cardCategory}>{item.category}</Text>
        ) : null}

        <Text style={styles.cardDate}>{formatDate(item.created_at)}</Text>

        {tags.length > 0 && (
          <View style={styles.tagRow}>
            {tags.map((tag) => (
              <TouchableOpacity
                key={tag}
                style={[styles.tagChip, activeTag === tag && styles.tagChipActive]}
                onPress={() => {
                  const next = activeTag === tag ? null : tag;
                  setActiveTag(next);
                  fetchLessons(search, next ?? undefined, activeCategory, sort);
                }}
                activeOpacity={0.7}
                hitSlop={{ top: 4, bottom: 4, left: 4, right: 4 }}
              >
                <Text style={[styles.tagText, activeTag === tag && styles.tagTextActive]}>
                  {tag}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        )}
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      {/* ── Header ── */}
      <View style={styles.header}>
        <Ionicons name="book-outline" size={22} color={colors.accent} />
        <Text style={styles.headerTitle}>Уроки</Text>
        {offline && (
          <View style={styles.offlineBadge}>
            <Text style={styles.offlineText}>офлайн</Text>
          </View>
        )}

        {/* Sort toggle */}
        <TouchableOpacity
          style={styles.headerBtn}
          onPress={handleSortToggle}
          activeOpacity={0.7}
        >
          <Ionicons
            name={sort === "newest" ? "arrow-down" : "arrow-up"}
            size={18}
            color={colors.textSecondary}
          />
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.headerBtn}
          onPress={() => fetchLessons(search, activeTag ?? undefined, activeCategory, sort)}
          activeOpacity={0.7}
        >
          <Ionicons name="refresh-outline" size={20} color={colors.textSecondary} />
        </TouchableOpacity>

        {/* Import file */}
        <TouchableOpacity
          style={styles.headerBtn}
          onPress={handleImport}
          disabled={importing}
          activeOpacity={0.7}
        >
          {importing ? (
            <ActivityIndicator color={colors.accent} size="small" />
          ) : (
            <Ionicons name="document-text-outline" size={20} color={colors.textSecondary} />
          )}
        </TouchableOpacity>

        {/* Manual add */}
        <TouchableOpacity
          style={[styles.headerBtn, styles.addBtn]}
          onPress={openAddModal}
          activeOpacity={0.8}
        >
          <Ionicons name="add" size={22} color={colors.onAccent} />
        </TouchableOpacity>
      </View>

      {/* ── Search ── */}
      <View style={styles.searchRow}>
        <Ionicons name="search-outline" size={16} color={colors.textHint} style={styles.searchIcon} />
        <TextInput
          style={styles.searchInput}
          placeholder="Поиск уроков..."
          placeholderTextColor={colors.textHint}
          value={search}
          onChangeText={(t) => {
            setSearch(t);
            fetchLessons(t, activeTag ?? undefined, activeCategory, sort);
          }}
          clearButtonMode="while-editing"
        />
      </View>

      {/* ── Theme / Category selector ── */}
      {allCategories.length > 0 && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.filterRow}
          contentContainerStyle={styles.filterContent}
        >
          <TouchableOpacity
            key="__cat_all__"
            style={[styles.filterChip, activeCategory === null && styles.filterChipActive]}
            onPress={() => handleCategoryChange(null)}
            activeOpacity={0.7}
          >
            <Text style={[styles.filterChipText, activeCategory === null && styles.filterChipTextActive]}>
              Все темы
            </Text>
          </TouchableOpacity>

          {allCategories.map((cat) => (
            <TouchableOpacity
              key={cat}
              style={[styles.filterChip, activeCategory === cat && styles.filterChipActive]}
              onPress={() => handleCategoryChange(activeCategory === cat ? null : cat)}
              activeOpacity={0.7}
            >
              <Text style={[styles.filterChipText, activeCategory === cat && styles.filterChipTextActive]}>
                {cat}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      )}

      {/* ── Tag filter chips ── */}
      {allTags.length > 0 && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.filterRow}
          contentContainerStyle={styles.filterContent}
        >
          <TouchableOpacity
            key="__tag_all__"
            style={[styles.filterChip, activeTag === null && styles.filterChipActive]}
            onPress={() => {
              setActiveTag(null);
              fetchLessons(search, undefined, activeCategory, sort);
            }}
            activeOpacity={0.7}
          >
            <Text style={[styles.filterChipText, activeTag === null && styles.filterChipTextActive]}>
              Все
            </Text>
          </TouchableOpacity>

          {allTags.map((tag) => (
            <TouchableOpacity
              key={tag}
              style={[styles.filterChip, activeTag === tag && styles.filterChipActive]}
              onPress={() => {
                const next = activeTag === tag ? null : tag;
                setActiveTag(next);
                fetchLessons(search, next ?? undefined, activeCategory, sort);
              }}
              activeOpacity={0.7}
            >
              <Text style={[styles.filterChipText, activeTag === tag && styles.filterChipTextActive]}>
                {tag}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      )}

      {/* ── Lessons list ── */}
      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} size="large" />
        </View>
      ) : lessons.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="book-outline" size={52} color={colors.textHint} />
          <Text style={styles.emptyTitle}>Уроков пока нет</Text>
          <Text style={styles.emptyHint}>
            Нажмите «+» чтобы добавить вручную, или значок файла чтобы импортировать .md/.txt/.docx.
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

      {/* ── Reader ── */}
      {selectedLesson && (
        <LessonReaderScreen
          lesson={selectedLesson}
          onClose={() => setSelectedLesson(null)}
          onUpdate={handleLessonUpdate}
        />
      )}

      {/* ── Import category modal ── */}
      <Modal
        visible={importCatModal}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setImportCatModal(false)}
      >
        <KeyboardAvoidingView
          style={styles.modalFlex}
          behavior={Platform.OS === "ios" ? "padding" : undefined}
        >
          <SafeAreaView style={styles.modalContainer} edges={["top", "bottom"]}>
            <View style={styles.modalHeader}>
              <TouchableOpacity
                onPress={() => { setImportCatModal(false); setImportPendingAsset(null); }}
                style={styles.headerBtn}
              >
                <Ionicons name="close" size={22} color={colors.textSecondary} />
              </TouchableOpacity>
              <Text style={styles.modalTitle}>Тема импорта</Text>
              <TouchableOpacity
                style={styles.saveBtn}
                onPress={handleImportConfirm}
                activeOpacity={0.8}
              >
                <Text style={styles.saveBtnText}>Импорт</Text>
              </TouchableOpacity>
            </View>

            <View style={{ padding: spacing.md }}>
              <Text style={styles.fieldLabel}>Тема (категория)</Text>
              <TextInput
                style={styles.fieldInput}
                value={importCatValue}
                onChangeText={setImportCatValue}
                placeholder="General, Интервью, Эзотерика..."
                placeholderTextColor={colors.textHint}
                autoCapitalize="words"
                autoFocus
                maxLength={100}
              />
              <Text style={{ color: colors.textHint, fontSize: 13, lineHeight: 18 }}>
                Файл: {importPendingAsset?.name ?? ""}
              </Text>
            </View>
          </SafeAreaView>
        </KeyboardAvoidingView>
      </Modal>

      {/* ── Manual add modal ── */}
      <Modal
        visible={addModal}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setAddModal(false)}
      >
        <KeyboardAvoidingView
          style={styles.modalFlex}
          behavior={Platform.OS === "ios" ? "padding" : undefined}
        >
          <SafeAreaView style={styles.modalContainer} edges={["top", "bottom"]}>
            <View style={styles.modalHeader}>
              <TouchableOpacity onPress={() => setAddModal(false)} style={styles.headerBtn}>
                <Ionicons name="close" size={22} color={colors.textSecondary} />
              </TouchableOpacity>
              <Text style={styles.modalTitle}>Новый урок</Text>
              <TouchableOpacity
                style={[styles.saveBtn, (!addTitle.trim() || !addContent.trim()) && styles.saveBtnOff]}
                onPress={handleManualAdd}
                disabled={!addTitle.trim() || !addContent.trim() || addSaving}
                activeOpacity={0.8}
              >
                {addSaving ? (
                  <ActivityIndicator color={colors.onAccent} size="small" />
                ) : (
                  <Text style={styles.saveBtnText}>Сохранить</Text>
                )}
              </TouchableOpacity>
            </View>

            <ScrollView style={styles.modalScroll} keyboardShouldPersistTaps="handled">
              <Text style={styles.fieldLabel}>Тема (категория)</Text>
              <TextInput
                style={styles.fieldInput}
                value={addCategory}
                onChangeText={setAddCategory}
                placeholder="Интервью, Эзотерика, General..."
                placeholderTextColor={colors.textHint}
                autoCapitalize="words"
                maxLength={100}
              />

              <Text style={styles.fieldLabel}>Название</Text>
              <TextInput
                style={styles.fieldInput}
                value={addTitle}
                onChangeText={setAddTitle}
                placeholder="Название урока..."
                placeholderTextColor={colors.textHint}
                maxLength={120}
              />

              <Text style={styles.fieldLabel}>Содержимое (Markdown)</Text>
              <TextInput
                style={[styles.fieldInput, styles.contentInput]}
                value={addContent}
                onChangeText={setAddContent}
                placeholder={"# Заголовок\n\nТекст урока..."}
                placeholderTextColor={colors.textHint}
                multiline
                textAlignVertical="top"
              />

              <Text style={styles.fieldLabel}>Теги (через запятую)</Text>
              <TextInput
                style={styles.fieldInput}
                value={addTags}
                onChangeText={setAddTags}
                placeholder="python, async, sql..."
                placeholderTextColor={colors.textHint}
                autoCapitalize="none"
                maxLength={200}
              />
            </ScrollView>
          </SafeAreaView>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },

  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
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
  headerBtn: {
    padding: 8,
    borderRadius: borderRadius.md,
    minWidth: 36,
    minHeight: 36,
    alignItems: "center",
    justifyContent: "center",
  },
  addBtn: {
    backgroundColor: colors.accent,
    width: 36,
    height: 36,
    borderRadius: 18,
  },

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
  searchInput: { flex: 1, color: colors.textPrimary, fontSize: 15 },

  filterRow: { marginTop: spacing.sm, maxHeight: 40 },
  filterContent: { paddingHorizontal: spacing.md, alignItems: "center" },
  filterChip: {
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: borderRadius.full,
    backgroundColor: colors.inputBg,
    borderWidth: 1,
    borderColor: colors.border,
    marginRight: 6,
  },
  filterChipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
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
  cardPinned: {
    borderColor: colors.accent,
    backgroundColor: "#1E1A12",
  },
  cardTitleRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
  },
  cardTitle: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: typography.body.fontSize,
    fontWeight: "600",
    lineHeight: 22,
  },
  pinBtn: {
    padding: 2,
    marginTop: 1,
  },
  cardCategory: {
    color: colors.accentHi,
    fontSize: 11,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  cardDate: { color: colors.textHint, fontSize: typography.caption.fontSize },
  tagRow: { flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 2 },
  tagChip: {
    backgroundColor: colors.inputBg,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: "transparent",
  },
  tagChipActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  tagText: { color: colors.accent, fontSize: 11, fontWeight: "600" },
  tagTextActive: { color: colors.onAccent },

  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
  },
  emptyTitle: { color: colors.textSecondary, fontSize: typography.h3.fontSize, fontWeight: "600" },
  emptyHint: { color: colors.textHint, fontSize: 14, textAlign: "center", lineHeight: 20 },

  // ── Modal ───────────────────────────────────────────────────
  modalFlex: { flex: 1 },
  modalContainer: { flex: 1, backgroundColor: colors.bg },
  modalHeader: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: spacing.sm,
  },
  modalTitle: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "600",
    textAlign: "center",
  },
  saveBtn: {
    backgroundColor: colors.accent,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: borderRadius.md,
    minWidth: 90,
    alignItems: "center",
  },
  saveBtnOff: { backgroundColor: colors.inputBg },
  saveBtnText: { color: colors.onAccent, fontSize: 14, fontWeight: "600" },

  modalScroll: { flex: 1, padding: spacing.md },
  fieldLabel: {
    color: colors.textHint,
    fontSize: 12,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: 4,
  },
  fieldInput: {
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
  contentInput: {
    minHeight: 220,
    lineHeight: 22,
    paddingTop: 12,
  },
});
