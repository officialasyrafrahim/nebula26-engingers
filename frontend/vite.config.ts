import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The SPA is served behind the same origin as the API in production. During
// development, Vite proxies the API and health endpoint to the FastAPI process.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
});
