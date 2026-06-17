import React from "react";
import {
  TouchableOpacity,
  Text,
  ActivityIndicator,
  StyleSheet,
  type ViewStyle,
} from "react-native";
import { colors, spacing, borderRadius, shadows, typography } from "../../theme";

interface PrimaryButtonProps {
  label: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
  variant?: "primary" | "outline";
}

export function PrimaryButton({
  label,
  onPress,
  loading = false,
  disabled = false,
  style,
  variant = "primary",
}: PrimaryButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <TouchableOpacity
      style={[
        variant === "primary" ? styles.primary : styles.outline,
        isDisabled && styles.disabled,
        style,
      ]}
      onPress={onPress}
      disabled={isDisabled}
      activeOpacity={0.82}
    >
      {loading ? (
        <ActivityIndicator
          color={variant === "primary" ? colors.white : colors.primary}
          size="small"
        />
      ) : (
        <Text
          style={variant === "primary" ? styles.primaryText : styles.outlineText}
        >
          {label}
        </Text>
      )}
    </TouchableOpacity>
  );
}

const base = {
  borderRadius: borderRadius.full,
  paddingVertical: spacing.md,
  paddingHorizontal: spacing.lg,
  alignItems: "center" as const,
  justifyContent: "center" as const,
  minHeight: 52,
};

const styles = StyleSheet.create({
  primary: {
    ...base,
    backgroundColor: colors.primary,
    ...shadows.md,
  },
  outline: {
    ...base,
    borderWidth: 1.5,
    borderColor: colors.primary,
    backgroundColor: "transparent",
  },
  disabled: {
    opacity: 0.5,
  },
  primaryText: {
    ...typography.button,
    color: colors.white,
  },
  outlineText: {
    ...typography.button,
    color: colors.primary,
  },
});

export default PrimaryButton;
