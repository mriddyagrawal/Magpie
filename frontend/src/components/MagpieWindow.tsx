import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { postQuery, getStatus, pickFolder, startIngest, getIngestStatus } from "../api";
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
const ONBOARD_HEIGHT = 210;
const EXPANDED_HEIGHT = 680;

export function MagpieWindow() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null); // the question currently answered
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [booting, setBooting] = useState(true);
  const [needsIndex, setNeedsIndex] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Poll /healthz every 500ms until the sidecar is up, then check if anything
  // is indexed. If the corpus is empty, show the onboarding card.
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      const base = `http://127.0.0.1:${(window as Window & { __MAGPIE_PORT__?: number }).__MAGPIE_PORT__ ?? 8765}`;
      while (!cancelled) {
        try {
          const res = await fetch(`${base}/healthz`);
          if (res.ok) {
            if (!cancelled) {
              setBooting(false);
              const status = await getStatus();
              if (!cancelled && status.indexed_count === 0) setNeedsIndex(true);
            }
            return;
          }
        } catch {
          // sidecar not ready yet
        }
        await new Promise<void>((r) => setTimeout(r, 500));
      }
    };
    poll();
    return () => { cancelled = true; };
  }, []);

  const handleSelectFolder = useCallback(async () => {
    const folder = await pickFolder();
    if (!folder) return;
    setIndexing(true);
    setIndexError(null);
    try {
      await startIngest(folder);
      // Poll until indexing finishes
      while (true) {
        await new Promise<void>((r) => setTimeout(r, 1000));
        const s = await getIngestStatus();
        if (!s.running) {
          if (s.error) {
            setIndexError(s.error);
          } else {
            setNeedsIndex(false);
          }
          break;
        }
      }
    } catch (e) {
      setIndexError((e as Error).message);
    } finally {
      setIndexing(false);
    }
  }, []);

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
      setNeedsIndex(false);
      // Select the top-scoring source by default so the preview pane is populated.
      setSelectedPath(res.sources[0]?.path ?? null);
    } catch (e) {
      setError((e as Error).message);
      setResult(null);
      setSubmitted(null); // restore input so user can edit and retry immediately
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
          : needsIndex
          ? new LogicalSize(COMPACT_WIDTH, ONBOARD_HEIGHT)
          : new LogicalSize(COMPACT_WIDTH, COMPACT_HEIGHT);
        await getCurrentWindow().setSize(target);
      } catch {
        // Not under Tauri (browser dev) — ignore.
      }
    })();
    return () => { cancelled = true; };
  }, [result, loading, error, needsIndex]);

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

  // Clicking the transparent window background (outside any card) should dismiss,
  // matching Spotlight / Alfred behaviour. tauri://blur only fires when another
  // *app* steals focus, so we also need this document-level handler for clicks
  // that land on the webview's transparent layer without leaving the window.
  useEffect(() => {
    const handler = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target?.closest(".magpie-card")) {
        hideWindow();
      }
    };
    document.addEventListener("pointerdown", handler);
    return () => document.removeEventListener("pointerdown", handler);
  }, []);

  // Wire Tauri window events: blur → hide (shrunk), focus → reset + focus input.
  // Spotlight semantics: always hide on blur, regardless of dev/prod.
  useEffect(() => {
    let cleanups: Array<() => void> = [];
    (async () => {
      try {
        const { getCurrentWindow, LogicalSize } = await import("@tauri-apps/api/window");
        const appWindow = getCurrentWindow();

        const unBlur = await appWindow.listen("tauri://blur", () => {
          // Debounce: on Windows the Alt key causes a spurious blur immediately
          // after the window appears. Cancel the hide if focus returns quickly.
          blurTimer.current = setTimeout(async () => {
            blurTimer.current = null;
            await appWindow.setSize(new LogicalSize(COMPACT_WIDTH, COMPACT_HEIGHT));
            await appWindow.hide();
          }, 150);
        });
        cleanups.push(unBlur);

        const unFocus = await appWindow.listen("tauri://focus", () => {
          if (blurTimer.current !== null) {
            clearTimeout(blurTimer.current);
            blurTimer.current = null;
          }
          reset();
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
        booting={booting}
        submittedQuestion={submitted}
      />

      {needsIndex && !active && (
        <div className="onboard-card magpie-card">
          <p className="onboard-card__message">
            {indexing
              ? "Indexing your files…"
              : indexError
              ? `Indexing failed: ${indexError}`
              : "Nothing indexed yet. Select a folder to get started."}
          </p>
          {!indexing && (
            <button
              className="onboard-card__btn"
              onClick={handleSelectFolder}
            >
              {indexError ? "Try again" : "Select folder to index"}
            </button>
          )}
        </div>
      )}

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
