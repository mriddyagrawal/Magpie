/**
 * ShortcutAppTab — the Settings → Shortcut & App tab.
 *
 * Layout (per Specs/UI/settings_window.md):
 *   - Title + subtitle
 *   - Global shortcut: chips + Change… + Use default. Shortcut
 *     recorder shows "Press a shortcut combination…" until the
 *     user releases a valid one (must include a modifier).
 *   - Theme: 3-button segmented control (Match system / Light / Dark)
 *   - Accent color: 4 radio swatches (Ink / Amber / Jade / Rose)
 *   - Toggles: Launch at login, Show in menu bar
 *   - Dropdown: Default action on activation (Empty ask bar / Show last query)
 *   - About card: version + "Check for updates" (no-op stub for v1)
 *
 * Theme + accent live-apply: changing Theme sets
 * `document.documentElement.dataset.theme` immediately so the user
 * sees the swap before the PATCH lands. Accent updates `--accent-*`
 * CSS vars on the root.
 */

import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  isRegistered as isShortcutRegistered,
  register as registerShortcut,
  unregister as unregisterShortcut,
} from "@tauri-apps/plugin-global-shortcut";
import {
  getAppSettings,
  getShortcut,
  patchAppSettings,
  putShortcut,
} from "../../api";
import type { AppSettings } from "../../api";

interface Props {
  app: AppSettings | null;
  setApp: (s: AppSettings) => void;
  shortcut: string | null;
  setShortcut: (s: string) => void;
  appVersion: string;
}

const THEMES: AppSettings["theme"][] = ["system", "light", "dark"];
const ACCENTS: AppSettings["accent"][] = ["ink", "amber", "jade", "rose"];
const ACCENT_COLORS: Record<AppSettings["accent"], string> = {
  ink: "#5b6cff",
  amber: "#d4b256",
  jade: "#34a853",
  rose: "#e0577a",
};

