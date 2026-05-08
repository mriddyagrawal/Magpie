/**
 * Tauri auto-updater wiring (Plan #10 P10-6).
 *
 * Calls Tauri's `check()` once on app launch. If an update is available,
 * downloads + installs + relaunches without prompting the user. The
 * `dialog: false` setting in `tauri.conf.json`'s `plugins.updater` block
 * means we drive the UX entirely from JS — no native modal interrupts the
 * user's current task.
 *
 * Failure modes (network down, signature mismatch, server 404, etc.) are
 * intentionally silent — `console.warn` only. Updates are a best-effort
 * background convenience, never something that should bug a user mid-flow.
 *
 * If we want a "check now" menu item or settings toggle later, expose
 * `checkForUpdates({ silent: false })` from this module and wire to a
 * tray menu / settings panel button.
 */

import { check, type Update } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";

interface CheckOptions {
  /**
   * If true, suppress all logging (used for the on-launch background check).
   * If false, log progress so a "check now" UI can surface useful state.
   */
  silent?: boolean;
}

/**
 * Run a single update check + install cycle. Resolves once the work is
 * complete (whether an update was applied or not). Never throws — all
 * failure paths are caught and logged at most as warnings.
 */
export async function checkForUpdates(opts: CheckOptions = {}): Promise<void> {
  const silent = opts.silent ?? true;
  const log = silent ? () => {} : console.log.bind(console, "[updater]");

  try {
    log("checking for updates…");
    const update: Update | null = await check();

    if (!update?.available) {
      log("no update available");
      return;
    }

    log(`update available: ${update.version} (current ${update.currentVersion})`);

    let downloaded = 0;
    let totalBytes = 0;

    await update.downloadAndInstall((event) => {
      switch (event.event) {
        case "Started":
          totalBytes = event.data.contentLength ?? 0;
          log(`download started (${totalBytes} bytes)`);
          break;
        case "Progress":
          downloaded += event.data.chunkLength;
          // Future: surface % to the UI via a custom Tauri event so a
          // notification badge or toast can show progress.
          break;
        case "Finished":
          log("download finished, installing…");
          break;
      }
    });

    log("install complete; relaunching");
    await relaunch();
  } catch (e) {
    // Silent failure by design — see module-level comment.
    console.warn("[updater] check failed:", e);
  }
}
