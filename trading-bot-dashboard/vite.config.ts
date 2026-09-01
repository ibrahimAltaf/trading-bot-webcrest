import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Access dev server from phone on LAN: http://YOUR_PC_IP:7000
    host: true,
    port: 7000,
    proxy: {
      // Same-origin /api → FastAPI on :6000 (no CORS). Nginx production uses /api too.
      "/api": {
        target: "http://127.0.0.1:6000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, "") || "/",
      },
    },
  },
});
