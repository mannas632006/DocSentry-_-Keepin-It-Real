import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dashboard talks to the API at an absolute URL resolved at runtime (see
// src/api.js), so there is no dev proxy here: in development it calls
// http://localhost:8000 directly, which the API's default cors_origins="*"
// allows.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
