import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { checkForUpdates } from "./auto-updater";
import "./styles/tokens.css";
import "./styles/globals.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Plan #10 P10-6 — fire one auto-update check on app launch.
// Runs in the background; silent on failure. See auto-updater.ts.
// Deferred via setTimeout so the window paints first before we hit
// the network. 1.5 s is short enough to catch updates promptly but long
// enough that the user sees the search bar before any update activity.
setTimeout(() => {
  void checkForUpdates({ silent: true });
}, 1500);
