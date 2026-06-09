import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { visualizer } from "rollup-plugin-visualizer";

// Прокси на FastAPI-бэкенд (toursearch web → :8000): /search/prepare,
// /search/stream (SSE), /search/cancel, страница результатов /run/{id}.
// Скриншоты теперь идут через /api/runs/{id}/screenshot/{provider} и
// /api/tests/screenshot/{filename} — оба покрыты префиксом /api.
const BACKEND = process.env.TOURSEARCH_API || "http://127.0.0.1:8000";

// Bundle analyzer включается через ANALYZE=1 npm run build (или :analyze скрипт).
// Создаёт `dist/stats.html` (treemap размеров модулей в gzip).
const analyze = process.env.ANALYZE === "1";

export default defineConfig({
  plugins: [
    react(),
    analyze && visualizer({
      filename: "dist/stats.html",
      gzipSize: true,
      brotliSize: true,
      template: "treemap",
    }),
  ].filter(Boolean),
  // Относительные пути ассетов — чтобы собранный dist раздавался FastAPI
  // под префиксом /app (StaticFiles) без переписывания ссылок.
  base: "./",
  server: {
    port: 5173,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/search": { target: BACKEND, changeOrigin: true },
      "/tests": { target: BACKEND, changeOrigin: true },
      "/run": { target: BACKEND, changeOrigin: true },
    },
  },
});
