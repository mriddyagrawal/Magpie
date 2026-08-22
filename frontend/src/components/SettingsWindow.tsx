/**
 * SettingsWindow — the top-level orchestrator for the Settings UI.
 *
 * Replaces Rahul's first-pass implementation (276 LOC, single flat
 * folder list) with the three-tab layout from
 * Specs/UI/settings_window.md:
 *
 *   - Sidebar (left): Magpie / SETTINGS / nav (Data / Search & AI /
 *     Shortcut & App) / status footer
 *   - Header strip (top): active section name + ● <state> pill
 *   - Main content: tab-specific component
 *
 * State ownership:
 *   - The orchestrator owns the four data slices (folders, search,
 *     app, providers) so tabs share the same source of truth and a
 *     PATCH from one tab can update the visible state in another
 *     (e.g., changing accent in Shortcut & App immediately affects
 *     Settings' own theme tokens).
 *   - The ingest poll lives here too — same 1.5s tick pattern as
 *     MagpieWindow. Running while the ingest is active; idle
 *     otherwise.
 *
 * The deep-link useRef pattern from PR 4 is preserved: the
 * NotFoundCard's "Add the folder where this knowledge might live"
 * CTA opens this window with `__MAGPIE_SETTINGS_ACTION__ =
 * "add-folder"`, which on mount switches to the Data tab AND fires
 * the folder picker.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getAppSettings,
  getFolders,
  getIngestStatus,
  getProviders,
  getSearchSettings,
  getShortcut,
  getStatus,
} from "./../api";
import type {
  AppSettings,
  FolderEntry,
  IngestStatus,
  ProvidersInfo,
  SearchSettings,
} from "./../api";
import type { StatusResponse } from "./../types";

import { ConfirmModal } from "./settings/ConfirmModal";
import { DataTab } from "./settings/DataTab";
import { SearchAITab } from "./settings/SearchAITab";
import { SettingsHeader } from "./settings/SettingsHeader";
import { SettingsSidebar } from "./settings/SettingsSidebar";
import type { SettingsTab } from "./settings/SettingsSidebar";
import { ShortcutAppTab } from "./settings/ShortcutAppTab";

import "./settings/Settings.css";

// Status fetch — periodic so the sidebar footer stays live.
const STATUS_POLL_MS = 5_000;
const INGEST_POLL_MS = 1_500;

export function SettingsWindow() {
  const [tab, setTab] = useState<SettingsTab>("data");
  const [folders, setFolders] = useState<FolderEntry[] | null>(null);
  const [search, setSearch] = useState<SearchSettings | null>(null);
  const [providers, setProviders] = useState<ProvidersInfo | null>(null);
  const [app, setApp] = useState<AppSettings | null>(null);
  const [shortcut, setShortcut] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [ingest, setIngest] = useState<IngestStatus | null>(null);
  const [appVersion, setAppVersion] = useState("0.1.0");

  // Stable ref for the deep-link "add folder" trigger. The handler
  // closes over `setTab` + DataTab's onIngestStarted, so we update
  // the ref on each render and call .current?.() in the
  // mount-time effect.
  const handleDeepLinkAddFolderRef = useRef<(() => void) | null>(null);

  // ----------- Initial parallel fetch on mount -----------
  // Each load RETRIES with a short backoff. On the packaged app's first
  // launch the sidecar is still booting (models load ~3-5s), so a single
  // fetch fails and — with no retry — left `folders` null forever, i.e. the
  // Data tab stuck on its loading skeletons (users hit Reindex just to
  // unstick it). Retrying until the sidecar answers fixes that without any
  // user action.
  useEffect(() => {
    let cancelled = false;
    const MAX_RETRIES = 6;
    const RETRY_DELAY_MS = 1500;
    async function withRetry<T>(fn: () => Promise<T>, label: string): Promise<T | undefined> {
      for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
        if (cancelled) return undefined;
        try {
          return await fn();
        } catch (e) {
          if (attempt === MAX_RETRIES) {
            console.warn(`${label} load failed after ${MAX_RETRIES + 1} attempts:`, e);
            return undefined;
          }
          await new Promise((r) => setTimeout(r, RETRY_DELAY_MS));
        }
      }
      return undefined;
    }
    (async () => {
      const tasks = [
        withRetry(getFolders, "folders").then((r) => { if (r && !cancelled) setFolders(r.folders); }),
        withRetry(getSearchSettings, "search-settings").then((r) => { if (r && !cancelled) setSearch(r); }),
        withRetry(getProviders, "providers").then((r) => { if (r && !cancelled) setProviders(r); }),
        withRetry(getAppSettings, "app-settings").then((r) => { if (r && !cancelled) setApp(r); }),
        withRetry(getShortcut, "shortcut").then((r) => { if (r && !cancelled) setShortcut(r); }),
        withRetry(getStatus, "status").then((r) => {
          if (r && !cancelled) { setStatus(r); setAppVersion(r.version); }
        }),
      ];
      await Promise.allSettled(tasks);
    })();
    return () => { cancelled = true; };
  }, []);

  // ----------- Status refresh poll (slow) -----------
  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const r = await getStatus();
        setStatus(r);
      } catch { /* ignore */ }
    }, STATUS_POLL_MS);
    return () => clearInterval(id);
  }, []);

  // ----------- Ingest poll (only when running) -----------
  // Same pattern as MagpieWindow: tick every 1.5s. On running→done
  // edge, refresh the folders list so per-row stats reflect the
  // newly-indexed files.
  const prevRunningRef = useRef(false);
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      while (!cancelled) {
        await new Promise((res) => setTimeout(res, INGEST_POLL_MS));
        if (cancelled) break;
        try {
          const s = await getIngestStatus();
          if (cancelled) break;
          if (s.running) {
            prevRunningRef.current = true;
            setIngest(s);
          } else if (prevRunningRef.current) {
            prevRunningRef.current = false;
            setIngest(null);
            // Refresh folders so the new files appear with correct
            // stats. Status refresh fires on its own poll.
            try {
              const r = await getFolders();
              if (!cancelled) setFolders(r.folders);
            } catch { /* ignore */ }
          } else {
            setIngest(null);
          }
        } catch {
          // sidecar hiccup — try again next tick
        }
      }
    };
    tick();
    return () => { cancelled = true; };
  }, []);

  // ----------- Theme + accent application to <html> -----------
  useEffect(() => {
    if (app === null) return;
    if (app.theme === "system") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = app.theme;
    }
    document.documentElement.dataset.accent = app.accent;
  }, [app?.theme, app?.accent]);

  // ----------- Refresh helpers passed to tabs -----------
  const refreshFolders = useCallback(async () => {
    try {
      const r = await getFolders();
      setFolders(r.folders);
    } catch (e) {
      console.warn("refreshFolders failed:", e);
    }
  }, []);

  const onIngestStarted = useCallback(() => {
    // Flag the poll so the running→done edge fires properly. The
    // poll itself is always running; this just ensures we observe
    // the start by setting a stub state to read against.
    prevRunningRef.current = true;
    // Fire-and-forget an immediate status fetch to surface progress
    // sooner than the next 1.5s tick.
    getIngestStatus().then((s) => setIngest(s)).catch(() => {});
  }, []);

  // ----------- Deep-link handler (NotFoundCard → add folder) -----------
  // Switch to Data tab + fire the folder picker. Lives as a stable
  // useCallback; the ref-based dispatch below ensures the mount-time
  // effect calls the LATEST closure (not the one captured at first
  // render).
  const handleDeepLinkAddFolder = useCallback(() => {
    setTab("data");
    requestAnimationFrame(() => {
      import("./../api").then(async ({ addFolder, pickFolder, startIngest }) => {
        const path = await pickFolder();
        if (!path) return;
        try {
          await addFolder(path);
          await startIngest(path);
          onIngestStarted();
          await refreshFolders();
        } catch (e) {
          console.warn("deep-link addFolder failed:", e);
        }
      });
    });
  }, [refreshFolders, onIngestStarted]);

  useEffect(() => {
    handleDeepLinkAddFolderRef.current = handleDeepLinkAddFolder;
  }, [handleDeepLinkAddFolder]);

  useEffect(() => {
    const w = window as Window & { __MAGPIE_SETTINGS_ACTION__?: string };
    const action = w.__MAGPIE_SETTINGS_ACTION__;
    if (action === "add-folder") {
      w.__MAGPIE_SETTINGS_ACTION__ = undefined;
      handleDeepLinkAddFolderRef.current?.();
    }
  }, []);

  return (
    <div className="settings-window">
      <SettingsSidebar active={tab} onChange={setTab} status={status} />
      <main className="settings-main">
        <SettingsHeader tab={tab} status={status} ingest={ingest} />
        <div className="settings-main__body">
          {tab === "data" && (
            <DataTab
              folders={folders}
              ingest={ingest}
              refreshFolders={refreshFolders}
              onIngestStarted={onIngestStarted}
              pollActive={Boolean(ingest?.running)}
            />
          )}
          {tab === "search-ai" && (
            <SearchAITab
              search={search}
              setSearch={setSearch}
              providers={providers}
              setProviders={setProviders}
            />
          )}
          {tab === "shortcut-app" && (
            <ShortcutAppTab
              app={app}
              setApp={setApp}
              shortcut={shortcut}
              setShortcut={setShortcut}
              appVersion={appVersion}
            />
          )}
        </div>
      </main>
    </div>
  );
}

// Re-export to keep existing callers (App.tsx etc.) compiling.
// (Not strictly needed since they import { SettingsWindow } already,
// but the explicit re-export documents the public surface.)
export { ConfirmModal };
