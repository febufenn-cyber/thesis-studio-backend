import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

/**
 * Phase B (SPA): the full single-page app served at /app (FRONTEND_LLD §19).
 * Assets are emitted to app/static/spa/ and referenced under /static/spa/ (the
 * FastAPI StaticFiles mount); FastAPI serves index.html for /app and its
 * client-side routes. Coexists with the vanilla app at / until parity.
 */
export default defineConfig({
  root: resolve(__dirname),
  base: "/static/spa/",
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, "../app/static/spa"),
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(__dirname, "index.html"),
    },
  },
});
