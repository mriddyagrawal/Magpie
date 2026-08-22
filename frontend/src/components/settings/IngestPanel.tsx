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

import { Pause, X } from "lucide-react";
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

function headline(ingest: IngestStatus): string {
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
  onStop,
  showCurrentFile = true,
}: {
  ingest: IngestStatus | null;
  pct: number;
  onStop: () => void;
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
        <button type="button" className="folder-row__progress-btn" onClick={onStop}>
          <Pause size={12} aria-hidden="true" /> Pause
        </button>
        <button type="button" className="folder-row__progress-btn" onClick={onStop}>
          <X size={12} aria-hidden="true" /> Cancel
        </button>
      </div>
    </div>
  );
}

/** Global panel. Render only while `ingest.running`. */
export function IngestPanel({
  ingest,
  onStop,
}: {
  ingest: IngestStatus | null;
  onStop: () => void;
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
      <IngestProgressBody ingest={ingest} pct={ingestPct(ingest)} onStop={onStop} />
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
