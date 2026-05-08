/**
 * RecentsPanel — the body of State 2 (Specs/UI/ask_bar.md).
 *
 * Renders below the search pill while the user is typing OR has
 * focused-but-empty input. Shows the last 4 questions (out of last 10
 * stored in recents.json) with relative timestamps. ↑/↓ navigates,
 * ⏎ replays the cached payload (zero LLM cost), ↻ on the right of
 * each row fires a fresh /query in the background.
 *
 * Per Plans/UI/Implementation Plan.md "Resolved design decisions":
 *   - Persist as a list (not collapsing on type-vs-empty).
 *   - Show last 4, store last 10.
 *   - Click row body OR ⏎ on selection → replay cached.
 *   - Click ↻ → background fresh /query, in-place result swap with
 *     same recents id (caller handles the post-fresh swap).
 */

import { useCallback, useEffect, useState } from "react";
import { getRecents } from "../api";
import type { RecentEntry } from "../types";

const SHOW_COUNT = 4;

interface Props {
  /** ↑/↓ index into the visible (top-N) slice; null = nothing
   *  selected (Enter on no-selection submits the typed input as a
   *  fresh question; the parent handles that branch). */
  selected: number | null;
  onSelectIndex: (i: number | null) => void;
  /** Replay cached result. Parent renders the answer card from the
   *  RecentEntry.result without firing /query. */
  onReplay: (entry: RecentEntry) => void;
  /** Force a fresh ask: parent fires postQuery(question) and updates
   *  the recent's result in place when it lands. */
  onAskAgain: (entry: RecentEntry) => void;
  /** Recents list provided by the parent (so MagpieWindow can mutate
   *  it after each fresh ask without re-fetching). null = still
   *  loading on first mount. */
  recents: RecentEntry[] | null;
  setRecents: (r: RecentEntry[]) => void;
}

export function RecentsPanel({
  selected,
  onSelectIndex,
  onReplay,
  onAskAgain,
  recents,
  setRecents,
}: Props) {
  const [error, setError] = useState<string | null>(null);

  // Initial fetch on mount. Parent owns the list afterward.
  useEffect(() => {
    if (recents !== null) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await getRecents();
        if (!cancelled) setRecents(list);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => { cancelled = true; };
  }, [recents, setRecents]);

  if (error !== null) {
    return (
      <section className="recents-panel magpie-card recents-panel--error">
        <span>Recents unavailable: {error}</span>
      </section>
    );
  }

  if (recents === null) {
    // Skeleton during the very first fetch. Boot poll usually
    // completes before this surface ever shows so users rarely see it.
    return (
      <section className="recents-panel magpie-card recents-panel--loading">
        <span className="recents-panel__heading">RECENT</span>
      </section>
    );
  }

  const visible = recents.slice(0, SHOW_COUNT);

  if (visible.length === 0) {
    // Empty state (first-launch or after a clear-history): just hide
    // the panel entirely so the window collapses to the resting size.
    return null;
  }

  return (
    <section className="recents-panel magpie-card" aria-label="Recent questions">
      <header className="recents-panel__heading">RECENT</header>
      <ul className="recents-panel__list" role="listbox">
        {visible.map((entry, i) => (
          <RecentRow
            key={entry.id}
            entry={entry}
            isSelected={selected === i}
            onMouseEnter={() => onSelectIndex(i)}
            onClick={() => onReplay(entry)}
            onAskAgain={() => onAskAgain(entry)}
          />
        ))}
      </ul>
    </section>
  );
}

interface RecentRowProps {
  entry: RecentEntry;
  isSelected: boolean;
  onMouseEnter: () => void;
  onClick: () => void;
  onAskAgain: () => void;
}

function RecentRow({
  entry,
  isSelected,
  onMouseEnter,
  onClick,
  onAskAgain,
}: RecentRowProps) {
  const onAskAgainClick = useCallback(
    (e: React.MouseEvent) => {
      // Don't bubble — click on ↻ is a fresh ask, not a replay.
      e.stopPropagation();
      onAskAgain();
    },
    [onAskAgain]
  );

  return (
    <li
      className={`recents-panel__row ${isSelected ? "is-selected" : ""}`}
      role="option"
      aria-selected={isSelected}
      onMouseEnter={onMouseEnter}
      onClick={onClick}
    >
      <span className="recents-panel__row-icon" aria-hidden="true">📄</span>
      <span className="recents-panel__row-question">{entry.question}</span>
      <span className="recents-panel__row-meta">
        <span className="recents-panel__row-timestamp">
          {formatRelative(entry.asked_at)}
        </span>
        <button
          type="button"
          className="recents-panel__row-ask-again"
          title="Ask again (fresh answer)"
          aria-label="Ask again with fresh answer"
          onClick={onAskAgainClick}
        >
          ↻
        </button>
      </span>
    </li>
  );
}

/**
 * Relative-time formatter for recent timestamps. v1 keeps it simple:
 * minutes/hours/days ago, then drops to "yesterday" / "N days ago".
 * Uses navigator.language for locale-aware large-number formatting.
 */
function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const now = Date.now();
  const diffMs = now - then;
  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} h ago`;
  const days = Math.round(hr / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 30) return `${Math.round(days / 7)} wk ago`;
  return new Date(iso).toLocaleDateString();
}
