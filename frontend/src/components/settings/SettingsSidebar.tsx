/**
 * SettingsSidebar — left rail with three nav entries + a status
 * footer pinned at the bottom. Used by SettingsWindow.tsx.
 *
 * The status footer shows `understood: N / provider: Local`. Acts as
 * a quiet operational indicator while the user pokes at settings —
 * they always know the corpus health without leaving the window.
 *
 * The Qdrant collection size used to live here too (`size: N MB`)
 * but was removed: it only reflected the `summaries` collection's
 * on-disk footprint, not the total Magpie-on-disk footprint
 * (fast_tier collection, summary markdown files, manifest, etc.),
 * which made the number misleading as a "how much space am I
 * using" indicator.
 */

import { Folder, Keyboard, Sparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { StatusResponse } from "../../types";

export type SettingsTab = "data" | "search-ai" | "shortcut-app";

interface Props {
  active: SettingsTab;
  onChange: (t: SettingsTab) => void;
  status: StatusResponse | null;
}

interface NavEntry {
  id: SettingsTab;
  label: string;
  icon: LucideIcon;
}

const NAV: NavEntry[] = [
  { id: "data",          label: "Data",            icon: Folder   },
  { id: "search-ai",     label: "Search & AI",     icon: Sparkles },
  { id: "shortcut-app",  label: "Shortcut & App",  icon: Keyboard },
];

export function SettingsSidebar({ active, onChange, status }: Props) {
  return (
    <aside className="settings-sidebar">
      <div className="settings-sidebar__header">
        <div className="settings-sidebar__brand">Magpie</div>
        <div className="settings-sidebar__brand-sub">SETTINGS</div>
      </div>
      <nav className="settings-sidebar__nav" aria-label="Settings sections">
        {NAV.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={`settings-sidebar__nav-item ${active === entry.id ? "is-active" : ""}`}
            onClick={() => onChange(entry.id)}
          >
            <span className="settings-sidebar__nav-icon" aria-hidden="true">
              <entry.icon size={15} strokeWidth={1.8} />
            </span>
            <span className="settings-sidebar__nav-label">{entry.label}</span>
          </button>
        ))}
      </nav>
      {/* Plain sentences, not a label:value debug table. Provider only
          — the model name is intentionally hidden from the user-facing
          surface (no-tech-leak: internal terms like "Gemma 4" never
          reach the UI). */}
      <div className="settings-sidebar__footer">
        <span className="settings-sidebar__footer-line">
          {status?.indexed_count != null
            ? `${status.indexed_count.toLocaleString()} ${status.indexed_count === 1 ? "file" : "files"} understood`
            : "Connecting…"}
        </span>
        {status?.provider && (
          <span className="settings-sidebar__footer-line">
            {status.provider === "cloud" ? "Cloud AI" : "On-device AI"}
          </span>
        )}
      </div>
    </aside>
  );
}
