/**
 * StatusFooter — universal bottom bar on the ask bar, shown in every
 * state per Specs/UI/ask_bar.md.
 *
 * Format:
 *   ● Ready · Local · Gemma 4 · 4,408 documents understood    Esc to dismiss
 *
 * Left side: status dot + health label + provider + model + document
 * count. Right side: state-specific keyboard hints.
 *
 * The footer is the user's persistent "is Magpie healthy?" indicator
 * and Magpie's only chrome — no header bar, no toolbar.
 *
 * Reads health/document count from the existing GET /status endpoint;
 * polls every 5s while visible so user-visible counts stay live as
 * indexing progresses. Gracefully degrades if the sidecar is down
 * (status dot turns red, label switches to "Reconnecting…").
 */

import { useEffect, useState } from "react";
import { getStatus } from "../api";
import type { ViewKind } from "./viewState";

interface Props {
  view: ViewKind;
  booting: boolean;
  /** Live indexing snapshot from /ingest/status (null when idle). */
  ingestRunning: boolean;
  ingestFilesDone: number;
  ingestFilesTotal: number;
}

interface FooterStatus {
  ready: boolean;
  indexed_count: number;
  /** Friendly health label. Computed from `ready` + `indexedCount`. */
  health: string;
  /** "ready" | "booting" | "reconnecting" | "indexing" — drives dot color. */
  dot: "ready" | "booting" | "reconnecting" | "indexing";
}

const STATUS_POLL_MS = 5_000;

export function StatusFooter({
  view,
  booting,
  ingestRunning,
  ingestFilesDone,
  ingestFilesTotal,
}: Props) {
  const [status, setStatus] = useState<FooterStatus>({
    ready: false,
    indexed_count: 0,
    health: "Starting Magpie…",
    dot: "booting",
  });

  // Periodic status refresh. The boot poll in MagpieWindow handles the
  // initial /healthz; once ready, this one keeps the document count
  // current as background indexing finishes new files.
  useEffect(() => {
    if (booting) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const s = await getStatus();
        if (cancelled) return;
        setStatus({
          ready: s.ready,
          indexed_count: s.indexed_count,
          health: s.ready ? "Ready" : "Reconnecting…",
          dot: s.ready ? "ready" : "reconnecting",
        });
      } catch {
        if (cancelled) return;
        setStatus((prev) => ({
          ...prev,
          health: "Reconnecting…",
          dot: "reconnecting",
        }));
      }
    };
    tick();
    const id = setInterval(tick, STATUS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [booting]);

  // Indexing overrides the steady-state health label so the user sees
  // "● Understanding 423 / 1,481 files" while a sync is in flight.
  let dot = booting ? "booting" : status.dot;
  let label = booting ? "Starting Magpie…" : status.health;
  if (ingestRunning && !booting) {
    dot = "indexing";
    label =
      ingestFilesTotal > 0
        ? `Understanding ${ingestFilesDone.toLocaleString()} / ${ingestFilesTotal.toLocaleString()} files`
        : "Understanding…";
  }

  // Provider + model are surfaced from /status when wired; for v1 the
  // backend doesn't yet return them, so we lean on a static label.
  // (Will route through /settings/search in PR 5 once the frontend
  // settings tab consumes that endpoint.)
  const providerLabel = "Local";
  const modelLabel = "Gemma 4";
  const docCount = status.indexed_count.toLocaleString();

  return (
    <footer className="status-footer">
      <div className="status-footer__left">
        <span
          className={`status-footer__dot status-footer__dot--${dot}`}
          aria-hidden="true"
        />
        <span className="status-footer__label">{label}</span>
        <Sep />
        <span className="status-footer__meta">{providerLabel}</span>
        <Sep />
        <span className="status-footer__meta">{modelLabel}</span>
        {!booting && (
          <>
            <Sep />
            <span className="status-footer__meta">
              {docCount} documents understood
            </span>
          </>
        )}
      </div>
      <div className="status-footer__right">
        <KeyboardHints view={view} />
      </div>
    </footer>
  );
}

function Sep() {
  return (
    <span className="status-footer__sep" aria-hidden="true">
      ·
    </span>
  );
}

function KeyboardHints({ view }: { view: ViewKind }) {
  switch (view) {
    case "resting":
      return <span><Kbd>Esc</Kbd> to dismiss</span>;
    case "typing":
      return (
        <span>
          <Kbd>↑↓</Kbd> navigate <Sep /> <Kbd>⏎</Kbd> open <Sep />{" "}
          <Kbd>Esc</Kbd> close
        </span>
      );
    case "retrieving":
      return <span><Kbd>Esc</Kbd> cancel</span>;
    case "answering":
      return (
        <span>
          <Kbd>⌘C</Kbd> copy <Sep /> <Kbd>Esc</Kbd> stop
        </span>
      );
    case "not_found":
      return <span><Kbd>Esc</Kbd> close</span>;
  }
}

function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="status-footer__kbd">{children}</kbd>;
}
