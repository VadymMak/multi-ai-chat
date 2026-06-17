import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { colors, borderRadius, typography } from "../../theme";

interface AppLogoProps {
  size?: number;
}

export function AppLogo({ size = 80 }: AppLogoProps) {
  const fontSize = size * 0.45;
  const radius = size / 2;

  return (
    <View
      style={[
        styles.circle,
        {
          width: size,
          height: size,
          borderRadius: radius,
        },
      ]}
    >
      <Text style={[styles.letter, { fontSize }]}>M</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  circle: {
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: colors.primaryDark,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 6,
  },
  letter: {
    color: colors.white,
    fontWeight: "700",
    letterSpacing: 1,
    includeFontPadding: false,
  },
});

export default AppLogo;
