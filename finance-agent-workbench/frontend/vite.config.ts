import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 构建产物输出到 frontend/dist，由 Flask 静态托管
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/static/app/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      // 开发时代理到 Flask 后端
      "/api": "http://127.0.0.1:8080",
    },
  },
});
