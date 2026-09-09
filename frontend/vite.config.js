import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
export default defineConfig({
  plugins: [vue()],
  // Keep hashed chunks available for sessions opened before a local update.
  build: {
    outDir: process.env.STUDIO_BUILD_DIR || "dist",
    emptyOutDir: false,
  },
  server: {
    proxy: {
      "/api": process.env.LEDGERLY_API_PROXY || "http://127.0.0.1:8000",
    },
  },
});
