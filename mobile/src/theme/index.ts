import type { TextStyle } from "react-native";

export const colors = {
  primary: "#6B46C1",
  primaryLight: "#9F7AEA",
  primaryDark: "#553C9A",
  secondary: "#D53F8C",
  sos: "#C53030",
  sosLight: "#FED7D7",
  success: "#38A169",
  warning: "#D69E2E",
  error: "#E53E3E",
  background: "#F7F7F7",
  surface: "#FFFFFF",
  surfaceSecondary: "#F0F0F0",
  textPrimary: "#1A1A1A",
  textSecondary: "#666666",
  textHint: "#999999",
  border: "#E0E0E0",
  borderFocus: "#6B46C1",
  overlay: "rgba(0,0,0,0.5)",
  white: "#FFFFFF",
  black: "#000000",
} as const;

export const typography = {
  h1: { fontSize: 28, fontWeight: "700" as TextStyle["fontWeight"] },
  h2: { fontSize: 22, fontWeight: "600" as TextStyle["fontWeight"] },
  h3: { fontSize: 18, fontWeight: "600" as TextStyle["fontWeight"] },
  body: { fontSize: 16, fontWeight: "400" as TextStyle["fontWeight"] },
  bodySmall: { fontSize: 14, fontWeight: "400" as TextStyle["fontWeight"] },
  caption: { fontSize: 12, fontWeight: "400" as TextStyle["fontWeight"] },
  button: { fontSize: 16, fontWeight: "600" as TextStyle["fontWeight"] },
  buttonSmall: { fontSize: 14, fontWeight: "500" as TextStyle["fontWeight"] },
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
} as const;

export const borderRadius = {
  sm: 6,
  md: 12,
  lg: 20,
  xl: 30,
  full: 9999,
} as const;

export const shadows = {
  sm: {
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 2,
    elevation: 2,
  },
  md: {
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.12,
    shadowRadius: 4,
    elevation: 4,
  },
  lg: {
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.16,
    shadowRadius: 8,
    elevation: 8,
  },
} as const;

export const theme = { colors, typography, spacing, borderRadius, shadows };
export default theme;
