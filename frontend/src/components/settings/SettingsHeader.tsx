/**
 * SettingsHeader — top strip across the main content area showing
 * `Magpie · Settings · ● <state>`. The status pill mirrors the
 * sidebar footer's health (Ready / Understanding / Reconnecting …)
 * so the user has a live indicator regardless of which tab they're
 * looking at.
 */

import type { IngestStatus } from "../../api";
import type { StatusResponse } from "../../types";

interface Props {
  status: StatusResponse | null;
  ingest: IngestStatus | null;
}

export function SettingsHeader({ status, ingest }: Props) {
  // Determine the dot state + label. Same priority as the ask bar's
  // StatusFooter: indexing > reconnecting > ready > booting.
  let dot: "ready" | "indexing" | "reconnecting" | "booting" = "booting";
  let label = "Starting…";
  if (ingest?.running) {
    dot = "indexing";
    label =
      ingest.files_total > 0
        ? `Understanding ${ingest.files_done.toLocaleString()} / ${ingest.files_total.toLocaleString()}`
        : "Understanding";
  } else if (status?.ready) {
    dot = "ready";
    label = "Ready";
  } else if (status !== null) {
    dot = "reconnecting";
    label = "Reconnecting…";
  }

  return (
    <header className="settings-header">
      <div className="settings-header__title">
        <span className="settings-header__title-app">Magpie</span>
        <span className="settings-header__title-sep">·</span>
        <span className="settings-header__title-section">Settings</span>
      </div>
      <div className="settings-header__pill">
        <span
          className={`settings-header__pill-dot settings-header__pill-dot--${dot}`}
          aria-hidden="true"
        />
        <span className="settings-header__pill-label">{label}</span>
      </div>
    </header>
  );
}
