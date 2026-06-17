import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  View,
  Text,
  TextInput,
  FlatList,
  StyleSheet,
  ActivityIndicator,
  TouchableOpacity,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "../lib/api";
import { colors, spacing, borderRadius } from "../theme";

interface Note {
  id: number;
  title: string;
  body: string;
  tags: string[];
  created_at: string;
}

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

export default function NotesScreen() {
  const [query, setQuery] = useState("");
  const [notes, setNotes] = useState<Note[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchNotes = useCallback(async (q: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const qs = q.trim() ? `?query=${encodeURIComponent(q.trim())}` : "";
      const { data } = await api.get(`/api/app/notes${qs}`);
      setNotes(Array.isArray(data) ? data : []);
    } catch {
      setError("Не удалось загрузить заметки");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchNotes("");
  }, [fetchNotes]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchNotes(query), 400);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, fetchNotes]);

  const renderNote = ({ item }: { item: Note }) => (
    <View style={styles.card}>
      <Text style={styles.cardTitle} numberOfLines={1}>
        {item.title || "Без названия"}
      </Text>
      <Text style={styles.cardBody} numberOfLines={3}>
        {item.body}
      </Text>
      {item.tags?.length > 0 && (
        <View style={styles.tagsRow}>
          {item.tags.slice(0, 4).map((tag, i) => (
            <View key={i} style={styles.tag}>
              <Text style={styles.tagText}>#{tag}</Text>
            </View>
          ))}
        </View>
      )}
      <Text style={styles.cardDate}>{formatDate(item.created_at)}</Text>
    </View>
  );

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Заметки</Text>
      </View>

      <View style={styles.searchRow}>
        <Ionicons name="search-outline" size={18} color={colors.textHint} />
        <TextInput
          style={styles.searchInput}
          placeholder="Найти в заметках..."
          placeholderTextColor={colors.textHint}
          value={query}
          onChangeText={setQuery}
          returnKeyType="search"
          clearButtonMode="while-editing"
        />
        {query.length > 0 && (
          <TouchableOpacity onPress={() => setQuery("")}>
            <Ionicons name="close-circle" size={18} color={colors.textHint} />
          </TouchableOpacity>
        )}
      </View>

      {isLoading && notes.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} size="large" />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity style={styles.retryBtn} onPress={() => fetchNotes(query)}>
            <Text style={styles.retryText}>Повторить</Text>
          </TouchableOpacity>
        </View>
      ) : notes.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="bookmark-outline" size={52} color={colors.textHint} />
          <Text style={styles.emptyTitle}>
            {query ? "Ничего не найдено" : "Заметок пока нет"}
          </Text>
          <Text style={styles.emptyHint}>
            {query
              ? "Попробуйте другой запрос"
              : "Используйте режим «Сохр.» в чате, чтобы добавить заметки"}
          </Text>
        </View>
      ) : (
        <FlatList
          data={notes}
          keyExtractor={(item) => String(item.id)}
          renderItem={renderNote}
          contentContainerStyle={styles.listContent}
          ItemSeparatorComponent={() => <View style={{ height: 8 }} />}
          refreshing={isLoading}
          onRefresh={() => fetchNotes(query)}
        />
      )}
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
  searchRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.inputBg,
    borderRadius: borderRadius.md,
    marginHorizontal: spacing.md,
    marginVertical: spacing.sm,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 8,
  },
  searchInput: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: 15,
    paddingVertical: 10,
  },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 12 },
  errorText: { color: "#E05D5D", fontSize: 15 },
  retryBtn: {
    backgroundColor: colors.accent,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderRadius: borderRadius.md,
  },
  retryText: { color: colors.onAccent, fontWeight: "600" },
  emptyTitle: { color: colors.textSecondary, fontSize: 16 },
  emptyHint: {
    color: colors.textHint,
    fontSize: 13,
    textAlign: "center",
    paddingHorizontal: spacing.md,
  },
  listContent: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 6,
  },
  cardTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  cardBody: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  tagsRow: { flexDirection: "row", flexWrap: "wrap", gap: 4 },
  tag: {
    backgroundColor: colors.tagNotesBg,
    borderRadius: borderRadius.sm,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  tagText: { color: colors.tagNotes, fontSize: 11 },
  cardDate: { color: colors.textHint, fontSize: 11 },
});
