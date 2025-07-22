/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class", // ✅ ВАЖНО!
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // ✅ ПРАВИЛЬНЫЙ СПОСОБ - с var()
        background: "var(--color-background)",
        panel: "var(--color-panel)",
        surface: "var(--color-surface)",
        border: "var(--color-border)",
        primary: "var(--color-primary)",
        success: "var(--color-success)",
        warning: "var(--color-warning)",
        error: "var(--color-error)",
        purple: "var(--color-purple)",
        "text-primary": "var(--color-text-primary)",
        "text-secondary": "var(--color-text-secondary)",
      },
    },
  },
  plugins: [],
};
