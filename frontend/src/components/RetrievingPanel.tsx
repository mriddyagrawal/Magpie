/**
 * RetrievingPanel — the body of State 3 (Specs/UI/ask_bar.md).
 *
 * Renders between the user submitting a question and the answer
 * starting to stream. Shows:
 *   - The question header (read-only echo of what the user asked).
 *   - A "Retrieving sources… scanning N docs" status line with a
 *     pulsing glyph.
 *   - A skeleton list of source rows that progressively fills as
 *     retrieval surfaces candidates. (For v1 we don't have a streaming
 *     retrieval API; the panel just shows a static "scanning" state
 *     for the duration. Wire-up to live retrieval surfacing is parked
 *     until /query supports streaming.)
 */

interface Props {
  /** Total documents in the index — used in "scanning N docs" copy. */
  documentsTotal: number;
}

export function RetrievingPanel({ documentsTotal }: Props) {
  return (
    <section className="retrieving-panel magpie-card" aria-live="polite">
      <div className="retrieving-panel__status">
        <span className="retrieving-panel__spinner" aria-hidden="true">○</span>
        <span className="retrieving-panel__status-label">
          Retrieving sources…
        </span>
        <span className="retrieving-panel__status-meta">
          scanning {documentsTotal.toLocaleString()} docs
        </span>
      </div>
      {/* Skeleton placeholder bars. Heights/widths are mockup-faithful
          (Specs/UI/Screenshot 2026-05-07 at 10.27.54 PM.png). When
          /query gains a streaming retrieval API, replace these with
          live source rows ("math-dept-2024.pdf  ▷ reading…"). */}
      <div className="retrieving-panel__skeleton">
        <div className="retrieving-panel__skeleton-row retrieving-panel__skeleton-row--wide" />
        <div className="retrieving-panel__skeleton-row retrieving-panel__skeleton-row--medium" />
        <div className="retrieving-panel__skeleton-row retrieving-panel__skeleton-row--narrow" />
      </div>
    </section>
  );
}
