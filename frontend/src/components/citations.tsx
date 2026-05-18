/**
 * Citation pill renderer for the answer card.
 *
 * The answer pipeline (src/answer.py system prompt) instructs the LLM to
 * emit inline `[1]`, `[2]` etc. markers in the prose. The number is the
 * 1-based index into `sources_used`. This renderer parses the prose,
 * substitutes each marker with a styled CitationPill component, and
 * routes everything else through the existing Highlighted token-marker.
 *
 * Bug-tolerance (per Plan #25 in Plans/Future Plans.md): if the model
 * emits an out-of-range marker (`[5]` when sources_used has 3 entries)
 * or a non-numeric marker, we render the marker as plain text with a
 * subtle "citation-orphan" class so it's still recognizable as
 * something-the-model-meant-to-cite. We log a console warning so
 * regressions on the prompt side are observable in dev tools.
 *
 * Why a separate file (not just adding to AnswerCard.tsx): the parser
 * is a pure function that's easier to reason about in isolation, and
 * other surfaces (RecentsPanel's preview line, NotFoundCard's prose,
 * etc.) might want to re-use it.
 */

import { Highlighted } from "./Highlighted";
import type { Source } from "../types";

export interface CitationProps {
  /** 1-based citation number, as it appeared in the prose. */
  n: number;
  /** The source this citation points at (already validated as in-range). */
  source: Source;
  /** Click handler — selects the source in the sources list. */
  onSelect?: (path: string) => void;
}

/**
 * A single inline citation tag. Rendered in green pill style per the
 * mockups (`Specs/UI/Screenshot 2026-05-07 at 10.28.51 PM.png`). Hover
 * reveals the source filename via the native title tooltip; click
 * fires `onSelect` so the parent can update the source list / preview.
 */
export function CitationPill({ n, source, onSelect }: CitationProps) {
  const filename = source.path.split("/").pop() ?? source.path;
  return (
    <button
      type="button"
      className="citation-pill"
      title={filename}
      onClick={() => onSelect?.(source.path)}
      aria-label={`Citation ${n}: ${filename}`}
    >
      {n}
    </button>
  );
}

export interface RenderAnswerOptions {
  text: string;
  sources: Source[];
  highlightTokens?: string[];
  onSelectSource?: (path: string) => void;
}

/**
 * Parse `text` into an array of React-renderable nodes, replacing
 * `[N]` markers with CitationPill components. Non-citation text is
 * routed through `<Highlighted>` for token highlighting.
 *
 * Returns an array (not JSX) so consumers can splat it into their own
 * containers without nesting fragments.
 */
export function renderAnswer({
  text,
  sources,
  highlightTokens = [],
  onSelectSource,
}: RenderAnswerOptions): React.ReactNode[] {
  // Split on the citation markers, keeping the markers as separate
  // parts. The capture group inside split() emits the markers as their
  // own array entries.
  const parts = text.split(/(\[\d+\])/g);

  return parts.map((part, i) => {
    const m = part.match(/^\[(\d+)\]$/);
    if (!m) {
      // Non-citation chunk — route through highlighting.
      if (!part) return null;
      return (
        <Highlighted key={i} text={part} tokens={highlightTokens} />
      );
    }
    const n = Number(m[1]);
    if (!Number.isFinite(n) || n < 1 || n > sources.length) {
      // Out-of-range or non-numeric: bug-tolerant fallback.
      // eslint-disable-next-line no-console
      console.warn(
        `citation ${part} out of range (1..${sources.length || 0}); ` +
          `rendering as plain text. The answer prompt may have drifted.`
      );
      return (
        <span key={i} className="citation-orphan" title="Unresolved citation">
          {part}
        </span>
      );
    }
    return (
      <CitationPill
        key={i}
        n={n}
        source={sources[n - 1]}
        onSelect={onSelectSource}
      />
    );
  }).filter(Boolean);
}
