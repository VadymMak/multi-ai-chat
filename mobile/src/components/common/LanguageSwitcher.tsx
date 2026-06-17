import React from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import { useLanguageContext } from "../../context/LanguageContext";
import { SUPPORTED_LANGUAGES, type SupportedLanguage } from "../../lib/constants";
import { colors, spacing, borderRadius, typography } from "../../theme";

const LABELS: Record<SupportedLanguage, string> = {
  ru: "RU",
  en: "EN",
};

export function LanguageSwitcher() {
  const { language, setLanguage } = useLanguageContext();

  return (
    <View style={styles.row}>
      {SUPPORTED_LANGUAGES.map((lang) => {
        const active = language === lang;
        return (
          <TouchableOpacity
            key={lang}
            style={[styles.pill, active && styles.pillActive]}
            onPress={() => setLanguage(lang)}
            activeOpacity={0.75}
          >
            <Text style={[styles.pillText, active && styles.pillTextActive]}>
              {LABELS[lang]}
            </Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  pill: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: borderRadius.full,
    borderWidth: 1.5,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  pillActive: {
    borderColor: colors.primary,
    backgroundColor: colors.primary,
  },
  pillText: {
    ...typography.buttonSmall,
    color: colors.textSecondary,
    letterSpacing: 0.5,
  },
  pillTextActive: {
    color: colors.white,
  },
});

export default LanguageSwitcher;
