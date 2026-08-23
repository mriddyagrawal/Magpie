/**
 * IngestPanel — the always-visible "Magpie is reading your files right now"
 * banner at the top of the Data tab, plus the shared progress body that the
 * per-folder rows reuse.
 *
 * Why this exists: `_ingest_state.path` on the server moves as the walker
 * steps from root to root, so a folder row only lights up while its own root
 * is the current one. That left three windows with no feedback at all —
 * before the first root is reached (the scan, which on a big tree is the
 * longest stretch), during end-of-run orphan cleanup, and the very first
 * index when the user has no folder rows to look at yet. This panel is keyed
 * off `running` alone, so it covers all of them.
 *
 * Phase matters. During "scanning" there is no file count yet, so showing
 * "0 of 0 files · 0%" reads as a hang. That phase gets an indeterminate bar
 * and honest copy instead.
 */

import { Pause, Play, X } from "lucide-react";
import type { IngestStatus } from "../../api";

/** True while the walker is still enumerating candidates and has no totals.
 *  Falls back to a count check when `phase` is absent (older sidecar). */
export function isScanning(ingest: IngestStatus | null): boolean {
  if (!ingest) return false;
  if (ingest.phase) return ingest.phase === "scanning";
  return ingest.files_total === 0;
}

/** Percent complete, floored at 0 and capped at 100. Meaningless while
 *  scanning — callers should not render it then. */
export function ingestPct(ingest: IngestStatus | null): number {
  if (!ingest || ingest.files_total <= 0) return 0;
  return Math.min(100, Math.round((ingest.files_done / ingest.files_total) * 100));
}

/** True in the brief window after the user pressed Pause/Cancel while
 *  in-flight file attempts are aborted (sub-second to a few seconds). */
export function isStopping(ingest: IngestStatus | null): boolean {
  return ingest?.phase === "stopping";
}

/** True when a paused run has fully drained: progress is preserved and
 *  Resume (= a plain sync) continues from where it stopped. */
export function isPaused(ingest: IngestStatus | null): boolean {
  return Boolean(
    ingest && !ingest.running && ingest.stopped && ingest.stop_kind === "pause",
  );
}

function headline(ingest: IngestStatus): string {
  if (isStopping(ingest)) {
    return ingest.stop_kind === "pause" ? "Pausing…" : "Stopping…";
  }
  if (isScanning(ingest)) return "Looking for files to read…";
  return ingest.kind === "reindex"
    ? "Rebuilding your index"
    : "Understanding your files";
}

/**
 * The progress body: counts line, bar, current file, elapsed/ETA, buttons.
 * Shared verbatim between the global panel and each folder row so the two can
 * never drift apart. Keeps the existing `folder-row__progress*` class names —
 * they are already styled and are not row-specific in any meaningful way.
 */
