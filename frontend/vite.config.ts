import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

/**
 * Phase A (bridge): build the React kit as a single self-contained IIFE bundle
 * that the served vanilla app (app/static/v2.html) loads. It exposes
 * window.AcadensiaKit.mount*() so E1–E7 render as islands inside the current
 * app — no framework migration required yet. Output lands in app/static/app/
 * so FastAPI's StaticFiles serves it at /static/app/.
 */
export default defineConfig({
  plugins: [react()],
  define: { "process.env.NODE_ENV": '"production"' },
  build: {
    outDir: resolve(__dirname, "../app/static/app"),
    emptyOutDir: true,
    lib: {
      entry: resolve(__dirname, "src/islands.tsx"),
      name: "AcadensiaKit",
      formats: ["iife"],
      fileName: () => "acadensia-kit.iife.js",
    },
    rollupOptions: {
      // React + ReactDOM are bundled in so the island is drop-in with no import map.
      output: { assetFileNames: "acadensia-kit.[ext]" },
    },
  },
});
