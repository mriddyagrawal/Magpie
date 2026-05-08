import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { postQuery, getStatus, getShortcut, getIngestStatus, stopIngest } from "../api";
import type { QueryResponse } from "../types";
import { AnswerCard } from "./AnswerCard";
import { PreviewCard } from "./PreviewCard";
import { QuestionCard } from "./QuestionCard";
import { SourcesCard } from "./SourcesCard";
import { StatusPill } from "./StatusPill";
import { extractHighlightTokens } from "./Highlighted";

import "./MagpieWindow.css";

function formatElapsed(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

// Spotlight semantics: width is constant, height grows downward for content.
const COMPACT_WIDTH = 800;
const COMPACT_HEIGHT = 96;    // search bar only — no onboard card
const ONBOARD_HEIGHT = 310;   // search bar + onboard card (indexing / needs-index)
const EXPANDED_HEIGHT = 680;  // search bar + full answer / sources / preview grid

export function MagpieWindow() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [booting, setBooting] = useState(true);
  const [needsIndex, setNeedsIndex] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [indexDone, setIndexDone] = useState(false);
  const [indexStopped, setIndexStopped] = useState(false);
  const [ingestProgress, setIngestProgress] = useState<{
    done: number; total: number; current: string | null; elapsed: number | null;
  } | null>(null);
  const [shortcutLabel, setShortcutLabel] = useState("Alt+Space");
  const inputRef = useRef<HTMLInputElement>(null);
  // Tracks whether the last poll saw running=true so we can detect the transition.
  const prevRunningRef = useRef(false);

  // Boot: poll /healthz until sidecar responds, then load corpus status + shortcut.
  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      const base = `http://127.0.0.1:${(window as Window & { __MAGPIE_PORT__?: number }).__MAGPIE_PORT__ ?? 8765}`;
      while (!cancelled) {
        try {
          const res = await fetch(`${base}/healthz`);
          if (res.ok) {
            if (!cancelled) {
              setBooting(false);
              const [status, shortcut] = await Promise.all([getStatus(), getShortcut()]);
              if (!cancelled) {
                if (status.indexed_count === 0) setNeedsIndex(true);
                setShortcutLabel(shortcut);
              }
            }
            return;
          }
        } catch {
          // sidecar not up yet
        }
        await new Promise<void>((r) => setTimeout(r, 500));
      }
    };
    boot();
    return () => { cancelled = true; };
  }, []);

  // Unified background poll — catches indexing started from any window (settings or here).
  // prevRunningRef detects the running→done transition without needing state in the loop.
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      while (!cancelled) {
        await new Promise<void>((r) => setTimeout(r, 1500));
        if (cancelled) break;
        try {
          const s = await getIngestStatus();
          if (s.running) {
            prevRunningRef.current = true;
            setIndexing(true);
            setIndexError(null);
            setIngestProgress({
              done: s.files_done,
              total: s.files_total,
              current: s.current_file,
              elapsed: s.elapsed_s,
            });
          } else if (prevRunningRef.current) {
            // Transition: was running, now done.
            prevRunningRef.current = false;
            setIndexing(false);
            setIngestProgress(null);
            if (s.error) {
              setIndexError(s.error);
            } else {
              setNeedsIndex(false);
              setIndexStopped(s.stopped);
              setIndexDone(true);
              setTimeout(() => setIndexDone(false), 3000);
              requestAnimationFrame(() => inputRef.current?.focus());
            }
          }
        } catch {
          // sidecar not ready yet
        }
      }
    };
    poll();
    return () => { cancelled = true; };
  }, []);

  const handleStop = useCallback(async () => {
    await stopIngest();
  }, []);

  const handleOpenSettings = useCallback(async () => {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const port = (window as Window & { __MAGPIE_PORT__?: number }).__MAGPIE_PORT__ ?? 8765;
      await invoke("open_settings", { port });
    } catch {
      // Not under Tauri — ignore.
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
      setSelectedPath(res.sources[0]?.path ?? null);
    } catch (e) {
      setError((e as Error).message);
      setResult(null);
      setSubmitted(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Backspace-to-dismiss: clearing the input collapses the answer card.
  useEffect(() => {
    if (query === "") {
      setResult(null);
      setSubmitted(null);
      setSelectedPath(null);
      setError(null);
    }
  }, [query]);

  // Resize the Tauri window to match the current display state.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { getCurrentWindow, LogicalSize } = await import("@tauri-apps/api/window");
        if (cancelled) return;
        const showOnboard = indexing || indexError !== null || needsIndex || indexDone;
        const target =
          result !== null || loading || error !== null
            ? new LogicalSize(COMPACT_WIDTH, EXPANDED_HEIGHT)
            : showOnboard
            ? new LogicalSize(COMPACT_WIDTH, ONBOARD_HEIGHT)
            : new LogicalSize(COMPACT_WIDTH, COMPACT_HEIGHT);
        await getCurrentWindow().setSize(target);
      } catch {
        // Not under Tauri (browser dev) — ignore.
      }
    })();
    return () => { cancelled = true; };
  }, [result, loading, error, needsIndex, indexDone, indexing, indexError]);

  // Esc always hides. Shrink before hide so the next summon opens compact.
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

  // Auto-focus input once the sidecar is up.
  useEffect(() => {
    if (!booting) requestAnimationFrame(() => inputRef.current?.focus());
  }, [booting]);

  // Re-focus on window focus (Alt+Space re-summon).
  useEffect(() => {
    let cleanups: Array<() => void> = [];
    (async () => {
      try {
        const { getCurrentWindow } = await import("@tauri-apps/api/window");
        const appWindow = getCurrentWindow();
        const unFocus = await appWindow.listen("tauri://focus", () => {
          requestAnimationFrame(() => inputRef.current?.focus());
        });
        cleanups.push(unFocus);
      } catch {
        // Not running under Tauri — ignore.
      }
    })();
    return () => cleanups.forEach((fn) => fn());
  }, []);

  const active = result !== null || loading || error !== null;
  const showOnboard = !active && (indexing || indexError !== null || needsIndex || indexDone);

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
        onOpenSettings={handleOpenSettings}
        shortcutLabel={shortcutLabel}
      />

      {showOnboard && (
        <div className="onboard-card magpie-card">
          {indexing ? (
            <>
              <p className="onboard-card__message">
                {ingestProgress?.total
                  ? `Indexing ${ingestProgress.done} / ${ingestProgress.total} files…`
                  : "Scanning files…"}
              </p>
              {ingestProgress?.total ? (
                <div className="onboard-card__progress-bar">
                  <div
                    className="onboard-card__progress-fill"
                    style={{ width: `${Math.round((ingestProgress.done / ingestProgress.total) * 100)}%` }}
                  />
                </div>
              ) : null}
              {ingestProgress?.current && (
                <p className="onboard-card__detail">
                  {ingestProgress.current.length > 44
                    ? `…${ingestProgress.current.slice(-42)}`
                    : ingestProgress.current}
                </p>
              )}
              {ingestProgress?.elapsed != null && (
                <p className="onboard-card__detail">{formatElapsed(ingestProgress.elapsed)}</p>
              )}
              <button className="onboard-card__btn onboard-card__btn--stop" onClick={handleStop}>
                Stop indexing
              </button>
            </>
          ) : indexError ? (
            <>
              <p className="onboard-card__message">Indexing failed: {indexError}</p>
              <button className="onboard-card__btn" onClick={handleOpenSettings}>Open Settings</button>
            </>
          ) : indexDone ? (
            <p className="onboard-card__message">
              {indexStopped
                ? "Indexing stopped — files so far are searchable."
                : "All done! Go ahead and ask something."}
            </p>
          ) : needsIndex ? (
            <>
              <p className="onboard-card__message">No folders indexed yet.</p>
              <button className="onboard-card__btn" onClick={handleOpenSettings}>Open Settings</button>
            </>
          ) : null}
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
            <PreviewCard path={selectedPath} highlights={highlights} />
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
    await win.setSize(new LogicalSize(COMPACT_WIDTH, COMPACT_HEIGHT));
    await win.hide();
  } catch {
    /* not under Tauri */
  }
}