export function IngestProgressBody({
  ingest,
  pct,
  onPause,
  onCancel,
  showCurrentFile = true,
}: {
  ingest: IngestStatus | null;
  pct: number;
  /** Pause: drain in-flight files, keep progress, offer Resume. Frees the
   *  machine so the user can ask questions mid-index. */
  onPause: () => void;
  /** Cancel: drain in-flight files and end the run. */
  onCancel: () => void;
  showCurrentFile?: boolean;
}) {
  const scanning = isScanning(ingest);
  const elapsed = ingest?.elapsed_s ?? null;
  // ETA = time-so-far projected across the remaining fraction. Only once we
  // have real per-file progress, otherwise it swings wildly during the scan.
  const etaSeconds =
    !scanning && elapsed !== null && pct > 0 && pct < 100
      ? Math.max(0, Math.round((elapsed / pct) * (100 - pct)))
      : null;

  return (
    <div className="folder-row__progress">
      <div className="folder-row__progress-line">
        <span className="folder-row__progress-current">
          {showCurrentFile && ingest?.current_file
            ? truncatePath(ingest.current_file)
            : scanning
              ? "Counting files…"
              : "Working…"}
        </span>
        <span className="folder-row__progress-counts">
          {scanning ? (
            "counting…"
          ) : ingest && ingest.files_total > 0 ? (
            <>
              {ingest.files_done.toLocaleString()} of{" "}
              {ingest.files_total.toLocaleString()} files
            </>
          ) : null}
        </span>
        {/* No percentage during the scan — there is no denominator yet. */}
        {!scanning && <span className="folder-row__progress-pct">{pct}%</span>}
      </div>
      <div className="folder-row__progress-bar">
        {scanning ? (
          <div className="folder-row__progress-fill folder-row__progress-fill--indeterminate" />
        ) : (
          <div
            className="folder-row__progress-fill"
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      {elapsed !== null && (
        <div className="folder-row__progress-time">
          <span>{formatDuration(elapsed)} elapsed</span>
          {etaSeconds !== null && <span>~{formatDuration(etaSeconds)} left</span>}
        </div>
      )}
      <div className="folder-row__progress-buttons">
        {isStopping(ingest) ? (
          <button type="button" className="folder-row__progress-btn" disabled>
            {ingest?.stop_kind === "pause" ? (
              <><Pause size={12} aria-hidden="true" /> Pausing…</>
            ) : (
              <><X size={12} aria-hidden="true" /> Stopping…</>
            )}
          </button>
        ) : (
          <>
            <button type="button" className="folder-row__progress-btn" onClick={onPause}>
              <Pause size={12} aria-hidden="true" /> Pause
            </button>
            <button type="button" className="folder-row__progress-btn" onClick={onCancel}>
              <X size={12} aria-hidden="true" /> Cancel
            </button>
          </>
        )}
      </div>
    </div>
  );
}

/** Global panel. Render only while `ingest.running`. */
export function IngestPanel({
  ingest,
  onPause,
  onCancel,
}: {
  ingest: IngestStatus | null;
  onPause: () => void;
  onCancel: () => void;
}) {
  if (!ingest?.running) return null;
  const scanning = isScanning(ingest);

  return (
    <section
      className="ingest-panel"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="ingest-panel__head">
        <span
          className={`ingest-panel__dot ingest-panel__dot--${scanning ? "scanning" : "indexing"}`}
          aria-hidden="true"
        />
        <h2 className="ingest-panel__title">{headline(ingest)}</h2>
      </div>
      <IngestProgressBody
        ingest={ingest}
        pct={ingestPct(ingest)}
        onPause={onPause}
        onCancel={onCancel}
      />
    </section>
  );
}

/** Shown after a paused run has drained: progress is kept, questions work
 *  (that's the point of pausing), and Resume finishes the remaining files.
 *  Render when `isPaused(ingest)`. */
export function PausedPanel({
  ingest,
  onResume,
}: {
  ingest: IngestStatus | null;
  onResume: () => void;
}) {
  if (!isPaused(ingest)) return null;
  const counts =
    ingest && ingest.files_total > 0
      ? `${ingest.files_done.toLocaleString()} of ${ingest.files_total.toLocaleString()} files read so far`
      : "Progress saved";

  return (
    <section className="ingest-panel" aria-live="polite">
      <div className="ingest-panel__head">
        <span className="ingest-panel__dot ingest-panel__dot--scanning" aria-hidden="true" />
        <h2 className="ingest-panel__title">Indexing paused</h2>
      </div>
      <div className="folder-row__progress">
        <div className="folder-row__progress-line">
          <span className="folder-row__progress-current">
            {counts} — everything read so far is searchable. Resume anytime to
            finish the rest.
          </span>
        </div>
        <div className="folder-row__progress-buttons">
          <button type="button" className="folder-row__progress-btn" onClick={onResume}>
            <Play size={12} aria-hidden="true" /> Resume
          </button>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Helpers — shared with FolderRow, which imports them from here.
// ---------------------------------------------------------------------------

export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return `${m}m ${rem}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function truncatePath(p: string): string {
  if (p.length <= 44) return p;
  return `…${p.slice(-42)}`;
}
