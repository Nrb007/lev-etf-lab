/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./" + hash routing: the site works from any path (GitHub Pages serves it under /<repo>/).
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  test: { environment: "jsdom", setupFiles: ["./tests/setup.ts"], globals: true, testTimeout: 20000 },
});
