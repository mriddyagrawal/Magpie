/**
 * StatusFooter — universal bottom bar on the ask bar, shown in every
 * state per Specs/UI/ask_bar.md.
 *
 * Format:
 *   ● Ready   Local   4,408 documents understood    Esc to dismiss
 *
 * Left side: status dot + health label + provider + document count,
 * separated by whitespace (no "·" glyphs — Spotlight style). Right
 * side: state-specific keyboard hints. The model name is deliberately
 * NOT shown (no-tech-leak product principle — internal names like
 * "Gemma 4" never reach the user-facing surface).
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
  /** "local" | "cloud" | "" (unknown until first /status lands). */
  provider: string;
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
    provider: "",
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
        // Two distinct unhealthy states, named for the user:
        //  - engine answered but isn't ready → its search database is
        //    still coming up ("Starting search engine…")
        //  - engine didn't answer at all → we're retrying the
        //    connection ("Can't reach engine — retrying…")
        setStatus({
          ready: s.ready,
          indexed_count: s.indexed_count,
          provider: s.provider ?? "",
          health: s.ready ? "Ready" : "Starting search engine…",
          dot: s.ready ? "ready" : "booting",
        });
      } catch {
        if (cancelled) return;
        setStatus((prev) => ({
          ...prev,
          health: "Can't reach engine — retrying…",
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

  // Live provider from /status — same wording as the Settings sidebar
  // so the vocabulary stays consistent. The model name is intentionally
  // never rendered (no-tech-leak).
  const providerLabel =
    status.provider === "" ? "" :
    status.provider === "cloud" ? "Cloud AI" : "On-device AI";
  const docCount = status.indexed_count.toLocaleString();

  return (
    <footer className="status-footer">
      <div className="status-footer__left">
        <span className="status-footer__state">
          <span
            className={`status-footer__dot status-footer__dot--${dot}`}
            aria-hidden="true"
          />
          <span className="status-footer__label">{label}</span>
        </span>
        {providerLabel && (
          <span className="status-footer__meta">{providerLabel}</span>
        )}
        {!booting && (
          <span className="status-footer__meta">
            {docCount} documents understood
          </span>
        )}
      </div>
      <div className="status-footer__right">
        <KeyboardHints view={view} />
      </div>
    </footer>
  );
}

// Platform-correct modifier key: ⌘ is meaningless on Windows/Linux.
const IS_MAC =
  typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

function Hint({ keys, label }: { keys: string; label: string }) {
  return (
    <span className="status-footer__hint">
      <kbd className="status-footer__kbd">{keys}</kbd> {label}
    </span>
  );
}

function KeyboardHints({ view }: { view: ViewKind }) {
  switch (view) {
    case "resting":
      return <Hint keys="Esc" label="to dismiss" />;
    case "typing":
      return (
        <>
          <Hint keys="↑↓" label="navigate" />
          <Hint keys="⏎" label="open" />
          <Hint keys="Esc" label="close" />
        </>
      );
    case "retrieving":
      return <Hint keys="Esc" label="cancel" />;
    case "answering":
      return (
        <>
          <Hint keys={IS_MAC ? "⌘C" : "Ctrl+C"} label="copy" />
          <Hint keys="Esc" label="stop" />
        </>
      );
    case "not_found":
      return <Hint keys="Esc" label="close" />;
  }
}
