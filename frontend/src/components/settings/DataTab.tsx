/**
 * DataTab — the Settings → Data tab.
 *
 * Layout (per Specs/UI/settings_window.md):
 *   - Subtitle ("Files and folders Magpie reads to understand your
 *     work. Nothing leaves your machine.") — the pane title lives in
 *     the window header strip.
 *   - Top-right toolbar: Sync / Reindex / Add folder / file
 *   - Folder rows (delegated to FolderRow)
 *   - Empty state when no folders yet
 *   - Exclusions sub-panel (collapsed by default)
 *
 * The Add dropdown menu offers "Add a folder…" and "Add a single
 * file…" — both invoke the existing pickFolder / pickFile Tauri
 * commands.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FolderOpen,
  Plus,
  RefreshCw,
  RotateCcw,
  X,
} from "lucide-react";
import {
  addFolder,
  addExclusion,
  friendlyError,
  isAlreadyIndexingError,
  jobCoversFolder,
  getExclusions,
  patchFolder,
  pickFile,
  pickFolder,
  removeExclusion,
  removeFolder,
  revealInFinder,
  runReindex,
  runSync,
  startIngest,
  stopIngest,
} from "../../api";
import type {
  ExclusionsResponse,
  FolderEntry,
  IngestStatus,
} from "../../api";
import { IngestPanel } from "./IngestPanel";

/** `startIngest`, but a 409 ("already indexing") resolves instead of throwing.
 *  Every caller has already persisted the rule change by this point, so the
 *  in-flight job's coalesced rerun will cover it — the 409 carries no
 *  information the user needs to act on. */
async function startIngestIgnoringConflict(path: string): Promise<void> {
  try {
    await startIngest(path);
  } catch (e) {
    if (!isAlreadyIndexingError(e)) throw e;
  }
}
import { ConfirmModal } from "./ConfirmModal";
import { FolderRow } from "./FolderRow";

interface Props {
  folders: FolderEntry[] | null;
  ingest: IngestStatus | null;
  /** Called by the parent to re-fetch /settings/folders after a
   *  mutation. The parent owns the list so it can stay in sync with
   *  the ingest poll. */
  refreshFolders: () => void;
  /** Notify parent to start the ingest poll (we just kicked off
   *  indexing). */
  onIngestStarted: () => void;
  /** Whether the parent has the ingest poll running already. */
  pollActive: boolean;
}

