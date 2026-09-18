import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Compose-only Vite config. The browser reaches Vite on :5173 and Vite proxies
// to the `api` service, because "localhost" inside the web container is not the
// API container. The frontend's own vite.config.ts is left untouched.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    proxy: {
      "/api": "http://api:8000",
      "/healthz": "http://api:8000",
    },
  },
});
