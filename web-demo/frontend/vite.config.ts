// 文件用途：配置 Vue 构建、源码别名与 Demo 后端开发代理。
import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8080",
        // 保留浏览器的 Host，让后端能够校验同源写请求。
        changeOrigin: false,
      },
    },
  },
});
