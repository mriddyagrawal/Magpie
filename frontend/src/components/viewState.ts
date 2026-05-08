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

import type { QueryResponse } from "../types";

export type ViewKind =
  | "resting"
  | "typing"
  | "retrieving"
  | "answering"
  | "not_found";

export type View =
  | { kind: "resting" }
  | { kind: "typing"; query: string; selected: number | null }
  | { kind: "retrieving"; question: string }
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
