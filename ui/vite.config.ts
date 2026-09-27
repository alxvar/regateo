import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev, /api goes to `regateo serve` (default port 8000).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": { target: process.env.REGATEO_API ?? "http://127.0.0.1:8000", changeOrigin: true } },
  },
});
