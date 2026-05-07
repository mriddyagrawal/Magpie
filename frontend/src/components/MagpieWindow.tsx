import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { postQuery, getStatus, pickFolder, pickFile, startIngest, getIngestStatus, stopIngest } from "../api";
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

// Spotlight semantics: width is constant, only height grows downward when a
// query is in flight. Width matches the tauri.conf.json initial size so the
// shrink-on-hide doesn't visually jump horizontally.
const COMPACT_WIDTH = 800;
const COMPACT_HEIGHT = 96;
const MANAGE_HEIGHT = 160;
const ONBOARD_HEIGHT = 310;
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
  const [indexDone, setIndexDone] = useState(false);
  const [indexStopped, setIndexStopped] = useState(false);
  const [ingestProgress, setIngestProgress] = useState<{
    done: number; total: number; current: string | null; elapsed: number | null;
  } | null>(null);
  const [lastFolder, setLastFolder] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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

  const runIngest = useCallback(async (folder: string) => {
    setIndexing(true);
    setIndexError(null);
    setIndexDone(false);
    setIndexStopped(false);
    setIngestProgress(null);
    try {
      await startIngest(folder);
      while (true) {
        await new Promise<void>((r) => setTimeout(r, 1000));
        const s = await getIngestStatus();
        setIngestProgress({
          done: s.files_done,
          total: s.files_total,
          current: s.current_file,
          elapsed: s.elapsed_s,
        });
        if (!s.running) {
          if (s.error) {
            setIndexError(s.error);
          } else {
            setNeedsIndex(false);
            setIndexStopped(s.stopped);
            setIndexDone(true);
            setTimeout(() => setIndexDone(false), 3000);
            requestAnimationFrame(() => inputRef.current?.focus());
          }
          setIngestProgress(null);
          break;
        }
      }
    } catch (e) {
      setIndexError((e as Error).message);
    } finally {
      setIndexing(false);
    }
  }, []);

  const handleSelectFolder = useCallback(async () => {
    const folder = await pickFolder();
    if (!folder) return;
    try {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      await getCurrentWindow().setFocus();
    } catch { /* not under Tauri */ }
    requestAnimationFrame(() => inputRef.current?.focus());
    setLastFolder(folder);
    await runIngest(folder);
  }, [runIngest]);

  const handleSelectFile = useCallback(async () => {
    const file = await pickFile();
    if (!file) return;
    try {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      await getCurrentWindow().setFocus();
    } catch { /* not under Tauri */ }
    requestAnimationFrame(() => inputRef.current?.focus());
    setLastFolder(file);
    await runIngest(file);
  }, [runIngest]);

  const handleReindex = useCallback(async () => {
    if (lastFolder) {
      await runIngest(lastFolder);
      return;
    }
    // No folder indexed yet — open the picker as a fallback.
    const folder = await pickFolder();
    if (!folder) return;
    try {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      await getCurrentWindow().setFocus();
    } catch { /* not under Tauri */ }
    requestAnimationFrame(() => inputRef.current?.focus());
    setLastFolder(folder);
    await runIngest(folder);
  }, [lastFolder, runIngest]);

  const handleStop = useCallback(async () => {
    await stopIngest();
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

  // Backspace-to-dismiss: clearing the input collapses the answer card.
  // The answer stays visible while the user types a new query; only
  // backspacing all the way to empty counts as an intentional dismiss.
  useEffect(() => {
    if (query === "") {
      setResult(null);
      setSubmitted(null);
      setSelectedPath(null);
      setError(null);
    }
  }, [query]);

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
          : indexing || indexError !== null || needsIndex || indexDone
          ? new LogicalSize(COMPACT_WIDTH, ONBOARD_HEIGHT)
          : new LogicalSize(COMPACT_WIDTH, MANAGE_HEIGHT);
        await getCurrentWindow().setSize(target);
      } catch {
        // Not under Tauri (browser dev) — ignore.
      }
    })();
    return () => { cancelled = true; };
  }, [result, loading, error, needsIndex, indexDone, indexing, indexError]);

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


  // Auto-focus the input once the backend finishes booting (it was disabled until now).
  useEffect(() => {
    if (!booting) {
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [booting]);

  // Re-focus the input whenever the window gains focus (e.g. user clicks back on Magpie
  // or Alt+Space re-summons it). Does not reset state so in-progress queries are preserved.
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

      {!active && (
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
              <button className="onboard-card__btn" onClick={handleSelectFolder}>Try again</button>
            </>
          ) : indexDone ? (
            <>
              <p className="onboard-card__message">
                {indexStopped
                  ? "Indexing stopped — files processed so far are searchable."
                  : "All done! Go ahead and ask something."}
              </p>
              <button className="onboard-card__btn" onClick={handleReindex}>Re-index</button>
            </>
          ) : needsIndex ? (
            <>
              <p className="onboard-card__message">Nothing indexed yet. Select a folder or file to get started.</p>
              <div className="onboard-card__actions">
                <button className="onboard-card__btn" onClick={handleSelectFolder}>Select folder</button>
                <button className="onboard-card__btn onboard-card__btn--secondary" onClick={handleSelectFile}>Select file</button>
              </div>
            </>
          ) : (
            <button className="onboard-card__btn" onClick={handleReindex}>Re-index</button>
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
    // Shrink to MANAGE_HEIGHT (not COMPACT_HEIGHT) — the management card is
    // always rendered below the search bar, so the window is never truly 96px.
    await win.setSize(new LogicalSize(COMPACT_WIDTH, MANAGE_HEIGHT));
    await win.hide();
  } catch {
    /* not under Tauri */
  }
}
