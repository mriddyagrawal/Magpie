/**
 * DataTab — the Settings → Data tab.
 *
 * Layout (per Specs/UI/settings_window.md):
 *   - Title + subtitle ("Files and folders Magpie reads to understand
 *     your work. Nothing leaves your machine.")
 *   - Top-right: ↻ Sync · ⟳ Reindex · + Add folder / file ▾
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
  addFolder,
  addExclusion,
  getExclusions,
  getIndexPlan,
  patchFolder,
  pickFile,
  pickFolder,
  removeExclusion,
  removeFolder,
  revealInFinder,
  runReindex,
  runSync,
  stopIngest,
} from "../../api";
import type {
  ExclusionsResponse,
  FolderEntry,
  IndexPlan,
  IngestStatus,
} from "../../api";
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
  const [plan, setPlan] = useState<IndexPlan | null>(null);

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

  // Fetch the index plan on mount and whenever folders change. Refresh
  // again whenever the ingest poll transitions from running → idle, so
  // the "X files left to index" line follows reality. Server caches for
  // 10s; spamming this endpoint mid-poll is cheap.
  const refreshPlan = useCallback(async () => {
    try {
      const p = await getIndexPlan();
      setPlan(p);
    } catch (e) {
      // Plan failures are non-fatal — fall back to silent (no grand
      // total banner); the rest of the tab still works.
      console.warn("[settings] /index/plan failed:", e);
    }
  }, []);
  useEffect(() => {
    void refreshPlan();
  }, [refreshPlan, folders?.length]);
  // Re-fetch after each ingest job ends. We watch `done` (server flips
  // it true after the finally block) — the dependency on `running`
  // alone would miss the transition because by the time the next poll
  // tick fires, `running` is already false and `done` true.
  const ingestDone = ingest?.done ?? false;
  useEffect(() => {
    if (ingestDone) {
      void refreshPlan();
    }
  }, [ingestDone, refreshPlan]);

  // The backend auto-fires `_do_sync()` from POST /settings/folders now,
  // so we no longer need a separate POST /ingest call here. We still
  // notify the parent so it starts polling /ingest/status and surfacing
  // progress in the UI.
  const handlePickFolder = useCallback(async () => {
    setShowAddMenu(false);
    setError(null);
    try {
      const path = await pickFolder();
      if (!path) return;
      await addFolder(path);
      onIngestStarted();
      refreshFolders();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [onIngestStarted, refreshFolders]);

  const handlePickFile = useCallback(async () => {
    setShowAddMenu(false);
    setError(null);
    try {
      const path = await pickFile();
      if (!path) return;
      await addFolder(path);
      onIngestStarted();
      refreshFolders();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [onIngestStarted, refreshFolders]);

  const handleSync = useCallback(async () => {
    setError(null);
    try {
      await runSync();
      onIngestStarted();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [onIngestStarted]);

  const handleReindexConfirm = useCallback(async () => {
    setShowReindexConfirm(false);
    setError(null);
    try {
      await runReindex();
      onIngestStarted();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [onIngestStarted]);

  const handleToggle = useCallback(async (path: string, enabled: boolean) => {
    setError(null);
    try {
      await patchFolder({ path, enabled });
      // Backend auto-fires sync when `enabled` flips — start polling so
      // the user sees the orphan-cleanup pass (or the new-files pass)
      // light up the status pill.
      onIngestStarted();
      refreshFolders();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [onIngestStarted, refreshFolders]);

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
      // Backend auto-fires sync on remove (orphan cleanup runs at the
      // end of _do_sync) — start polling so the user sees the count
      // drop in real time.
      onIngestStarted();
      refreshFolders();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [removeTarget, onIngestStarted, refreshFolders]);

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
      setError((e as Error).message);
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
        setError((e as Error).message);
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
          <div className="data-tab__empty-glyph" aria-hidden="true">📁</div>
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
      {error && <ErrorBanner message={error} />}
      <PlanSummary plan={plan} ingest={ingest} />
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
  return (
    <header className="data-tab__header">
      <div className="data-tab__header-text">
        <h1 className="data-tab__title">Data</h1>
        <p className="data-tab__subtitle">
          Files and folders Magpie reads to understand your work. Nothing
          leaves your machine.
        </p>
      </div>
      <div className="data-tab__header-actions">
        <button
          type="button"
          className="data-tab__btn data-tab__btn--ghost"
          onClick={onSync}
          disabled={syncDisabled}
          title="Pick up new files and drop removed ones."
        >
          ↻ Sync
        </button>
        <button
          type="button"
          className="data-tab__btn data-tab__btn--warn"
          onClick={onReindex}
          disabled={syncDisabled}
          title="Rebuild from scratch. Slow but thorough."
        >
          ⟳ Reindex
        </button>
        <div className="data-tab__add-menu-wrap" ref={addMenuRef}>
          <button
            type="button"
            className="data-tab__btn data-tab__btn--primary"
            onClick={() => setShowAddMenu(!showAddMenu)}
          >
            + Add folder / file ▾
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
      ⚠ {message}
    </div>
  );
}

/** Single-line summary above the folder list:
 *   "12,431 files across 4 folders · 1,234 still to index"
 *   "12,431 files across 4 folders · all caught up"
 *   "Scanning your folders…"  (during scan phase, no plan yet)
 *
 * The summary is informational — buttons live in the header, not here.
 * Hidden entirely when the plan endpoint hasn't responded yet AND
 * there's no scan in progress (avoids a flash of empty content). */
function PlanSummary({
  plan,
  ingest,
}: {
  plan: IndexPlan | null;
  ingest: IngestStatus | null;
}) {
  const scanning = ingest?.phase === "scanning";
  if (scanning) {
    return (
      <div className="data-tab__plan-summary data-tab__plan-summary--scanning">
        Scanning your folders…
      </div>
    );
  }
  if (!plan || plan.folders.length === 0) return null;
  const enabled = plan.folders.filter((f) => f.enabled).length;
  const totalLabel = plan.grand_total.toLocaleString();
  const folderLabel = enabled === 1 ? "1 folder" : `${enabled} folders`;
  const tail =
    plan.grand_remaining > 0
      ? `${plan.grand_remaining.toLocaleString()} still to index`
      : "all caught up";
  return (
    <div className="data-tab__plan-summary">
      {totalLabel} {plan.grand_total === 1 ? "file" : "files"} across{" "}
      {folderLabel} · {tail}
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
          {target?.display_name || target?.path.split("/").pop() || target?.path}
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
          {open ? "▼" : "▶"}
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
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
      {addInput || (
        <button type="button" className="exclusion-list__add-btn" onClick={onAddClick}>
          + Add path…
        </button>
      )}
    </div>
  );
}
