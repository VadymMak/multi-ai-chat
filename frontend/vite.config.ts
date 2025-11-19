import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import legacy from "@vitejs/plugin-legacy";
import path from "path";
import injectPolyfillPlugin from "./vite-plugin-inject-polyfill.js";

export default defineConfig({
  plugins: [
    injectPolyfillPlugin(),
    react(),
    legacy({
      targets: ["defaults", "not IE 11"],
      additionalLegacyPolyfills: ["regenerator-runtime/runtime"],
      renderLegacyChunks: true,
      modernPolyfills: true,
      renderModernChunks: true,
      polyfills: [
        "es.object.assign",
        "es.promise",
        "es.promise.finally",
        "es.symbol",
        "es.array.iterator",
      ],
    }),
  ],
  server: {
    port: 3000,
    open: true,
  },
  build: {
    outDir: "build",
    target: "es2015",
    sourcemap: true,
    minify: "terser",
    modulePreload: false,
    cssCodeSplit: false,
    commonjsOptions: {
      include: [/node_modules/],
      transformMixedEsModules: true,
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "#minpath": path.resolve(
        __dirname,
        "node_modules/vfile/lib/minpath.browser.js"
      ),
    },
  },
  optimizeDeps: {
    include: ["vfile", "react-markdown"],
    esbuildOptions: {
      target: "es2015",
      define: {
        global: "globalThis",
      },
    },
  },
});