export function ShortcutAppTab({
  app,
  setApp,
  shortcut,
  setShortcut,
  appVersion,
}: Props) {
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [recordedKeys, setRecordedKeys] = useState<string>("");
  // OS-level autostart state, source of truth for the "Launch at login"
  // toggle. Independent of the settings.json mirror — the OS may have
  // been re-configured outside Magpie.
  const [autostart, setAutostart] = useState<boolean | null>(null);

  // Initial fetch.
  useEffect(() => {
    if (app === null) {
      getAppSettings().then(setApp).catch((e) => setError((e as Error).message));
    }
    if (shortcut === null) {
      getShortcut().then(setShortcut).catch(() => { /* non-fatal */ });
    }
    invoke<boolean>("get_autostart")
      .then(setAutostart)
      .catch(() => setAutostart(false));
  }, [app, shortcut, setApp, setShortcut]);

  const handleAutostart = useCallback(async (v: boolean) => {
    setAutostart(v); // optimistic
    try {
      await invoke("set_autostart", { enabled: v });
      // Mirror to settings.json so /settings/app reflects the same value
      // for any consumer that reads from it (currently just display).
      patchAppSettings({ launch_at_login: v }).catch(() => { /* non-fatal */ });
    } catch (e) {
      setAutostart(!v); // roll back
      setError(`Couldn't change Launch at login: ${(e as Error).message ?? e}`);
    }
  }, []);

  // Runtime swap of the global shortcut. Pattern adapted from Kunkun's
  // frontend/src/lib/utils/hotkey.ts: unregister the old binding, then
  // register the new one with a callback that invokes the toggle command
  // back into Rust. The Rust side has no runtime re-register path; this
  // is the only mechanism that makes "Change…" take effect without an
  // app restart. On next launch, lib.rs reads shortcut.json and
  // registers the saved combo from Rust again — same outcome.
  const swapShortcut = useCallback(async (newCombo: string, oldCombo?: string | null) => {
    if (oldCombo && oldCombo !== newCombo) {
      try {
        if (await isShortcutRegistered(oldCombo)) {
          await unregisterShortcut(oldCombo);
        }
      } catch { /* best-effort cleanup */ }
    }
    // If the new combo is already registered (e.g., by Rust at boot),
    // drop it so register() doesn't error.
    try {
      if (await isShortcutRegistered(newCombo)) {
        await unregisterShortcut(newCombo);
      }
    } catch { /* ignore */ }
    await registerShortcut(newCombo, async (e) => {
      if (e.state === "Pressed") {
        try {
          await invoke("toggle_main_window");
        } catch (err) {
          console.error("toggle_main_window failed:", err);
        }
      }
    });
  }, []);

  const patchApp = useCallback(async (p: Partial<AppSettings>) => {
    if (app !== null) setApp({ ...app, ...p });  // optimistic
    try {
      const updated = await patchAppSettings(p);
      setApp(updated);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [app, setApp]);

  // Apply theme + accent to the document root immediately on change.
  useEffect(() => {
    if (app === null) return;
    if (app.theme === "system") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = app.theme;
    }
    document.documentElement.dataset.accent = app.accent;
  }, [app?.theme, app?.accent]);

  // Shortcut recorder: capture the first modifier+key combo and save.
  useEffect(() => {
    if (!recording) return;
    const onKey = async (e: KeyboardEvent) => {
      // Wait for a non-modifier key with at least one modifier held.
      if (["Meta", "Control", "Alt", "Shift"].includes(e.key)) return;
      const mods: string[] = [];
      if (e.metaKey) mods.push("Cmd");
      if (e.ctrlKey) mods.push("Ctrl");
      if (e.altKey) mods.push("Alt");
      if (e.shiftKey) mods.push("Shift");
      if (mods.length === 0) {
        setError("Shortcut must include at least one modifier (Cmd/Ctrl/Alt/Shift)");
        return;
      }
      e.preventDefault();
      const combo = `${mods.join("+")}+${formatKey(e.key)}`;
      setRecordedKeys(combo);
      setRecording(false);
      // Try the live re-register first; if the OS rejects it (collision
      // with another app), abort without persisting so the old binding
      // stays intact on disk and on the next boot.
      try {
        await swapShortcut(combo, shortcut);
        await putShortcut(combo);
        setShortcut(combo);
      } catch (err) {
        setError(`Couldn't bind ${combo}: ${(err as Error).message ?? err}`);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [recording, setShortcut]);

  const handleUseDefault = useCallback(async () => {
    setError(null);
    try {
      await swapShortcut("Alt+Space", shortcut);
      await putShortcut("Alt+Space");
      setShortcut("Alt+Space");
    } catch (e) {
      setError(`Couldn't restore default Alt+Space: ${(e as Error).message ?? e}`);
    }
  }, [setShortcut, swapShortcut, shortcut]);

  if (app === null) {
    return (
      <div className="shortcut-app-tab">
        <p className="shortcut-app-tab__loading">Loading…</p>
      </div>
    );
  }

  return (
    <div className="shortcut-app-tab">
      <header className="shortcut-app-tab__header">
        <h1 className="shortcut-app-tab__title">Shortcut & App</h1>
        <p className="shortcut-app-tab__subtitle">
          The global summon-key, theme, accent, and launch behavior.
        </p>
      </header>
      {error && <div className="shortcut-app-tab__error">⚠ {error}</div>}

      <Section title="Global shortcut">
        {recording ? (
          <div className="shortcut-recorder">
            <span className="shortcut-recorder__chip">
              {recordedKeys || "Press a shortcut combination…"}
            </span>
            <button
              type="button"
              className="shortcut-app-tab__btn"
              onClick={() => { setRecording(false); setRecordedKeys(""); }}
            >
              Cancel
            </button>
          </div>
        ) : (
          <div className="shortcut-display">
            <ShortcutChips combo={shortcut || "Alt+Space"} />
            <button
              type="button"
              className="shortcut-app-tab__btn"
              onClick={() => { setError(null); setRecording(true); }}
            >
              Change…
            </button>
            <button
              type="button"
              className="shortcut-app-tab__btn"
              onClick={handleUseDefault}
            >
              Use default
            </button>
          </div>
        )}
        <p className="shortcut-app-tab__hint">
          Pressed from anywhere on your computer. Must include a modifier.
        </p>
      </Section>

      <Section title="Theme">
        <div className="segmented-control">
          {THEMES.map((t) => (
            <button
              key={t}
              type="button"
              className={`segmented-control__btn ${app.theme === t ? "is-active" : ""}`}
              onClick={() => patchApp({ theme: t })}
            >
              {t === "system" ? "Match system" : capitalize(t)}
            </button>
          ))}
        </div>
      </Section>

      <Section title="Accent color">
        <div className="accent-picker">
          {ACCENTS.map((a) => (
            <button
              key={a}
              type="button"
              className={`accent-swatch ${app.accent === a ? "is-active" : ""}`}
              onClick={() => patchApp({ accent: a })}
              aria-label={`Accent color ${a}`}
            >
              <span
                className="accent-swatch__dot"
                style={{ background: ACCENT_COLORS[a] }}
                aria-hidden="true"
              />
              <span className="accent-swatch__label">{capitalize(a)}</span>
            </button>
          ))}
        </div>
        <p className="shortcut-app-tab__hint">
          Colors highlights, the active toggle, and progress bars.
        </p>
      </Section>

      <Section>
        <SettingRow
          label="Launch at login"
          hint="Start Magpie automatically when you log in."
          control={
            <Toggle
              checked={autostart ?? false}
              onChange={handleAutostart}
              label="Launch at login"
            />
          }
        />
        <SettingRow
          label="Show in menu bar"
          hint="The Magpie icon stays available in the system tray. Restart Magpie to apply."
          control={
            <Toggle
              checked={app.show_in_tray}
              onChange={(v) => patchApp({ show_in_tray: v })}
              label="Show in menu bar"
            />
          }
        />
      </Section>

      <section className="about-card">
        <div className="about-card__main">
          <h3 className="about-card__name">Magpie</h3>
          <p className="about-card__version">Version {appVersion}</p>
        </div>
        <button
          type="button"
          className="shortcut-app-tab__btn"
          onClick={() => { /* no-op stub for v1 */ }}
        >
          Check for updates
        </button>
      </section>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="shortcut-app-tab__section">
      {title && <h2 className="shortcut-app-tab__section-title">{title}</h2>}
      <div className="shortcut-app-tab__section-body">{children}</div>
    </section>
  );
}

function ShortcutChips({ combo }: { combo: string }) {
  const parts = combo.split("+");
  return (
    <span className="shortcut-chips">
      {parts.map((p, i) => (
        <span key={i} className="shortcut-chips__part">
          {i > 0 && <span className="shortcut-chips__plus">+</span>}
          <kbd className="shortcut-chips__chip">{p}</kbd>
        </span>
      ))}
    </span>
  );
}

function SettingRow({
  label,
  hint,
  control,
}: {
  label: string;
  hint: string;
  control: React.ReactNode;
}) {
  return (
    <div className="setting-row">
      <div className="setting-row__text">
        <span className="setting-row__label">{label}</span>
        <span className="setting-row__hint">{hint}</span>
      </div>
      <div className="setting-row__control">{control}</div>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
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
      onClick={() => onChange(!checked)}
    >
      <span className="toggle-switch__knob" aria-hidden="true" />
    </button>
  );
}

function capitalize(s: string): string {
  return s.length > 0 ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function formatKey(key: string): string {
  if (key === " ") return "Space";
  if (key.length === 1) return key.toUpperCase();
  return key;
}
