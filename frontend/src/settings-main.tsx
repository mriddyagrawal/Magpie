import React from "react";
import ReactDOM from "react-dom/client";
import { SettingsWindow } from "./components/SettingsWindow";
import "./styles/tokens.css";
import "./styles/globals.css";

// Dedicated entry point for the Settings window. Unlike the shared
// index.html → App.tsx path (which guesses the window type from a
// Rust-injected `window.__MAGPIE_WINDOW_TYPE__` global), this renders
// <SettingsWindow> directly. That removes the init-script/global race
// that white-screened the settings webview on Windows/WebView2, and lets
// you develop the settings UI in a plain browser at /settings.html.
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <SettingsWindow />
  </React.StrictMode>
);
