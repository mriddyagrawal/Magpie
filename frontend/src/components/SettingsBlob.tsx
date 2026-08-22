/**
 * SettingsBlob — Spotlight-style circular gear button to the right of
 * the search pill. Replaces the inside-the-bar gear from Rahul's build.
 *
 * Pattern reference: macOS Spotlight ships circular blobs to the right
 * of its search pill (App Store, Folders, Stacks, Files). Magpie ships
 * exactly one — Settings.
 *
 * Always visible across all five ask-bar states (resting, typing,
 * retrieving, answering, not-found). The user can open Settings while
 * reading an answer or in the not-found state. Esc still hides the ask
 * bar; clicking the blob opens Settings without closing the ask bar.
 *
 * Sibling pattern documented in Specs/UI/ask_bar.md "Universal
 * elements".
 */

import { useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";

interface Props {
  /** Sidecar port — passed verbatim to the open_settings command for
   *  the legacy invoke signature. The Tauri side now reads it from
   *  state too, so this is belt-and-suspenders. */
  port: number;
}

export function SettingsBlob({ port }: Props) {
  const onClick = useCallback(async () => {
    try {
      await invoke("open_settings", { port });
    } catch {
      // Not under Tauri (browser dev) — ignore.
    }
  }, [port]);

  return (
    <button
      type="button"
      className="settings-blob"
      onClick={onClick}
      title="Settings"
      aria-label="Open settings"
      tabIndex={-1}
    >
      <span className="settings-blob__glyph" aria-hidden="true">⚙</span>
    </button>
  );
}
