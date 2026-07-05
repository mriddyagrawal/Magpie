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

import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { visit, SKIP } from "unist-util-visit";
import "katex/dist/katex.min.css";

import { splitWithTokens } from "./Highlighted";
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
  // Both separators — Windows paths use `\`.
  const filename = source.path.split(/[\\/]/).pop() ?? source.path;
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

// ---------------------------------------------------------------------------
// Markdown answer renderer (the primary path)
// ---------------------------------------------------------------------------

/**
 * Rehype plugin: walk every text node in the rendered markdown tree and
 *   1. replace `[N]` citation markers with an <answer-cite data-n>
 *      element (mapped to <CitationPill> below), and
 *   2. wrap highlight-token matches in <mark class="magpie-highlight">.
 *
 * Skipped inside code blocks (a `[1]` in a shell snippet is an array
 * index, not a citation) and inside math nodes (KaTeX consumes its own
 * source text; this plugin runs BEFORE rehype-katex in the pipeline).
 */
function rehypeCiteAndHighlight(tokens: string[]) {
  return () => (tree: unknown) => {
    visit(tree as never, "text", (node: never, index: number | undefined, parent: never) => {
      const p = parent as { tagName?: string; properties?: { className?: unknown }; children: unknown[] } | undefined;
      const n = node as { value: string };
      if (index === undefined || !p) return;
      if (p.tagName === "code" || p.tagName === "pre") return;
      const cls = p.properties?.className;
      if (Array.isArray(cls) && cls.some((c) => String(c).startsWith("math"))) return;

      const pieces = n.value.split(/(\[\d+\])/g).filter((s) => s !== "");
      const out: unknown[] = [];
      for (const piece of pieces) {
        const m = piece.match(/^\[(\d+)\]$/);
        if (m) {
          out.push({
            type: "element",
            tagName: "answer-cite",
            properties: { dataN: m[1] },
            children: [],
          });
        } else {
          for (const part of splitWithTokens(piece, tokens)) {
            out.push(
              part.highlight
                ? {
                    type: "element",
                    tagName: "mark",
                    properties: { className: ["magpie-highlight"] },
                    children: [{ type: "text", value: part.text }],
                  }
                : { type: "text", value: part.text },
            );
          }
        }
      }
      // Nothing to change — leave the node untouched.
      if (out.length === 1 && (out[0] as { type: string }).type === "text") return;
      p.children.splice(index, 1, ...out);
      return [SKIP, index + out.length];
    });
  };
}

/**
 * The answer body: GitHub-flavored markdown + LaTeX math (KaTeX) with
 * clickable `[N]` citation pills and token highlighting preserved.
 * Replaces the old flat-text renderAnswer as AnswerCard's renderer —
 * answers citing academic PDFs routinely contain lists, tables, and
 * `$...$` math, which flat text rendered as unreadable soup.
 */
export function AnswerMarkdown({
  text,
  sources,
  highlightTokens = [],
  onSelectSource,
}: RenderAnswerOptions) {
  const citePlugin = useMemo(
    () => rehypeCiteAndHighlight(highlightTokens),
    [highlightTokens],
  );
  const components = useMemo(
    () => ({
      "answer-cite": (props: { node?: { properties?: { dataN?: string } } }) => {
        const n = Number(props.node?.properties?.dataN);
        if (!Number.isFinite(n) || n < 1 || n > sources.length) {
          // Out-of-range: same bug-tolerant fallback as before.
          console.warn(
            `citation [${n}] out of range (1..${sources.length || 0}); rendering as plain text.`,
          );
          return (
            <span className="citation-orphan" title="Unresolved citation">
              [{Number.isFinite(n) ? n : "?"}]
            </span>
          );
        }
        return <CitationPill n={n} source={sources[n - 1]} onSelect={onSelectSource} />;
      },
    }),
    [sources, onSelectSource],
  );

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[citePlugin, rehypeKatex]}
      // Custom element mapping — cast because react-markdown's types
      // only know standard HTML tag names.
      components={components as never}
    >
      {text}
    </ReactMarkdown>
  );
}

