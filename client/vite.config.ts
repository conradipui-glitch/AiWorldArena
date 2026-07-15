import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiPort = process.env.AI_SOCIETY_API_PORT ?? "8000";
const apiTarget = `http://127.0.0.1:${apiPort}`;

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    allowedHosts: ["terminal.local"],
    proxy: {
      "/v1": {
        target: apiTarget,
        changeOrigin: true,
        ws: true,
      },
      "/health": apiTarget,
    },
  },
});
