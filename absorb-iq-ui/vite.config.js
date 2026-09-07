import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy /api -> FastAPI backend so the UI can use same-origin relative URLs in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
