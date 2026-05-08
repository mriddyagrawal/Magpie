import { useCallback, useEffect, useRef, useState } from "react";
import {
  getFolders,
  addFolder,
  removeFolder,
  getShortcut,
  pickFolder,
  startIngest,
  getIngestStatus,
  stopIngest,
} from "../api";
import type { FolderEntry, IngestStatus } from "../api";
import "./SettingsWindow.css";

function formatElapsed(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

export function SettingsWindow() {
  const [folders, setFolders] = useState<FolderEntry[]>([]);
  const [shortcut, setShortcut] = useState("Alt+Space");
  const [ingest, setIngest] = useState<IngestStatus | null>(null);
  const [addingFolder, setAddingFolder] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadFolders = useCallback(async () => {
    try {
      const data = await getFolders();
      setFolders(data.folders);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    loadFolders();
    getShortcut().then(setShortcut).catch(() => {});
  }, [loadFolders]);

  // Poll ingest status while indexing is running.
  useEffect(() => {
    const tick = async () => {
      try {
        const s = await getIngestStatus();
        setIngest(s);
        if (!s.running) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          loadFolders();
        }
      } catch {
        // sidecar not ready yet — ignore
      }
    };

    const startPolling = () => {
      if (pollRef.current) return;
      pollRef.current = setInterval(tick, 1000);
      tick();
    };

    // Check once on mount to see if indexing is already running.
    getIngestStatus()
      .then((s) => {
        setIngest(s);
        if (s.running) startPolling();
      })
      .catch(() => {});

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadFolders]);

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    const tick = async () => {
      try {
        const s = await getIngestStatus();
        setIngest(s);
        if (!s.running) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          loadFolders();
        }
      } catch {}
    };
    pollRef.current = setInterval(tick, 1000);
    tick();
  }, [loadFolders]);

  const handleAddFolder = useCallback(async () => {
    setAddingFolder(true);
    setError(null);
    try {
      const path = await pickFolder();
      if (!path) return;
      await addFolder(path);
      await loadFolders();
      await startIngest(path);
      startPolling();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAddingFolder(false);
    }
  }, [loadFolders, startPolling]);

  const handleRemoveFolder = useCallback(async (path: string) => {
    setError(null);
    try {
      await removeFolder(path);
      setFolders((prev) => prev.filter((f) => f.path !== path));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const handleIndexFolder = useCallback(async (path: string) => {
    setError(null);
    try {
      await startIngest(path);
      startPolling();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [startPolling]);

  const handleStop = useCallback(async () => {
    await stopIngest();
  }, []);

  const indexingPath = ingest?.running ? ingest.path : null;

  return (
    <div className="settings-window">
      <h1 className="settings-window__title">Settings</h1>

      {error && <p className="settings-window__error">{error}</p>}

      {/* ── Indexed Locations ─────────────────────────────────────────── */}
      <section className="settings-section">
        <div className="settings-section__header">
          <h2 className="settings-section__title">Indexed Locations</h2>
          <button
            className="settings-btn settings-btn--primary"
            onClick={handleAddFolder}
            disabled={addingFolder || (ingest?.running ?? false)}
          >
            {addingFolder ? "Picking…" : "+ Add Folder"}
          </button>
        </div>

        {folders.length === 0 ? (
          <p className="settings-empty">No folders indexed yet.</p>
        ) : (
          <ul className="settings-folder-list">
            {folders.map((f) => {
              const isIndexingThis = indexingPath === f.path;
              return (
                <li key={f.path} className="settings-folder-item">
                  <span className="settings-folder-item__path" title={f.path}>
                    {f.path}
                  </span>
                  <div className="settings-folder-item__actions">
                    {isIndexingThis ? (
                      <span className="settings-folder-item__badge">Indexing…</span>
                    ) : (
                      <button
                        className="settings-btn settings-btn--ghost"
                        onClick={() => handleIndexFolder(f.path)}
                        disabled={ingest?.running ?? false}
                        title="Re-index this folder"
                      >
                        Re-index
                      </button>
                    )}
                    <button
                      className="settings-btn settings-btn--danger"
                      onClick={() => handleRemoveFolder(f.path)}
                      disabled={isIndexingThis}
                      title="Remove from indexed locations"
                    >
                      Remove
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* ── Indexing Progress ─────────────────────────────────────────── */}
      {ingest?.running && (
        <section className="settings-section settings-section--progress">
          <h2 className="settings-section__title">Indexing</h2>
          <p className="settings-progress__message">
            {ingest.files_total
              ? `${ingest.files_done} / ${ingest.files_total} files`
              : "Scanning…"}
          </p>
          {ingest.files_total > 0 && (
            <div className="settings-progress__bar">
              <div
                className="settings-progress__fill"
                style={{ width: `${Math.round((ingest.files_done / ingest.files_total) * 100)}%` }}
              />
            </div>
          )}
          {ingest.current_file && (
            <p className="settings-progress__detail">
              {ingest.current_file.length > 52
                ? `…${ingest.current_file.slice(-50)}`
                : ingest.current_file}
            </p>
          )}
          {ingest.elapsed_s != null && (
            <p className="settings-progress__detail">{formatElapsed(ingest.elapsed_s)} elapsed</p>
          )}
          <button className="settings-btn settings-btn--stop" onClick={handleStop}>
            Stop indexing
          </button>
        </section>
      )}

      {/* ── Keyboard Shortcut ─────────────────────────────────────────── */}
      <section className="settings-section">
        <h2 className="settings-section__title">Keyboard Shortcut</h2>
        <div className="settings-shortcut-row">
          <span className="settings-shortcut-row__label">Summon Magpie</span>
          <kbd className="settings-shortcut-row__kbd">{shortcut}</kbd>
        </div>
        <p className="settings-hint">
          To change the shortcut, quit and relaunch Magpie — it will offer alternatives if the
          current shortcut is taken.
        </p>
      </section>

      {/* ── About ─────────────────────────────────────────────────────── */}
      <section className="settings-section">
        <h2 className="settings-section__title">About</h2>
        <p className="settings-hint">
          Magpie — local AI search for your files. Built with ColPali, Qdrant, and a lot of
          stubbornness.
        </p>
      </section>
    </div>
  );
}
