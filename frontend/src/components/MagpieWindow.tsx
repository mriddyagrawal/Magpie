import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { postQuery } from "../api";
import type { QueryResponse } from "../types";
import { AnswerCard } from "./AnswerCard";
import { PreviewCard } from "./PreviewCard";
import { QuestionCard } from "./QuestionCard";
import { SourcesCard } from "./SourcesCard";
import { StatusPill } from "./StatusPill";
import { extractHighlightTokens } from "./Highlighted";

import "./MagpieWindow.css";

// Spotlight semantics: width is constant, only height grows downward when a
// query is in flight. Width matches the tauri.conf.json initial size so the
// shrink-on-hide doesn't visually jump horizontally.
const COMPACT_WIDTH = 800;
const COMPACT_HEIGHT = 96;
const EXPANDED_HEIGHT = 680;

export function MagpieWindow() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null); // the question currently answered
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const highlights = useMemo(
    () => (result ? extractHighlightTokens(result.answer) : []),
    [result]
  );

  const onSubmit = useCallback(async (q: string) => {
    if (!q.trim()) return;
    setLoading(true);
    setError(null);
    setSubmitted(q);
    try {
      const res = await postQuery(q);
      setResult(res);
      // Select the top-scoring source by default so the preview pane is populated.
      setSelectedPath(res.sources[0]?.path ?? null);
    } catch (e) {
      setError((e as Error).message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const reset = useCallback(() => {
    setResult(null);
    setSubmitted(null);
    setSelectedPath(null);
    setQuery("");
    setError(null);
  }, []);

  // Resize the window itself when a query is active vs idle. Tauri's set_size
  // keeps the top-left fixed, so the bar stays anchored and the cards grow
  // downward — no jump, no re-anchoring needed mid-session.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { getCurrentWindow, LogicalSize } = await import("@tauri-apps/api/window");
        if (cancelled) return;
        const target = result !== null || loading || error !== null
          ? new LogicalSize(COMPACT_WIDTH, EXPANDED_HEIGHT)
          : new LogicalSize(COMPACT_WIDTH, COMPACT_HEIGHT);
        await getCurrentWindow().setSize(target);
      } catch {
        // Not under Tauri (browser dev) — ignore.
      }
    })();
    return () => { cancelled = true; };
  }, [result, loading, error]);

  // Spotlight behavior: Esc always hides. Shrink the window *before* hide so
  // the next summon opens already-compact — avoids a flash of the expanded
  // layout being visible for a frame.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        hideWindow();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Wire Tauri window events: blur → hide (shrunk), focus → reset + focus input.
  // Spotlight semantics: always hide on blur, regardless of dev/prod.
  useEffect(() => {
    let cleanups: Array<() => void> = [];
    (async () => {
      try {
        const { getCurrentWindow, LogicalSize } = await import("@tauri-apps/api/window");
        const appWindow = getCurrentWindow();

        const unBlur = await appWindow.listen("tauri://blur", async () => {
          // Shrink before hide so re-summon opens already-compact, no flash.
          await appWindow.setSize(new LogicalSize(COMPACT_WIDTH, COMPACT_HEIGHT));
          await appWindow.hide();
        });
        cleanups.push(unBlur);

        const unFocus = await appWindow.listen("tauri://focus", () => {
          reset();
          // Defer to next tick so the reset has rendered the input.
          requestAnimationFrame(() => inputRef.current?.focus());
        });
        cleanups.push(unFocus);
      } catch {
        // Not running under Tauri — ignore.
      }
    })();
    return () => cleanups.forEach((fn) => fn());
  }, [reset]);

  const active = result !== null || loading || error !== null;

  return (
    <div className={`magpie-window ${active ? "is-active" : "is-resting"}`}>
      <QuestionCard
        ref={inputRef}
        value={query}
        onChange={setQuery}
        onSubmit={() => onSubmit(query)}
        loading={loading}
        submittedQuestion={submitted}
      />

      {active && (
        <div className="magpie-grid">
          <div className="magpie-col-left">
            <AnswerCard
              answer={result?.answer ?? ""}
              highlights={highlights}
              error={error}
              loading={loading}
              onFollowUp={() => inputRef.current?.focus()}
            />
            <SourcesCard
              sources={result?.sources ?? []}
              selectedPath={selectedPath}
              onSelect={setSelectedPath}
              highlights={highlights}
            />
          </div>
          <div className="magpie-col-right">
            <PreviewCard
              path={selectedPath}
              highlights={highlights}
            />
          </div>
        </div>
      )}

      {active && <StatusPill />}
    </div>
  );
}

async function hideWindow() {
  try {
    const { getCurrentWindow, LogicalSize } = await import("@tauri-apps/api/window");
    const win = getCurrentWindow();
    // Shrink while still hidden-on-next-summon so the user never sees the
    // expanded layout briefly when re-summoning. Vibrancy redraw on macOS
    // can ghost stale pixels otherwise.
    await win.setSize(new LogicalSize(COMPACT_WIDTH, COMPACT_HEIGHT));
    await win.hide();
  } catch {
    /* not under Tauri */
  }
}
