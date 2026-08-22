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
    // Don't let Vite's file watcher recurse into the Rust build output.
    // On Windows, watching src-tauri/target/**/*.dll crashes with EBUSY
    // because the linker holds a lock on the .dll while it's being written.
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
  envPrefix: ["VITE_", "TAURI_"],
  build: {
    rollupOptions: {
      // Two HTML entry points: the spotlight bar (index.html) and the
      // Settings window (settings.html). Vite serves both in dev, so the
      // settings UI is reachable at http://localhost:1420/settings.html.
      input: {
        main: "index.html",
        settings: "settings.html",
      },
    },
  },
});