export function DataTab({
  folders,
  ingest,
  refreshFolders,
  onIngestStarted,
  pollActive,
}: Props) {
  const [showAddMenu, setShowAddMenu] = useState(false);
  const [showReindexConfirm, setShowReindexConfirm] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<FolderEntry | null>(null);
  const [exclusionsOpen, setExclusionsOpen] = useState(false);
  const [exclusions, setExclusions] = useState<ExclusionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const addMenuRef = useRef<HTMLDivElement>(null);

  // Close the Add dropdown when clicking outside.
  useEffect(() => {
    if (!showAddMenu) return;
    const onDocClick = (e: MouseEvent) => {
      if (addMenuRef.current && !addMenuRef.current.contains(e.target as Node)) {
        setShowAddMenu(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [showAddMenu]);

  const handlePickFolder = useCallback(async () => {
    setShowAddMenu(false);
    setError(null);
    try {
      const path = await pickFolder();
      if (!path) return;
      await addFolder(path);
      // The folder is already saved at this point. A 409 here just means the
      // startup auto-sync is still in flight — the rule change we just made
      // gets picked up by its coalesced rerun, so the folder WILL be read.
      // Letting that throw used to skip refreshFolders() below, which is why
      // adding a first folder during boot showed an error banner over an
      // empty list even though the add had succeeded.
      await startIngestIgnoringConflict(path);
      onIngestStarted();
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      refreshFolders();
    }
  }, [onIngestStarted, refreshFolders]);

  const handlePickFile = useCallback(async () => {
    setShowAddMenu(false);
    setError(null);
    try {
      const path = await pickFile();
      if (!path) return;
      await addFolder(path);
      await startIngestIgnoringConflict(path);   // see handlePickFolder
      onIngestStarted();
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      refreshFolders();
    }
  }, [onIngestStarted, refreshFolders]);

  const handleSync = useCallback(async () => {
    setError(null);
    try {
      await runSync();
      onIngestStarted();
    } catch (e) {
      // Clicking Sync while a sync is already running returns a benign 409 —
      // indexing is already happening, which is what the user wanted, so just
      // make sure the poll is active and don't alarm them with an error banner.
      if (isAlreadyIndexingError(e)) {
        onIngestStarted();
        return;
      }
      setError(friendlyError(e));
    }
  }, [onIngestStarted]);

  const handleReindexConfirm = useCallback(async () => {
    setShowReindexConfirm(false);
    setError(null);
    try {
      await runReindex();
      onIngestStarted();
    } catch (e) {
      setError(friendlyError(e));
    }
  }, [onIngestStarted]);

  const handleToggle = useCallback(async (path: string, enabled: boolean) => {
    setError(null);
    try {
      await patchFolder({ path, enabled });
      refreshFolders();
    } catch (e) {
      setError(friendlyError(e));
    }
  }, [refreshFolders]);

  const handleRemove = useCallback((path: string) => {
    const target = (folders ?? []).find((f) => f.path === path);
    if (target) setRemoveTarget(target);
  }, [folders]);

  const handleRemoveConfirm = useCallback(async () => {
    if (!removeTarget) return;
    const path = removeTarget.path;
    setRemoveTarget(null);
    setError(null);
    try {
      await removeFolder(path);
      refreshFolders();
    } catch (e) {
      setError(friendlyError(e));
    }
  }, [removeTarget, refreshFolders]);

  const handleResync = useCallback(async (_path: string) => {
    // v1: per-folder Refresh fires the global Sync. When we add
    // per-folder ingest jobs (post-v1), this becomes a path-filtered
    // call.
    await handleSync();
  }, [handleSync]);

  const handleStop = useCallback(async () => {
    try {
      await stopIngest();
    } catch (e) {
      setError(friendlyError(e));
    }
  }, []);

  const handleReveal = useCallback(async (path: string) => {
    try { await revealInFinder(path); } catch { /* ignore */ }
  }, []);

  const handleToggleExclusions = useCallback(async () => {
    const next = !exclusionsOpen;
    setExclusionsOpen(next);
    if (next && exclusions === null) {
      try {
        const data = await getExclusions();
        setExclusions(data);
      } catch (e) {
        setError(friendlyError(e));
      }
    }
  }, [exclusionsOpen, exclusions]);

  // Empty state.
  if (folders !== null && folders.length === 0) {
    return (
      <div className="data-tab">
        <DataHeader
          showAddMenu={showAddMenu}
          setShowAddMenu={setShowAddMenu}
          addMenuRef={addMenuRef}
          onPickFolder={handlePickFolder}
          onPickFile={handlePickFile}
          onSync={handleSync}
          onReindex={() => setShowReindexConfirm(true)}
          syncDisabled={pollActive}
        />
        {error && <ErrorBanner message={error} />}
        <div className="data-tab__empty">
          <div className="data-tab__empty-glyph" aria-hidden="true">
            <FolderOpen size={40} strokeWidth={1.25} />
          </div>
          <p className="data-tab__empty-headline">
            Magpie hasn't read any of your files yet.
          </p>
          <p className="data-tab__empty-sub">
            Add a folder to get started — Magpie will read it on your machine.
          </p>
        </div>
        <ReindexConfirm
          open={showReindexConfirm}
          onCancel={() => setShowReindexConfirm(false)}
          onConfirm={handleReindexConfirm}
        />
        <RemoveConfirm
          target={removeTarget}
          onCancel={() => setRemoveTarget(null)}
          onConfirm={handleRemoveConfirm}
        />
      </div>
    );
  }

  return (
    <div className="data-tab">
      <DataHeader
        showAddMenu={showAddMenu}
        setShowAddMenu={setShowAddMenu}
        addMenuRef={addMenuRef}
        onPickFolder={handlePickFolder}
        onPickFile={handlePickFile}
        onSync={handleSync}
        onReindex={() => setShowReindexConfirm(true)}
        syncDisabled={pollActive}
      />
      <IngestPanel ingest={ingest} onStop={handleStop} />
      {error && <ErrorBanner message={error} />}
      <div className="data-tab__list">
        {folders === null ? (
          <SkeletonList />
        ) : (
          folders.map((f) => (
            <FolderRow
              key={f.path}
              folder={f}
              isIngesting={
                Boolean(ingest?.running) &&
                ingest?.path === f.path
              }
              inJobScope={jobCoversFolder(ingest, f.path)}
              ingest={ingest}
              onToggle={handleToggle}
              onRemove={handleRemove}
              onResync={handleResync}
              onStop={handleStop}
              onReveal={handleReveal}
            />
          ))
        )}
      </div>

      <ExclusionsPanel
        open={exclusionsOpen}
        onToggle={handleToggleExclusions}
        exclusions={exclusions}
        onAdd={async (body) => {
          await addExclusion(body);
          const refreshed = await getExclusions();
          setExclusions(refreshed);
        }}
        onRemove={async (type, value) => {
          await removeExclusion(type, value);
          const refreshed = await getExclusions();
          setExclusions(refreshed);
        }}
      />

      <ReindexConfirm
        open={showReindexConfirm}
        onCancel={() => setShowReindexConfirm(false)}
        onConfirm={handleReindexConfirm}
      />
      <RemoveConfirm
        target={removeTarget}
        onCancel={() => setRemoveTarget(null)}
        onConfirm={handleRemoveConfirm}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components used only by DataTab
// ---------------------------------------------------------------------------

function DataHeader({
  showAddMenu,
  setShowAddMenu,
  addMenuRef,
  onPickFolder,
  onPickFile,
  onSync,
  onReindex,
  syncDisabled,
}: {
  showAddMenu: boolean;
  setShowAddMenu: (v: boolean) => void;
  addMenuRef: React.RefObject<HTMLDivElement>;
  onPickFolder: () => void;
  onPickFile: () => void;
  onSync: () => void;
  onReindex: () => void;
  syncDisabled: boolean;
}) {
  // The pane title lives in the window header strip now; this row is
  // subtitle + toolbar. flex-wrap in CSS lets the buttons drop to
  // their own line on narrow windows instead of colliding with text.
  return (
    <header className="data-tab__header">
      <p className="data-tab__subtitle">
        Files and folders Magpie reads to understand your work. Nothing
        leaves your machine.
      </p>
      <div className="data-tab__header-actions">
        <button
          type="button"
          className="data-tab__btn data-tab__btn--ghost"
          onClick={onSync}
          disabled={syncDisabled}
          title="Pick up new files and drop removed ones."
        >
          <RefreshCw size={13} aria-hidden="true" /> Sync
        </button>
        <button
          type="button"
          className="data-tab__btn data-tab__btn--warn"
          onClick={onReindex}
          disabled={syncDisabled}
          title="Rebuild from scratch. Slow but thorough."
        >
          <RotateCcw size={13} aria-hidden="true" /> Reindex
        </button>
        <div className="data-tab__add-menu-wrap" ref={addMenuRef}>
          <button
            type="button"
            className="data-tab__btn data-tab__btn--primary"
            onClick={() => setShowAddMenu(!showAddMenu)}
          >
            <Plus size={14} aria-hidden="true" /> Add folder / file{" "}
            <ChevronDown size={13} aria-hidden="true" />
          </button>
          {showAddMenu && (
            <div className="data-tab__add-menu" role="menu">
              <button type="button" className="data-tab__add-item" onClick={onPickFolder}>
                Add a folder…
              </button>
              <button type="button" className="data-tab__add-item" onClick={onPickFile}>
                Add a single file…
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="data-tab__error" role="alert">
      <AlertTriangle size={14} aria-hidden="true" /> {message}
    </div>
  );
}

function SkeletonList() {
  return (
    <div className="data-tab__skeleton">
      <div className="data-tab__skeleton-row" />
      <div className="data-tab__skeleton-row" />
      <div className="data-tab__skeleton-row" />
    </div>
  );
}

function ReindexConfirm({
  open,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <ConfirmModal
      open={open}
      title="Reindex everything?"
      body={
        <p>
          This rebuilds Magpie's understanding of all your folders. It can
          take 10–60 minutes depending on how much you've added.{" "}
          <strong>Your files are not touched.</strong>
        </p>
      }
      requireWord="RESET"
      confirmLabel="Reindex"
      confirmTone="danger"
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  );
}

function RemoveConfirm({
  target,
  onCancel,
  onConfirm,
}: {
  target: FolderEntry | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <ConfirmModal
      open={target !== null}
      title="Stop reading this folder?"
      body={
        <p>
          {target?.display_name || target?.path.split(/[\\/]/).pop() || target?.path}
          {" "}— files inside the folder are not deleted. Magpie will forget
          what's inside it.
        </p>
      }
      confirmLabel="Remove"
      confirmTone="danger"
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  );
}

function ExclusionsPanel({
  open,
  onToggle,
  exclusions,
  onAdd,
  onRemove,
}: {
  open: boolean;
  onToggle: () => void;
  exclusions: ExclusionsResponse | null;
  onAdd: (body: { path?: string; glob?: string }) => Promise<void>;
  onRemove: (type: "path" | "glob", value: string) => Promise<void>;
}) {
  const [globInput, setGlobInput] = useState("");

  const handleAddGlob = useCallback(async () => {
    const v = globInput.trim();
    if (!v) return;
    await onAdd({ glob: v });
    setGlobInput("");
  }, [globInput, onAdd]);

  const handleAddPath = useCallback(async () => {
    const path = await pickFolder();
    if (path) await onAdd({ path });
  }, [onAdd]);

  return (
    <section className={`exclusions-panel ${open ? "is-open" : ""}`}>
      <button
        type="button"
        className="exclusions-panel__toggle"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span className="exclusions-panel__chevron" aria-hidden="true">
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </span>
        Exclusions
        {exclusions && (
          <span className="exclusions-panel__count">
            {exclusions.paths.length + exclusions.globs.length}
          </span>
        )}
      </button>
      {open && (
        <div className="exclusions-panel__body">
          {exclusions === null ? (
            <p className="exclusions-panel__loading">Loading…</p>
          ) : (
            <>
              <ExclusionList
                title="Excluded paths"
                items={exclusions.paths}
                onAddClick={handleAddPath}
                onRemove={(v) => onRemove("path", v)}
              />
              <ExclusionList
                title="Excluded glob patterns"
                items={exclusions.globs}
                addInput={
                  <div className="exclusions-panel__add-row">
                    <input
                      type="text"
                      className="exclusions-panel__input"
                      placeholder="e.g. *.log"
                      value={globInput}
                      onChange={(e) => setGlobInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          handleAddGlob();
                        }
                      }}
                    />
                    <button
                      type="button"
                      className="exclusions-panel__add-btn"
                      onClick={handleAddGlob}
                    >
                      Add
                    </button>
                  </div>
                }
                onRemove={(v) => onRemove("glob", v)}
              />
            </>
          )}
        </div>
      )}
    </section>
  );
}

function ExclusionList({
  title,
  items,
  addInput,
  onAddClick,
  onRemove,
}: {
  title: string;
  items: string[];
  addInput?: React.ReactNode;
  onAddClick?: () => void;
  onRemove: (value: string) => void;
}) {
  return (
    <div className="exclusion-list">
      <h4 className="exclusion-list__title">{title}</h4>
      {items.length === 0 ? (
        <p className="exclusion-list__empty">No exclusions.</p>
      ) : (
        <ul className="exclusion-list__items">
          {items.map((value) => (
            <li key={value} className="exclusion-list__item">
              <code className="exclusion-list__value">{value}</code>
              <button
                type="button"
                className="exclusion-list__remove"
                onClick={() => onRemove(value)}
                aria-label={`Remove ${value}`}
              >
                <X size={12} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {addInput || (
        <button type="button" className="exclusion-list__add-btn" onClick={onAddClick}>
          <Plus size={12} aria-hidden="true" /> Add path…
        </button>
      )}
    </div>
  );
}
