module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
    "postcss-custom-properties": {
      preserve: false, // Заменить переменные на реальные значения
    },
  },
};
