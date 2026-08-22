/**
 * NotFoundCard — the body of State 5 (Specs/UI/ask_bar.md State 5).
 *
 * Renders when the answer pipeline returned `not_found: true`. Shows
 * the "I read N likely sources but didn't find anything about X"
 * preamble + exactly one CTA: "Add the folder where this knowledge
 * might live", which deep-links into Settings → Data → folder picker
 * via the open_settings_with_action Tauri command.
 *
 * Per the resolved decisions in Plans/UI/Implementation Plan.md:
 * single CTA only. The earlier mockup variants ("Re-read", "Try a
 * different phrasing") are intentionally dropped — they added
 * complexity for marginal value, and the Add-folder path covers the
 * common case (Magpie can't answer because the corpus doesn't have
 * the data).
 */

import { useCallback } from "react";
import { ChevronRight, Plus, SearchX } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";

interface Props {
  /** Total sources scanned during retrieval (sources_scanned_count
   *  from QueryResponse). "I read N likely sources…" */
  scannedCount: number;
  /** Short noun phrase summarizing what the user asked about. The
   *  LLM emits this when it sets not_found=true; rendered into the
   *  preamble copy. */
  topic: string;
}

export function NotFoundCard({ scannedCount, topic }: Props) {
  const onAddFolder = useCallback(async () => {
    try {
      await invoke("open_settings_with_action", { action: "add-folder" });
    } catch {
      // Not under Tauri — ignore. Browser-dev users can fall back to
      // opening settings manually via the gear icon.
    }
  }, []);

  // The count is the total file count from the manifest (everything
  // Magpie has read), not the per-query retrieval count — that gives
  // the user an honest "I checked everything I have" framing.
  const sourceWord = scannedCount === 1 ? "source" : "sources";
  const headline = scannedCount > 0
    ? `I checked all ${scannedCount.toLocaleString()} ${sourceWord} I've read but didn't find anything about ${topic}.`
    : `Magpie hasn't read any folders that look like they'd contain ${topic}.`;

  return (
    <section className="not-found-card magpie-card" aria-live="polite">
      <header className="not-found-card__header">
        <span className="not-found-card__icon" aria-hidden="true">
          <SearchX size={15} />
        </span>
        <h2 className="not-found-card__title">Answer not found</h2>
      </header>
      <p className="not-found-card__body">{headline}</p>
      <button
        type="button"
        className="not-found-card__cta"
        onClick={onAddFolder}
      >
        <span className="not-found-card__cta-icon" aria-hidden="true">
          <Plus size={14} />
        </span>
        <span className="not-found-card__cta-label">
          Add the folder where this knowledge might live
        </span>
        <span className="not-found-card__cta-chevron" aria-hidden="true">
          <ChevronRight size={14} />
        </span>
      </button>
    </section>
  );
}
