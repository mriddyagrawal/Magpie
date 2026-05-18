/**
 * FolderRow — one card in the Data tab's folder list. Renders all
 * states (ready / understanding / paused / error) and the in-progress
 * sub-state with Pause + Cancel buttons.
 *
 * State rules:
 *   - If `isIngesting` (the parent decides via ingest.path matching),
 *     show "understanding" pill + progress bar + Pause/Cancel.
 *   - Else if `!folder.enabled`, show "paused" pill + dimmed body.
 *   - Else show "ready" pill + stats line.
 *
 * Per-row Pause/Cancel route to the global `POST /ingest/stop` per
 * the resolved design decision — v1 has only one running indexing
 * job at a time, so per-folder pause = global pause.
 */

import type { FolderEntry, IngestStatus } from "../../api";

interface Props {
  folder: FolderEntry;
  /** True iff the running ingest job's path matches this folder. */
  isIngesting: boolean;
  ingest: IngestStatus | null;
  onToggle: (path: string, enabled: boolean) => void;
  onRemove: (path: string) => void;
  onResync: (path: string) => void;
  onStop: () => void;
  onReveal: (path: string) => void;
}

export function FolderRow({
  folder,
  isIngesting,
  ingest,
  onToggle,
  onRemove,
  onResync,
  onStop,
  onReveal,
}: Props) {
  const displayName = folder.display_name?.trim() || basenameOf(folder.path);
  const tildePath = tildify(folder.path);
  const status: "ready" | "understanding" | "paused" | "error" =
    isIngesting ? "understanding" :
    !folder.enabled ? "paused" :
    "ready";

  const pct = isIngesting && ingest && ingest.files_total > 0
    ? Math.min(100, Math.round((ingest.files_done / ingest.files_total) * 100))
    : 0;

  return (
    <article className={`folder-row folder-row--${status}`}>
      <div className="folder-row__main">
        <div className="folder-row__icon" aria-hidden="true">
          {fileIconFor(folder)}
        </div>
        <div className="folder-row__body">
          <div className="folder-row__name-line">
            <h3 className="folder-row__name">{displayName}</h3>
            <StatusPill status={status} />
          </div>
          <div className="folder-row__path">{tildePath}</div>
          {isIngesting ? (
            <InProgressBlock ingest={ingest} pct={pct} onStop={onStop} />
          ) : (
            <StatsLine folder={folder} />
          )}
        </div>
        <div className="folder-row__actions">
          <Toggle
            checked={folder.enabled}
            disabled={isIngesting}
            onChange={(v) => onToggle(folder.path, v)}
            label={`${folder.enabled ? "Pause" : "Resume"} indexing of ${displayName}`}
          />
          <IconButton title="Reveal in Finder" onClick={() => onReveal(folder.path)}>
            📂
          </IconButton>
          <IconButton title="Re-sync this folder" onClick={() => onResync(folder.path)}>
            ↻
          </IconButton>
          <IconButton title="Remove" onClick={() => onRemove(folder.path)}>
            …
          </IconButton>
        </div>
      </div>
    </article>
  );
}

function StatusPill({ status }: { status: "ready" | "understanding" | "paused" | "error" }) {
  const label =
    status === "ready" ? "ready" :
    status === "understanding" ? "understanding" :
    status === "paused" ? "paused" :
    "error";
  return (
    <span className={`folder-row__pill folder-row__pill--${status}`}>
      <span className="folder-row__pill-dot" aria-hidden="true" />
      {label}
    </span>
  );
}

function StatsLine({ folder }: { folder: FolderEntry }) {
  const parts: string[] = [];
  parts.push(`${folder.files.toLocaleString()} ${folder.files === 1 ? "file" : "files"}`);
  parts.push(formatSize(folder.size_bytes));
  if (folder.last_read_at) {
    parts.push(`read ${formatRelative(folder.last_read_at)}`);
  } else {
    parts.push("not yet read");
  }
  return <div className="folder-row__stats">{parts.join(" · ")}</div>;
}

function InProgressBlock({
  ingest,
  pct,
  onStop,
}: {
  ingest: IngestStatus | null;
  pct: number;
  onStop: () => void;
}) {
  return (
    <div className="folder-row__progress">
      <div className="folder-row__progress-line">
        <span className="folder-row__progress-current">
          {ingest?.current_file
            ? truncatePath(ingest.current_file)
            : "Scanning…"}
        </span>
        <span className="folder-row__progress-counts">
          {ingest && ingest.files_total > 0 ? (
            <>
              {ingest.files_done.toLocaleString()} of{" "}
              {ingest.files_total.toLocaleString()} files
            </>
          ) : null}
        </span>
        <span className="folder-row__progress-pct">{pct}%</span>
      </div>
      <div className="folder-row__progress-bar">
        <div className="folder-row__progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="folder-row__progress-buttons">
        <button type="button" className="folder-row__progress-btn" onClick={onStop}>
          ⏸ Pause
        </button>
        <button type="button" className="folder-row__progress-btn" onClick={onStop}>
          ✕ Cancel
        </button>
      </div>
    </div>
  );
}

function Toggle({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      className={`toggle-switch ${checked ? "is-on" : ""}`}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span className="toggle-switch__knob" aria-hidden="true" />
    </button>
  );
}

function IconButton({
  title,
  onClick,
  children,
}: {
  title: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className="folder-row__icon-btn"
      title={title}
      aria-label={title}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function basenameOf(path: string): string {
  return path.replace(/\/+$/, "").split("/").pop() || path;
}

function tildify(path: string): string {
  // Best-effort: replace `/Users/<name>/` with `~/`. Won't catch
  // every shell expansion but covers the common case.
  return path.replace(/^\/Users\/[^/]+\//, "~/");
}

function fileIconFor(folder: FolderEntry): string {
  // Folders → 📁; single .pdf / .csv / etc → matching glyph.
  const lower = folder.path.toLowerCase();
  if (lower.endsWith(".pdf")) return "📄";
  if (lower.endsWith(".csv") || lower.endsWith(".tsv")) return "📊";
  if (lower.endsWith(".md") || lower.endsWith(".txt")) return "📝";
  return "📁";
}

function formatSize(bytes: number): string {
  if (bytes === 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const diff = Date.now() - then;
  const sec = Math.round(diff / 1000);
  if (sec < 60) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} h ago`;
  const days = Math.round(hr / 24);
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days} days ago`;
  return new Date(iso).toLocaleDateString();
}

function truncatePath(p: string): string {
  if (p.length <= 44) return p;
  return `…${p.slice(-42)}`;
}
