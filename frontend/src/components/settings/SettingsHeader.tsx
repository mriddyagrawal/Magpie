/**
 * SettingsHeader — top strip across the main content area. Shows the
 * ACTIVE SECTION name (like macOS System Settings' title bar shows the
 * pane you're in) plus a live status pill. The app name already lives
 * in the sidebar brand, so repeating "Magpie · Settings" here read as
 * clutter — the section name is the information that actually changes.
 *
 * The status pill mirrors the sidebar footer's health (Ready /
 * Understanding / Reconnecting …) so the user has a live indicator
 * regardless of which tab they're looking at.
 */

import type { IngestStatus } from "../../api";
import type { StatusResponse } from "../../types";
import type { SettingsTab } from "./SettingsSidebar";

interface Props {
  tab: SettingsTab;
  status: StatusResponse | null;
  ingest: IngestStatus | null;
}

const TAB_LABELS: Record<SettingsTab, string> = {
  "data": "Data",
  "search-ai": "Search & AI",
  "shortcut-app": "Shortcut & App",
};

export function SettingsHeader({ tab, status, ingest }: Props) {
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
      <h1 className="settings-header__section">{TAB_LABELS[tab]}</h1>
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
