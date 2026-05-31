import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Прокси на FastAPI-бэкенд (toursearch web → :8000): /search/prepare,
// /search/stream (SSE), /search/cancel, страница результатов /run/{id} и её
// скриншоты /screenshots. Так фронт (vite :5173) ходит к бэкенду без CORS-плясок.
const BACKEND = process.env.TOURSEARCH_API || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/search": { target: BACKEND, changeOrigin: true },
      "/run": { target: BACKEND, changeOrigin: true },
      "/screenshots": { target: BACKEND, changeOrigin: true },
      "/history": { target: BACKEND, changeOrigin: true },
    },
  },
});
