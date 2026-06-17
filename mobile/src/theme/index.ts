import type { TextStyle } from "react-native";

export const colors = {
  bg:          "#161210",
  bgChat:      "#14100E",
  surface:     "#241E19",
  inputBg:     "#211B16",
  border:      "#322820",
  borderHi:    "#3A2F25",
  textPrimary:   "#F2ECE3",
  textSecondary: "#9A8F7F",
  textHint:      "#6F6557",
  accent:    "#C9A35B",
  accentHi:  "#D9B36A",
  onAccent:  "#221A10",
  tagSearchBg: "#2E2719", tagSearch: "#D9B36A",
  tagNotesBg:  "#1E2A22", tagNotes:  "#7FCBAA",
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
