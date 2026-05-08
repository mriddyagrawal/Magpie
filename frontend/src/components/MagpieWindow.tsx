/**
 * MagpieWindow — the top-level ask bar component.
 *
 * Implements the five-state model from Specs/UI/ask_bar.md:
 *
 *   resting       Input empty, focused. Just the search pill +
 *                 settings blob + status footer.
 *   typing        Input has at least one char. Recents panel appears
 *                 below the pill; ↑/↓ navigates, ⏎ replays cached
 *                 OR submits as a fresh question (when nothing is
 *                 selected).
 *   retrieving    Pipeline in flight. Question echo + scanning UI.
 *   answering     Result streaming/done. Two-column grid: answer +
 *                 sources on the left, preview on the right.
 *   not_found     Result.not_found = true. Single-CTA card.
 *
 * Plus orthogonal slices that compose with the view:
 *   booting       Sidecar isn't up yet. Disables the input across
 *                 all view kinds.
 *   ingest        Background indexing snapshot. Shows in the status
 *                 footer always; renders an above-the-body progress
 *                 card when view ∈ {resting, typing}.
 *   recents       Last-N persisted asks. Initially null (fetched on
 *                 mount), then mutated locally after each ask.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

import {
  getIngestStatus,
  getRecent,
  postQuery,
  stopIngest,
} from "../api";
import type { IngestStatus } from "../api";
import type { QueryResponse, RecentEntry } from "../types";
import type { View } from "./viewState";
import { extractHighlightTokens } from "./Highlighted";

import { AnswerCard } from "./AnswerCard";
import { NotFoundCard } from "./NotFoundCard";
import { PreviewCard } from "./PreviewCard";
import { QuestionCard } from "./QuestionCard";
import { RecentsPanel } from "./RecentsPanel";
import { RetrievingPanel } from "./RetrievingPanel";
import { SettingsBlob } from "./SettingsBlob";
import { SourcesCard } from "./SourcesCard";
import { StatusFooter } from "./StatusFooter";

import "./MagpieWindow.css";

// Window heights per state, per Specs/UI/ask_bar.md "Five states"
// table. Values are approximate — designer derives the exact sizes
// during PR 6 polish; these are the working baselines for now.
const WIDTH = 800;
// Resting comes in two flavors: empty (just the bar, ~96px) and
// with-recents (room for the recents panel below, ~320px). The
// resize effect picks the right value at render time based on the
// recents list length.
const HEIGHT_RESTING_EMPTY = 96;
const HEIGHT_RESTING_WITH_RECENTS = 320;
const HEIGHTS: Omit<Record<View["kind"], number>, "resting"> = {
  typing: 320,
  retrieving: 380,
  answering: 680,
  not_found: 280,
};

// Heuristic: Magpie's main window has focus → fire window-scoped
// shortcuts. Used to avoid double-firing Cmd+, on macOS where the
// native menu accelerator already handles it.
const IS_MAC = typeof navigator !== "undefined" &&
  /Mac|iPhone|iPad|iPod/.test(navigator.platform);

export function MagpieWindow() {
  const [view, setView] = useState<View>({ kind: "resting" });
  const [booting, setBooting] = useState(true);
  const [recents, setRecents] = useState<RecentEntry[] | null>(null);
  const [ingest, setIngest] = useState<IngestStatus | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // The previous `running` value from /ingest/status. Used to detect
  // the running→done transition without state churn.
  const prevIngestRunning = useRef(false);

  // Generation counter for race protection. Incremented on every new
  // ask submission. The async response checks if its captured gen
  // matches the current value; if not, the user has typed something
  // else / re-summoned / replayed a different recent in the meantime,
  // and the stale response is discarded. Without this, an in-flight
  // /query whose user-action context has changed would clobber the
  // current view (e.g., user blurred while retrieving, came back,
  // typed something new — old response still wins).
  const queryGenRef = useRef(0);

  // The Tauri sidecar port — pre-injected by lib.rs's setup() into
  // window.__MAGPIE_PORT__. Used by SettingsBlob for the open_settings
  // invoke arg.
  const port = (window as Window & { __MAGPIE_PORT__?: number }).__MAGPIE_PORT__ ?? 8765;

  // -------------------------------------------------------------------
  // Boot poll: hit /healthz every 500ms until the sidecar responds.
  // -------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const base = `http://127.0.0.1:${port}`;
    const tick = async () => {
      while (!cancelled) {
        try {
          const r = await fetch(`${base}/healthz`);
          if (r.ok && !cancelled) {
            setBooting(false);
            return;
          }
        } catch {
          // sidecar still warming up
        }
        await new Promise((res) => setTimeout(res, 500));
      }
    };
    tick();
    return () => { cancelled = true; };
  }, [port]);

  // -------------------------------------------------------------------
  // Ingest poll: 1.5s tick. Detects running→done transition for the
  // "indexing finished" focus-back handoff.
  // -------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      while (!cancelled) {
        await new Promise((res) => setTimeout(res, 1500));
        if (cancelled) break;
        try {
          const s = await getIngestStatus();
          if (cancelled) break;
          if (s.running) {
            prevIngestRunning.current = true;
            setIngest(s);
          } else if (prevIngestRunning.current) {
            prevIngestRunning.current = false;
            setIngest(null);
            // Re-focus the input on the running→done edge so the user
            // can immediately start typing without clicking back.
            requestAnimationFrame(() => inputRef.current?.focus());
          } else {
            setIngest(null);
          }
        } catch {
          // sidecar hiccup; try again next tick
        }
      }
    };
    tick();
    return () => { cancelled = true; };
  }, []);

  // -------------------------------------------------------------------
  // Window resize per view state. Resting is the only state with a
  // length-dependent height: empty when no recents, taller when
  // recents are populated (so they show on first summon).
  // -------------------------------------------------------------------
  const visibleRecentsCount = recents?.slice(0, 4).length ?? 0;
  const targetHeight =
    view.kind === "resting"
      ? (visibleRecentsCount > 0 ? HEIGHT_RESTING_WITH_RECENTS : HEIGHT_RESTING_EMPTY)
      : HEIGHTS[view.kind];
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { getCurrentWindow, LogicalSize } = await import("@tauri-apps/api/window");
        if (cancelled) return;
        await getCurrentWindow().setSize(new LogicalSize(WIDTH, targetHeight));
      } catch {
        // Not under Tauri (browser dev) — ignore.
      }
    })();
    return () => { cancelled = true; };
  }, [targetHeight]);

  // -------------------------------------------------------------------
  // Esc handler — dispatch by view.
  // -------------------------------------------------------------------
  useEffect(() => {
    const onKey = async (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      switch (view.kind) {
        case "resting":
          await hideWindow();
          break;
        case "typing":
          // Clear input → drop back to resting. Esc twice in a row
          // (resting → hide) closes the window.
          setView({ kind: "resting" });
          break;
        case "retrieving":
          // No /query/cancel API yet; just transition back to
          // typing with the question pre-filled.
          setView({ kind: "typing", query: view.question, selected: null });
          break;
        case "answering":
        case "not_found":
          // Return to typing with the question pre-filled so the
          // user can refine and re-submit.
          setView({ kind: "typing", query: view.question, selected: null });
          requestAnimationFrame(() => inputRef.current?.focus());
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view]);

  // -------------------------------------------------------------------
  // Spotlight-style typing-replaces-selection for views WITHOUT an
  // input element (answering / not_found). The question header in
  // those states is a button, not an input — so a real
  // setSelectionRange isn't possible. We simulate it: any printable
  // single-character keystroke transitions to typing state with that
  // character as the new input; Backspace transitions to typing
  // with empty input. Net effect matches Spotlight: re-summon,
  // start typing → replaces; backspace → clears.
  // -------------------------------------------------------------------
  useEffect(() => {
    if (view.kind !== "answering" && view.kind !== "not_found") return;
    const onKey = (e: KeyboardEvent) => {
      // Skip if any modifier keys other than Shift are held — those
      // are app-level shortcuts (Cmd+C, Cmd+,, etc.), not typing.
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      // Skip non-printable except Backspace (Enter, arrow keys, F-keys, etc.).
      const isPrintable = e.key.length === 1;
      if (!isPrintable && e.key !== "Backspace") return;
      e.preventDefault();
      const newQuery = e.key === "Backspace" ? "" : e.key;
      // Increment the gen counter so any in-flight /query from this
      // view's question gets discarded on return.
      queryGenRef.current++;
      setView({ kind: "typing", query: newQuery, selected: null });
      requestAnimationFrame(() => {
        const el = inputRef.current;
        if (!el) return;
        el.focus();
        try { el.setSelectionRange(newQuery.length, newQuery.length); } catch { /* ok */ }
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view.kind]);

  // -------------------------------------------------------------------
  // Cmd+, / Ctrl+, → open settings. macOS uses the native menu
  // accelerator (registered in lib.rs); Windows + Linux use this
  // window-level keydown listener so the shortcut still works there.
  // -------------------------------------------------------------------
  useEffect(() => {
    if (IS_MAC) return; // native menu handles it
    const onKey = async (e: KeyboardEvent) => {
      if (e.key === "," && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        try {
          await invoke("open_settings", { port });
        } catch {
          // not under Tauri
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [port]);

  // -------------------------------------------------------------------
  // Auto-focus input when boot completes, and on Tauri window focus.
  // -------------------------------------------------------------------
  useEffect(() => {
    if (!booting) requestAnimationFrame(() => inputRef.current?.focus());
  }, [booting]);

  useEffect(() => {
    let cleanups: Array<() => void> = [];
    (async () => {
      try {
        const { getCurrentWindow } = await import("@tauri-apps/api/window");
        const appWindow = getCurrentWindow();

        // On focus (re-summon via Alt+Space, tray click, etc.), DO NOT
        // reset the view state — the user expects to come back to
        // whatever they were doing (still-retrieving, the previous
        // answer, the not-found card).
        //
        // Spotlight-style "select all" on focus: when the input is
        // visible (resting/typing) and contains text, select it so
        // the user's next keystroke replaces it and Backspace clears
        // it wholesale. For answering/not_found states (no input —
        // the question is a header button), the keystroke handler
        // below provides the same UX without needing real selection.
        const unFocus = await appWindow.listen("tauri://focus", () => {
          requestAnimationFrame(() => {
            const el = inputRef.current;
            if (!el) return;
            el.focus();
            if (el.value.length > 0) {
              try { el.setSelectionRange(0, el.value.length); } catch { /* ok */ }
            }
          });
        });
        cleanups.push(unFocus);

        // On blur (user clicks another app or presses Cmd+Tab),
        // hide the window. Spotlight pattern. The recents panel and
        // any in-flight question state survive — re-summon brings the
        // user back to a fresh resting bar; the recents panel will
        // show the just-asked question on next type.
        const unBlur = await appWindow.listen("tauri://blur", () => {
          hideWindow();
        });
        cleanups.push(unBlur);
      } catch {
        // Not under Tauri — ignore.
      }
    })();
    return () => cleanups.forEach((fn) => fn());
  }, []);

  // -------------------------------------------------------------------
  // Submit / replay handlers
  // -------------------------------------------------------------------

  const submitQuestion = useCallback(async (question: string) => {
    const trimmed = question.trim();
    if (!trimmed) return;
    const myGen = ++queryGenRef.current;
    setView({ kind: "retrieving", question: trimmed });
    try {
      const result = await postQuery(trimmed);
      // Race guard: if the user typed something else, replayed a
      // different recent, or otherwise changed context while this
      // query was in flight, queryGenRef has advanced and our
      // response is stale. Drop it on the floor.
      if (myGen !== queryGenRef.current) return;
      // Append to in-memory recents if the backend returned an id —
      // saves a re-fetch and keeps the panel snappy.
      if (result.recent_id !== null) {
        const newEntry: RecentEntry = {
          id: result.recent_id,
          asked_at: new Date().toISOString(),
          question: trimmed,
          rewritten_query: result.search_query.query ?? null,
          result: {
            answer: result.answer,
            sources_used: result.sources.filter((s) => s.cited).map((s) => s.path),
            not_found: result.not_found,
            not_found_topic: result.not_found_topic,
          },
        };
        setRecents((prev) => prev === null ? [newEntry] : [newEntry, ...prev].slice(0, 10));
      }
      if (result.not_found) {
        setView({ kind: "not_found", question: trimmed, result });
      } else {
        const firstCited = result.sources.find((s) => s.cited)?.path ?? null;
        setView({
          kind: "answering",
          question: trimmed,
          result,
          selectedPath: firstCited,
        });
      }
    } catch (e) {
      // Race guard applies to errors too — if context changed, drop
      // the failure rather than overriding the user's new state.
      if (myGen !== queryGenRef.current) return;
      // Treat hard /query failures as not-found (the network/sidecar
      // hiccup case). The error string isn't shown — Magpie's spec
      // surface stays user-friendly. Devs see the failure in stderr.
      console.error("query failed:", e);
      setView({
        kind: "not_found",
        question: trimmed,
        result: makeErrorResult(trimmed),
      });
    }
  }, []);

  // Both ⏎-on-recent and the ↻ Ask-again button route through this.
  // Per the user's resolved decision: cached if fresh, fresh /query if
  // the index has changed since the recent was persisted (server-side
  // is_stale flag, manifest mtime as the proxy).
  //
  // We re-fetch the recent right before deciding so a sync that
  // completed between the initial /recents fetch and the user's click
  // is reflected. The list-fetch's stamped is_stale is a hint; this is
  // the authoritative read.
  const replayRecent = useCallback(async (entry: RecentEntry) => {
    // Race guard: replays count as a context change too. Bumping the
    // gen counter discards any /query response that arrives later.
    const myGen = ++queryGenRef.current;

    // Re-check freshness server-side. Network failure → fall back to
    // the optimistic in-memory value.
    let isStale = entry.is_stale ?? false;
    try {
      const fresh = await getRecent(entry.id);
      if (fresh && fresh.is_stale !== undefined) isStale = fresh.is_stale;
    } catch {
      // sidecar hiccup; trust the optimistic value
    }
    if (myGen !== queryGenRef.current) return;

    if (isStale) {
      // Index changed — re-run the pipeline.
      submitQuestion(entry.question);
      return;
    }

    // Render the cached payload directly (no LLM call).
    if (entry.result.not_found) {
      setView({
        kind: "not_found",
        question: entry.question,
        result: synthesizeQueryResponse(entry, /*not_found*/ true),
      });
      return;
    }
    const synth = synthesizeQueryResponse(entry, false);
    setView({
      kind: "answering",
      question: entry.question,
      result: synth,
      selectedPath: synth.sources.find((s) => s.cited)?.path ?? null,
    });
  }, [submitQuestion]);

  // The ↻ Ask-again button. Same smart-cached behavior as ⏎-on-recent
  // — both buttons honor staleness uniformly (per the resolved
  // decision). Kept as a separate user-facing affordance for the
  // explicit "give me this question again" gesture.
  const askAgain = useCallback(async (entry: RecentEntry) => {
    replayRecent(entry);
  }, [replayRecent]);

  // Click-to-edit / follow-up: revert to typing state with the
  // current question pre-filled. Both the question-header click and
  // the AnswerCard's "+ follow up" button route here. Lets the user
  // refine a question and re-ask without going through Esc.
  const editCurrentQuestion = useCallback(() => {
    if (
      view.kind === "answering" ||
      view.kind === "not_found" ||
      view.kind === "retrieving"
    ) {
      const q = view.question;
      setView({ kind: "typing", query: q, selected: null });
      requestAnimationFrame(() => {
        const el = inputRef.current;
        if (!el) return;
        el.focus();
        // Move caret to the end so the user can immediately keep
        // typing (Ctrl-A to select-all if they want to replace).
        const len = q.length;
        try { el.setSelectionRange(len, len); } catch { /* ok */ }
      });
    }
  }, [view]);

  // -------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------

  // Highlight tokens for the answer prose. Computed once per result.
  const highlights = useMemo(
    () => view.kind === "answering" ? extractHighlightTokens(view.result.answer) : [],
    [view]
  );

  // Search-pill props per view.
  const inputValue =
    view.kind === "typing" ? view.query :
    view.kind === "retrieving" ? view.question :
    view.kind === "answering" || view.kind === "not_found" ? view.question :
    "";
  const submittedQuestion =
    view.kind === "retrieving" || view.kind === "answering" || view.kind === "not_found"
      ? view.question : null;

  const onInputChange = (q: string) => {
    if (q === "") setView({ kind: "resting" });
    else setView({ kind: "typing", query: q, selected: null });
  };

  const onInputSubmit = () => {
    if (view.kind === "typing" && view.selected !== null && recents) {
      const visible = recents.slice(0, 4);
      const sel = visible[view.selected];
      if (sel) { replayRecent(sel); return; }
    }
    submitQuestion(inputValue);
  };

  // Recents-keyboard nav: active in both resting and typing state, so
  // the user can ↑/↓ through recents immediately on summon (no typing
  // required to discover them).
  useEffect(() => {
    if (view.kind !== "resting" && view.kind !== "typing") return;
    if (!recents) return;
    const visible = recents.slice(0, 4);
    if (visible.length === 0) return;
    const currentSelected = view.kind === "typing" ? view.selected : null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        const next = currentSelected === null ? 0 :
          Math.min(currentSelected + 1, visible.length - 1);
        if (view.kind === "typing") {
          setView({ ...view, selected: next });
        } else {
          setView({ kind: "typing", query: "", selected: next });
        }
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const next = currentSelected === null ? visible.length - 1 :
          Math.max(currentSelected - 1, 0);
        if (view.kind === "typing") {
          setView({ ...view, selected: next });
        } else {
          setView({ kind: "typing", query: "", selected: next });
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, recents]);

  // Active state for QuestionCard's display-as-title-row vs. input.
  return (
    <div className={`magpie-window magpie-window--${view.kind}`}>
      <div className="magpie-window__top-row">
        <QuestionCard
          ref={inputRef}
          value={inputValue}
          onChange={onInputChange}
          onSubmit={onInputSubmit}
          loading={view.kind === "retrieving"}
          booting={booting}
          submittedQuestion={submittedQuestion}
          onEditQuestion={editCurrentQuestion}
        />
        <SettingsBlob port={port} />
      </div>

      {/* Background indexing card — only shown when not actively asking. */}
      {ingest?.running && (view.kind === "resting" || view.kind === "typing") && (
        <IndexingOverlay ingest={ingest} onStop={stopIngest} />
      )}

      {/* Body per view. Recents panel renders in BOTH resting and
          typing — so the user sees their history immediately on
          summon and doesn't have to type to discover it. */}
      {(view.kind === "resting" || view.kind === "typing") && (
        <RecentsPanel
          selected={view.kind === "typing" ? view.selected : null}
          onSelectIndex={(i) => {
            // Selection only meaningful in typing state. Promote
            // from resting on first arrow-key navigation.
            if (view.kind === "typing") {
              setView({ ...view, selected: i });
            } else {
              setView({ kind: "typing", query: "", selected: i });
            }
          }}
          onReplay={replayRecent}
          onAskAgain={askAgain}
          recents={recents}
          setRecents={setRecents}
        />
      )}

      {view.kind === "retrieving" && (
        <RetrievingPanel documentsTotal={view.question.length /* placeholder */} />
      )}

      {view.kind === "answering" && (
        <AnsweringBody
          result={view.result}
          selectedPath={view.selectedPath}
          onSelect={(path) => setView({ ...view, selectedPath: path })}
          onFollowUp={editCurrentQuestion}
          highlights={highlights}
        />
      )}

      {view.kind === "not_found" && (
        <NotFoundCard
          scannedCount={view.result.sources_scanned_count}
          topic={view.result.not_found_topic || view.question}
        />
      )}

      <StatusFooter
        view={view.kind}
        booting={booting}
        ingestRunning={Boolean(ingest?.running)}
        ingestFilesDone={ingest?.files_done ?? 0}
        ingestFilesTotal={ingest?.files_total ?? 0}
      />
    </div>
  );
}

// -------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------

function AnsweringBody({
  result,
  selectedPath,
  onSelect,
  onFollowUp,
  highlights,
}: {
  result: QueryResponse;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onFollowUp: () => void;
  highlights: string[];
}) {
  return (
    <div className="magpie-grid">
      <div className="magpie-col-left">
        <AnswerCard
          answer={result.answer}
          sources={result.sources}
          highlights={highlights}
          error={null}
          loading={false}
          onFollowUp={onFollowUp}
          onSelectSource={onSelect}
        />
        <SourcesCard
          sources={result.sources}
          selectedPath={selectedPath}
          onSelect={onSelect}
          highlights={highlights}
        />
      </div>
      <div className="magpie-col-right">
        <PreviewCard path={selectedPath} highlights={highlights} />
      </div>
    </div>
  );
}

function IndexingOverlay({
  ingest,
  onStop,
}: {
  ingest: IngestStatus;
  onStop: () => void;
}) {
  const pct = ingest.files_total > 0
    ? Math.round((ingest.files_done / ingest.files_total) * 100)
    : 0;
  return (
    <div className="indexing-overlay magpie-card">
      <p className="indexing-overlay__message">
        {ingest.files_total > 0
          ? `Understanding ${ingest.files_done.toLocaleString()} / ${ingest.files_total.toLocaleString()} files…`
          : "Scanning files…"}
      </p>
      {ingest.files_total > 0 && (
        <div className="indexing-overlay__bar">
          <div className="indexing-overlay__bar-fill" style={{ width: `${pct}%` }} />
        </div>
      )}
      {ingest.current_file && (
        <p className="indexing-overlay__detail">
          {ingest.current_file.length > 44
            ? `…${ingest.current_file.slice(-42)}`
            : ingest.current_file}
        </p>
      )}
      <button className="indexing-overlay__stop" onClick={onStop}>
        Stop indexing
      </button>
    </div>
  );
}

/**
 * Build a QueryResponse-shaped object from a cached RecentEntry so
 * the answering view can render replays without a re-fetch. Sources
 * are reconstructed from the stored sources_used (path-only); score
 * defaults to 1.0 since we don't persist the original retrieval
 * scores. Cited=true for everything in sources_used (those ARE the
 * cited ones by definition).
 */
function synthesizeQueryResponse(
  entry: RecentEntry,
  notFound: boolean
): QueryResponse {
  return {
    question: entry.question,
    answer: entry.result.answer,
    sources: entry.result.sources_used.map((path) => ({
      path,
      summary: "",
      score: 1.0,
      cited: true,
    })),
    search_query: { query: entry.rewritten_query ?? entry.question, keywords: [] },
    not_found: notFound,
    not_found_topic: entry.result.not_found_topic,
    sources_scanned_count: entry.result.sources_used.length,
    recent_id: entry.id,
  };
}

function makeErrorResult(question: string): QueryResponse {
  return {
    question,
    answer: "",
    sources: [],
    search_query: { query: question, keywords: [] },
    not_found: true,
    not_found_topic: question.replace(/\?+$/, "").trim(),
    sources_scanned_count: 0,
    recent_id: null,
  };
}

async function hideWindow() {
  try {
    const { getCurrentWindow, LogicalSize } = await import("@tauri-apps/api/window");
    const win = getCurrentWindow();
    await win.setSize(new LogicalSize(WIDTH, HEIGHT_RESTING_EMPTY));
    await win.hide();
  } catch {
    // not under Tauri
  }
}
