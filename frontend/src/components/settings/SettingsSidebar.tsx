/**
 * SettingsSidebar — left rail with three nav entries + a status
 * footer pinned at the bottom. Used by SettingsWindow.tsx.
 *
 * The status footer mirrors the same numbers shown on the ask bar's
 * StatusFooter: `understood: N / size: N MB / provider: Local · Gemma 4`.
 * Acts as a quiet operational indicator while the user pokes at
 * settings — they always know the corpus health without leaving
 * the window.
 */

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
  icon: string; // glyph; designer can swap to SVG later
}

const NAV: NavEntry[] = [
  { id: "data",          label: "Data",            icon: "📁" },
  { id: "search-ai",     label: "Search & AI",     icon: "≡"  },
  { id: "shortcut-app",  label: "Shortcut & App",  icon: "⌨"  },
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
              {entry.icon}
            </span>
            <span className="settings-sidebar__nav-label">{entry.label}</span>
          </button>
        ))}
      </nav>
      <div className="settings-sidebar__footer">
        <SidebarFooterRow
          label="understood"
          value={status?.indexed_count != null ? status.indexed_count.toLocaleString() : "—"}
        />
        <SidebarFooterRow
          label="size"
          value={status?.size_mb != null ? `${status.size_mb.toLocaleString()} MB` : "—"}
        />
        {/* Provider only — the model name is intentionally hidden from
            the user-facing surface. Internal terms ("Gemma 4",
            "unsloth/gemma-...") shouldn't leak into the UI per the
            no-tech-leak product principle. */}
        <SidebarFooterRow
          label="provider"
          value={status?.provider ? capitalize(status.provider) : "—"}
        />
      </div>
    </aside>
  );
}

function SidebarFooterRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="settings-sidebar__footer-row">
      <span className="settings-sidebar__footer-label">{label}:</span>
      <span className="settings-sidebar__footer-value">{value}</span>
    </div>
  );
}

function capitalize(s: string): string {
  return s.length > 0 ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}
