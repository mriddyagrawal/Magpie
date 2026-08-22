/**
 * Five-state discriminated union for the ask bar (Specs/UI/ask_bar.md).
 *
 * Replaces the 13-boolean state machine in Rahul's MagpieWindow.tsx
 * with a single `view: View` plus orthogonal slices (booting, ingest,
 * recents) that compose with the view rather than competing with it.
 *
 * Why a separate file: the type is referenced from multiple components
 * (StatusFooter, RecentsPanel, MagpieWindow). Hoisting to its own
 * module avoids circular imports and lets the union evolve in one
 * place.
 */

import type { QueryResponse, Source } from "../types";

export type ViewKind =
  | "resting"
  | "typing"
  | "retrieving"
  | "answering"
  | "not_found";

export type View =
  | { kind: "resting" }
  // `prior` carries the answer the user was reading when they started a
  // follow-up, so it can stay pinned (dimmed) above the ask bar while they
  // compose the next question. Undefined for a fresh query typed from rest.
  | { kind: "typing"; query: string; selected: number | null; prior?: QueryResponse }
  | {
      kind: "retrieving";
      question: string;
      // Partial-sources slot for streaming. Both null while we're still
      // waiting on the `sources` SSE event from /query/stream (covers
      // the rewrite + retrieval window — typically ~500ms-3s); both
      // populate the moment that event lands and the body switches
      // from a full-bleed RetrievingPanel to the answering-shaped
      // two-column layout (loading spinner in the AnswerCard slot,
      // sources card already populated below it). See
      // Specs/UI/ask_bar.md and Plans/Future Plans.md #35 for the
      // wider streaming story.
      partialSources: Source[] | null;
      selectedPath: string | null;
    }
  | {
      kind: "answering";
      question: string;
      result: QueryResponse;
      selectedPath: string | null;
    }
  | { kind: "not_found"; question: string; result: QueryResponse };

/** Convenience: the kind discriminant alone, for components that only
 *  need to switch on which-state without the payload. */
export function viewKind(v: View): ViewKind {
  return v.kind;
}
