/**
 * WelcomeCard — empty-corpus first-launch onboarding body.
 *
 * Renders below the input bar in `resting` state when:
 *   - `indexed_count === 0` (Magpie has never read any files)
 *   - the sidecar is up (`!booting`)
 *   - no ingest is currently running (the IndexingOverlay covers that)
 *
 * Visual treatment mirrors NotFoundCard exactly — single-CTA card with
 * header / body / button — so it reuses NotFoundCard's `.not-found-card`
 * CSS classes verbatim. Keeping a separate component (rather than
 * shoe-horning into NotFoundCard) means the copy and trigger logic
 * stay separate; if either card needs to diverge later, decoupling is
 * a 5-minute split.
 *
 * The CTA reuses the same `open_settings_with_action` Tauri command
 * NotFoundCard's CTA fires, with `action="add-folder"` — Settings opens
 * on the Data tab and immediately pops the folder picker. Same
 * onboarding path as the not-found case, just surfaced earlier in the
 * user journey.
 */

import { useCallback } from "react";
import { ChevronRight, Plus } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";

export function WelcomeCard() {
  const onAddFolder = useCallback(async () => {
    try {
      await invoke("open_settings_with_action", { action: "add-folder" });
    } catch {
      // Not under Tauri — ignore. Browser-dev users can fall back to
      // opening settings manually via the gear icon.
    }
  }, []);

  return (
    <section className="not-found-card magpie-card" aria-live="polite">
      <header className="not-found-card__header">
        <h2 className="not-found-card__title">Welcome to Magpie</h2>
      </header>
      <p className="not-found-card__body">
        Magpie can't answer questions until it's read some files. Add
        a folder to get started — everything stays on your machine
        unless you switch to the cloud provider.
      </p>
      <button
        type="button"
        className="not-found-card__cta"
        onClick={onAddFolder}
      >
        <span className="not-found-card__cta-icon" aria-hidden="true">
          <Plus size={14} />
        </span>
        <span className="not-found-card__cta-label">
          Add a folder to get started
        </span>
        <span className="not-found-card__cta-chevron" aria-hidden="true">
          <ChevronRight size={14} />
        </span>
      </button>
    </section>
  );
}
