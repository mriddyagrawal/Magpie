import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri reserves 1420; for plain browser dev we use 5173 (Vite default).
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: false,
    host: "127.0.0.1",
  },
  envPrefix: ["VITE_", "TAURI_"],
});
