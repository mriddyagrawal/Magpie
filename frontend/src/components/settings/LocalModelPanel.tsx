/**
 * LocalModelPanel — the "Local model files" section of Search & AI.
 *
 * Renders the state machine behind the /local/* API:
 *
 *   not_installed → one "Download (~N GB)" button, honest about size
 *   downloading   → per-half progress (LLM vs visual), byte counts, Cancel
 *   ready         → what's on disk + a two-step Remove
 *   error         → the message + Try again (partial downloads resume free)
 *
 * The two halves are shown separately on purpose: the LLM half (~2.8 GB) is
 * what the Local provider toggle needs; the visual half (0.9–7.3 GB
 * depending on machine) is used by indexing regardless of provider. Lumping
 * them into one bar would hide which one a user is waiting on.
 *
 * Self-contained: owns its own 1s poll while a download runs, following the
 * SettingsWindow ingest-poll rhythm. Parent passes `refreshProviders` so the
 * Local provider card's disabled state updates the moment install finishes.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, Download, HardDrive, X } from "lucide-react";
import {
  cancelLocalInstall,
  deleteLocalModels,
  friendlyError,
  getLocalStatus,
  startLocalInstall,
} from "../../api";
import type { LocalInstallStatus } from "../../api";

const POLL_MS = 1000;

/** "2.8 GB" / "556 MB" / "~" for unknown. Display-grade only. */
function fmtBytes(n: number | null | undefined): string {
  if (n == null || n <= 0) return "~";
  const gb = n / 1024 ** 3;
  if (gb >= 0.95) return `${gb.toFixed(gb >= 10 ? 0 : 1)} GB`;
  return `${Math.round(n / 1024 ** 2)} MB`;
}

const PHASE_LABEL: Record<string, string> = {
  starting: "Starting…",
  binary: "Getting the inference engine…",
  llm_weights: "Downloading the answer model…",
  mmproj: "Downloading the vision add-on…",
  visual_adapter: "Downloading the visual search model…",
  visual_base: "Downloading the visual search model…",
};

export function LocalModelPanel({
  refreshProviders,
}: {
  refreshProviders: () => void;
}) {
  const [status, setStatus] = useState<LocalInstallStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const wasRunning = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const s = await getLocalStatus();
      setStatus(s);
      // Fire the provider-card refresh exactly once, on the running→idle
      // edge — that is the moment `downloaded` may have flipped.
      if (wasRunning.current && !s.running) refreshProviders();
      wasRunning.current = s.running;
    } catch (e) {
      setError(friendlyError(e));
    }
  }, [refreshProviders]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!status?.running) return;
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [status?.running, refresh]);

  // Two-step remove: first click arms, second click (within 4s) fires.
  useEffect(() => {
    if (!confirmingRemove) return;
    const id = setTimeout(() => setConfirmingRemove(false), 4000);
    return () => clearTimeout(id);
  }, [confirmingRemove]);

  const handleDownload = useCallback(async () => {
    setError(null);
    try {
      await startLocalInstall();
      await refresh();
    } catch (e) {
      setError(friendlyError(e));
    }
  }, [refresh]);

  const handleCancel = useCallback(async () => {
    try {
      await cancelLocalInstall();
      await refresh();
    } catch (e) {
      setError(friendlyError(e));
    }
  }, [refresh]);

  const handleRemove = useCallback(async () => {
    if (!confirmingRemove) {
      setConfirmingRemove(true);
      return;
    }
    setConfirmingRemove(false);
    try {
      await deleteLocalModels("all");
      await refresh();
      refreshProviders();
    } catch (e) {
      setError(friendlyError(e));
    }
  }, [confirmingRemove, refresh, refreshProviders]);

  if (status === null) return null; // first fetch pending — render nothing

  const totalNeeded =
    (status.llm.ready ? 0 : status.llm.bytes_total ?? 0) +
    (status.visual.ready ? 0 : status.visual.bytes_total);
  const onDisk = status.llm.bytes_done + status.visual.bytes_done;

  return (
    <section className="local-model-panel" aria-live="polite">
      <header className="local-model-panel__header">
        <HardDrive size={14} aria-hidden="true" />
        <span className="local-model-panel__title">Local model files</span>
      </header>

      {(error || status.error) && (
        <div className="local-model-panel__error">
          <AlertTriangle size={13} aria-hidden="true" /> {error ?? status.error}
        </div>
      )}

      {status.running ? (
        <div className="local-model-panel__body">
          <p className="local-model-panel__phase">
            {PHASE_LABEL[status.phase ?? ""] ?? "Downloading…"}
            <span className="local-model-panel__phase-hint">
              {" "}
              — safe to cancel, downloads resume where they left off
            </span>
          </p>
          <HalfProgress
            label="Answering (local AI)"
            done={status.llm.bytes_done}
            total={status.llm.bytes_total}
            ready={status.llm.ready}
          />
          <HalfProgress
            label="Visual search (scans & photos)"
            done={status.visual.bytes_done}
            total={status.visual.bytes_total}
            ready={status.visual.ready}
          />
          <div className="local-model-panel__actions">
            <button
              type="button"
              className="folder-row__progress-btn"
              onClick={handleCancel}
            >
              <X size={12} aria-hidden="true" /> Cancel
            </button>
          </div>
        </div>
      ) : status.state === "ready" ? (
        <div className="local-model-panel__body local-model-panel__body--ready">
          <p className="local-model-panel__ready-line">
            <Check size={13} aria-hidden="true" /> Everything is downloaded —{" "}
            {fmtBytes(onDisk)} on disk. Local answering and visual search are
            ready.
          </p>
          <div className="local-model-panel__actions">
            <button
              type="button"
              className={`local-model-panel__remove ${confirmingRemove ? "is-armed" : ""}`}
              onClick={handleRemove}
            >
              {confirmingRemove
                ? `Really remove? Frees ${fmtBytes(onDisk)}`
                : "Remove downloads…"}
            </button>
          </div>
        </div>
      ) : (
        <div className="local-model-panel__body">
          <p className="local-model-panel__pitch">
            {status.llm.ready
              ? "Local answering is ready. The visual search model still needs a download."
              : "Answer questions without anything leaving your machine. One download, no account."}
            {status.cancelled && " Your earlier progress was kept."}
          </p>
          <div className="local-model-panel__actions">
            <button
              type="button"
              className="local-model-panel__download"
              onClick={handleDownload}
            >
              <Download size={13} aria-hidden="true" />
              {status.state === "error" ? "Try again" : "Download"}
              {totalNeeded > 0 && ` (${fmtBytes(totalNeeded)})`}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function HalfProgress({
  label,
  done,
  total,
  ready,
}: {
  label: string;
  done: number;
  total: number | null;
  ready: boolean;
}) {
  const pct =
    ready ? 100 : total && total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <div className="local-model-panel__half">
      <div className="local-model-panel__half-line">
        <span className="local-model-panel__half-label">
          {ready && <Check size={12} aria-hidden="true" />} {label}
        </span>
        <span className="local-model-panel__half-bytes">
          {ready ? "done" : `${fmtBytes(done)} of ${fmtBytes(total)}`}
        </span>
        {!ready && total != null && (
          <span className="folder-row__progress-pct">{pct}%</span>
        )}
      </div>
      <div className="folder-row__progress-bar">
        {!ready && total == null ? (
          <div className="folder-row__progress-fill folder-row__progress-fill--indeterminate" />
        ) : (
          <div className="folder-row__progress-fill" style={{ width: `${pct}%` }} />
        )}
      </div>
    </div>
  );
}
