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
  getRecents,
  getStatus,
  postQueryStream,
  stopIngest,
} from "../api";
import type { IngestStatus } from "../api";
import type { QueryResponse, RecentEntry, Source } from "../types";
import type { View } from "./viewState";
import { extractHighlightTokens } from "./Highlighted";

import { AnswerCard } from "./AnswerCard";
import { dragState, startDragOnMouseDown } from "./dragWindow";
import { NotFoundCard } from "./NotFoundCard";
import { PreviewCard } from "./PreviewCard";
import { QuestionCard } from "./QuestionCard";
import { RecentsPanel } from "./RecentsPanel";
import { RetrievingPanel } from "./RetrievingPanel";
import { SettingsBlob } from "./SettingsBlob";
import { SourcesCard } from "./SourcesCard";
import { StatusFooter } from "./StatusFooter";
import { WelcomeCard } from "./WelcomeCard";

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
// Height when the WelcomeCard is showing (empty corpus, first launch).
// Same value as HEIGHT_RESTING_WITH_RECENTS — the card occupies a
// similar amount of body space as the recents panel does.
const HEIGHT_RESTING_WELCOME = 320;
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
  // Total file count Magpie has read (manifest size, surfaced via
  // /status). Used by RetrievingPanel for "scanning N docs" copy
  // and by NotFoundCard's recents-replay fallback. Refreshed on
  // boot and after each ingest completion.
  const [indexedCount, setIndexedCount] = useState(0);
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

  // Conversation history — last N (question, answer) pairs sent to
  // the answer LLM as context so follow-up questions resolve
  // references like "the test", "it", "the same one". Session-scoped
  // ONLY: empty on app start, populated as the user asks, destroyed
  // when the React mount unmounts (= app quit). Distinct from
  // recents.json (which is persisted to disk and drives the recents
  // panel's UI). Recents > history because recents survive restarts;
  // history dies with the session per the user's spec.
  //
  // Cap kept low (HISTORY_TURNS = 5) so the prompt doesn't bloat —
  // each turn adds ~300-500 tokens of (Q, A) text. answer.py's
  // SYSTEM_PROMPT already has the "use prior turns to resolve
  // references" instruction.
  const HISTORY_TURNS = 5;
  const historyRef = useRef<Array<{ question: string; answer: string }>>([]);

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

  // Indexed file count — refreshed on boot and after each ingest run.
  // Used by RetrievingPanel ("scanning N docs") and as the fallback
  // count when replaying not-found recents.
  useEffect(() => {
    if (booting) return;
    getStatus().then((s) => setIndexedCount(s.indexed_count)).catch(() => { /* non-fatal */ });
  }, [booting]);

  // -------------------------------------------------------------------
  // Recents fetch — fires once after boot completes. Doing this here
  // (not inside RecentsPanel) avoids a race where RecentsPanel's
  // useEffect ran on mount before the sidecar was ready, getting a
  // network error and rendering "Recents unavailable: Load failed".
  // After this, the recents list is owned in MagpieWindow state and
  // mutated locally after each ask (no re-fetch needed).
  // -------------------------------------------------------------------
  useEffect(() => {
    if (booting || recents !== null) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await getRecents();
        if (!cancelled) setRecents(list);
      } catch (e) {
        if (cancelled) return;
        // One retry after a short delay — the boot poll's /healthz
        // might have responded before all routes were live.
        await new Promise((r) => setTimeout(r, 750));
        if (cancelled) return;
        try {
          const list = await getRecents();
          if (!cancelled) setRecents(list);
        } catch (err) {
          // Still failing — fall back to empty list. The user gets a
          // panel that says "no recents yet" rather than "load
          // failed", which is at least visually clean. They can ask
          // a question; the recents will populate from there.
          console.warn("recents load failed; falling back to empty:", err);
          if (!cancelled) setRecents([]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [booting, recents]);

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
            // Refresh the indexed count so "scanning N docs" reflects
            // the post-ingest manifest size on the next retrieval.
            getStatus().then((st) => setIndexedCount(st.indexed_count)).catch(() => {});
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
  // Retrieving has two heights: the brief full-bleed RetrievingPanel
  // window (rewrite + retrieval, ~500ms-3s) uses HEIGHTS.retrieving,
  // and the moment partialSources arrive we expand to HEIGHTS.answering
  // since the body adopts the answering-shaped two-column layout.
  const retrievingWithSources =
    view.kind === "retrieving" && view.partialSources !== null;
  // First-launch / empty-corpus onboarding card. Renders below the input
  // bar in resting state when Magpie has no indexed files, the sidecar
  // is up, and no ingest is currently running (which would have its own
  // IndexingOverlay). Takes priority over the recents panel because the
  // user can't have recents without files to query against.
  const showWelcomeCard =
    view.kind === "resting" &&
    !booting &&
    !ingest?.running &&
    indexedCount === 0;
  const targetHeight =
    view.kind === "resting"
      ? (showWelcomeCard
          ? HEIGHT_RESTING_WELCOME
          : (visibleRecentsCount > 0 ? HEIGHT_RESTING_WITH_RECENTS : HEIGHT_RESTING_EMPTY))
      : retrievingWithSources
      ? HEIGHTS.answering
      : HEIGHTS[view.kind];
  // Mirror targetHeight into a ref so the tauri://focus listener
  // (registered once on mount) can read the latest value without
  // re-registering every time the height changes. Otherwise the
  // listener would close over a stale value.
  const targetHeightRef = useRef(targetHeight);
  useEffect(() => { targetHeightRef.current = targetHeight; }, [targetHeight]);
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
        // Two things happen on focus:
        //   1. Force a window resize to the current targetHeight.
        //      This is defense in depth — if the window size drifted
        //      while hidden (it shouldn't, but Tauri/macOS sometimes
        //      mutate dimensions on hide/show), we restore it before
        //      the user sees a clipped body.
        //   2. Spotlight-style "select all" on focus when the input
        //      has text. The input is now ALWAYS rendered (post the
        //      "always-input" rewrite), so selectAll works in every
        //      view state including answering / not_found.
        const unFocus = await appWindow.listen("tauri://focus", async () => {
          try {
            const { LogicalSize } = await import("@tauri-apps/api/window");
            await appWindow.setSize(new LogicalSize(WIDTH, targetHeightRef.current));
          } catch { /* not under Tauri */ }
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
        //
        // EXCEPT right after a drag starts: on Windows, entering the
        // native window-move loop fires a blur — hiding then made
        // every drag attempt vanish the window into the background.
        // Blurs within a short window of startDragging() are the
        // drag itself, not the user leaving; ignore them.
        const unBlur = await appWindow.listen("tauri://blur", () => {
          if (Date.now() - dragState.lastDragStartAt < 800) return;
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
    // Initial retrieving view — full-bleed RetrievingPanel until the
    // `sources` SSE event lands. partialSources stays null during the
    // rewrite + retrieval window so the renderer keeps showing the
    // existing full-height spinner; once sources arrive we set them
    // and the body switches to the answering-shaped layout.
    setView({
      kind: "retrieving",
      question: trimmed,
      partialSources: null,
      selectedPath: null,
    });
    const historyToSend = historyRef.current.slice(-HISTORY_TURNS);

    // Streaming accumulator — captures every event as it arrives so we
    // can build the final QueryResponse on `done`. Defaults match what
    // an empty backend response would look like, so partial-stream
    // failures still produce a coherent final view.
    let sources: Source[] = [];
    const searchQuery = { query: "", keywords: [] } as { query: string; keywords: string[] };
    let rewrittenQuery: string | null = null;
    let sourcesScannedCount = 0;
    const answerChunks: string[] = [];
    let sourcesUsed: string[] = [];
    let notFoundTopic: string | null = null;
    let recentId: string | null = null;
    let streamError: string | null = null;

    try {
      for await (const ev of postQueryStream(trimmed, { history: historyToSend })) {
        // Race guard at every event — if the user typed something
        // else, replayed a different recent, or otherwise changed
        // context mid-stream, queryGenRef has advanced and our
        // remaining events are stale. Drop them on the floor; the
        // sidecar finishes its work and writes the recent regardless.
        if (myGen !== queryGenRef.current) return;
        switch (ev.type) {
          case "sources":
            sources = ev.sources;
            searchQuery.query = ev.searchQuery.query;
            searchQuery.keywords = ev.searchQuery.keywords;
            rewrittenQuery = ev.rewrittenQuery;
            sourcesScannedCount = ev.sourcesScannedCount;
            // Body transitions to the answering-shaped two-column
            // layout. Spinner stays in the AnswerCard slot until the
            // answer event arrives; sources card is interactive
            // immediately (clickable, preview pane updates).
            setView({
              kind: "retrieving",
              question: trimmed,
              partialSources: ev.sources,
              selectedPath: ev.sources[0]?.path ?? null,
            });
            break;
          case "not_found_topic":
            notFoundTopic = ev.topic;
            break;
          case "answer_chunk":
            // Phase 1: this fires exactly once with the full answer
            // text. Phase 2 (Plan #35) will fire many times; the
            // accumulator handles both shapes identically.
            answerChunks.push(ev.text);
            break;
          case "sources_used":
            sourcesUsed = ev.paths;
            break;
          case "error":
            streamError = ev.detail;
            break;
          case "done":
            recentId = ev.recentId;
            break;
        }
      }
      // Final race guard before applying terminal state — defends
      // against a context change that happened on the very last event.
      if (myGen !== queryGenRef.current) return;

      if (streamError !== null) {
        console.error("query stream error:", streamError);
        setView({
          kind: "not_found",
          question: trimmed,
          result: makeErrorResult(trimmed),
        });
        return;
      }

      const isNotFound = notFoundTopic !== null;
      const finalAnswer = isNotFound ? "" : answerChunks.join("");
      const citedSet = new Set(sourcesUsed);
      const finalSources: Source[] = sources.map((s) => ({
        ...s,
        cited: citedSet.has(s.path),
      }));
      const result: QueryResponse = {
        question: trimmed,
        answer: finalAnswer,
        sources: finalSources,
        search_query: searchQuery,
        not_found: isNotFound,
        not_found_topic: notFoundTopic ?? "",
        sources_scanned_count: sourcesScannedCount,
        sources_used: sourcesUsed,
        recent_id: recentId,
      };

      // Append to in-memory history if we got a real answer (not the
      // not-found case). History serves the LLM, not the user, so
      // not-found turns aren't useful context. Single-session only;
      // historyRef dies with the React mount.
      if (!isNotFound && finalAnswer) {
        historyRef.current.push({ question: trimmed, answer: finalAnswer });
        if (historyRef.current.length > HISTORY_TURNS) {
          historyRef.current = historyRef.current.slice(-HISTORY_TURNS);
        }
      }
      // Append to in-memory recents if the backend returned an id —
      // saves a re-fetch and keeps the panel snappy.
      if (recentId !== null) {
        const newEntry: RecentEntry = {
          id: recentId,
          asked_at: new Date().toISOString(),
          question: trimmed,
          rewritten_query: rewrittenQuery,
          result: {
            answer: finalAnswer,
            sources_used: sourcesUsed,
            not_found: isNotFound,
            not_found_topic: notFoundTopic ?? "",
          },
        };
        setRecents((prev) => prev === null ? [newEntry] : [newEntry, ...prev].slice(0, 10));
      }

      if (isNotFound) {
        setView({ kind: "not_found", question: trimmed, result });
      } else {
        const firstCited = finalSources.find((s) => s.cited)?.path ?? null;
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
      // Treat hard /query/stream failures as not-found (the network/
      // sidecar hiccup case). The error string isn't shown — Magpie's
      // spec surface stays user-friendly. Devs see the failure in
      // stderr.
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

  // Follow-up affordance: focus the input + select-all so the user's
  // next keystroke either replaces the question (typing replaces the
  // selection) or refines via arrow keys. The input is always
  // rendered now (no question-as-button), so we just hand focus.
  const focusAndSelectInput = useCallback(() => {
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (!el) return;
      el.focus();
      if (el.value.length > 0) {
        try { el.setSelectionRange(0, el.value.length); } catch { /* ok */ }
      }
    });
  }, []);

  // -------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------

  // Highlight tokens for the answer prose. Computed once per result.
  const highlights = useMemo(
    () => view.kind === "answering" ? extractHighlightTokens(view.result.answer) : [],
    [view]
  );

  // Search-pill props per view. The input is now ALWAYS rendered (no
  // more question-as-button); its value is the question for active
  // states (so re-summon shows the previous question selectable), the
  // typed-so-far for typing, and empty for resting.
  const inputValue =
    view.kind === "typing" ? view.query :
    view.kind === "retrieving" ? view.question :
    view.kind === "answering" || view.kind === "not_found" ? view.question :
    "";
  const isActive =
    view.kind === "retrieving" ||
    view.kind === "answering" ||
    view.kind === "not_found";

  const onInputChange = (q: string) => {
    // Any edit transitions to typing/resting state. Bumping the gen
    // counter discards any /query response that's still in flight
    // from a prior submit — so old answers don't clobber the new
    // typing state.
    if (view.kind !== "typing" && view.kind !== "resting") {
      queryGenRef.current++;
    }
    if (q === "") setView({ kind: "resting" });
    else setView({ kind: "typing", query: q, selected: null });
  };

  const onInputSubmit = () => {
    if (view.kind === "typing" && view.selected !== null && recents) {
      const visible = recents.slice(0, 4);
      const sel = visible[view.selected];
      if (sel) { replayRecent(sel); return; }
    }
    // Submit-on-already-asked is a re-ask of the same question. The
    // user explicitly pressed Enter — honor it. (Smart cached-replay
    // is on the recents path; direct re-submit always fires fresh.)
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

  // Grab-anywhere window dragging (Spotlight behavior): any mousedown
  // on empty space — gaps between cards, side margins, the status
  // footer — moves the window. Content cards are excluded so text in
  // answers/sources/previews stays selectable; the QuestionCard has
  // its own drag handler for the bar itself.
  const onWindowMouseDown = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (target.closest(".magpie-card")) return;
    startDragOnMouseDown(e);
  }, []);

  // Active state for QuestionCard's display-as-title-row vs. input.
  return (
    <div
      className={`magpie-window magpie-window--${view.kind}`}
      onMouseDown={onWindowMouseDown}
    >
      <div className="magpie-window__top-row">
        <QuestionCard
          ref={inputRef}
          value={inputValue}
          onChange={onInputChange}
          onSubmit={onInputSubmit}
          loading={view.kind === "retrieving"}
          booting={booting}
          isActive={isActive}
        />
        <SettingsBlob port={port} />
      </div>

      {/* Background indexing card — only shown when not actively asking. */}
      {ingest?.running && (view.kind === "resting" || view.kind === "typing") && (
        <IndexingOverlay ingest={ingest} onStop={stopIngest} />
      )}

      {/* First-launch / empty-corpus onboarding. Takes priority over the
          recents panel since the user can't have recents without a corpus. */}
      {showWelcomeCard && <WelcomeCard />}

      {/* Body per view. Recents panel renders in BOTH resting and
          typing — so the user sees their history immediately on
          summon and doesn't have to type to discover it. Suppressed
          when the WelcomeCard is showing (resting + empty corpus);
          typing-with-empty-corpus still renders RecentsPanel which
          will simply be empty — that path is rare and harmless. */}
      {(view.kind === "resting" || view.kind === "typing") && !showWelcomeCard && (
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

      {view.kind === "retrieving" && view.partialSources === null && (
        <RetrievingPanel documentsTotal={indexedCount} />
      )}

      {view.kind === "retrieving" && view.partialSources !== null && (
        // Retrieving-with-sources: same two-column layout as answering,
        // with the AnswerCard in `loading=true` (animated dots) until
        // the answer event lands. Sources are clickable, the right-pane
        // PreviewCard is live — the user can browse the pulled files
        // while the LLM thinks. Synthesized QueryResponse here is just
        // a shell to feed AnsweringBody; the real one is built when
        // `done` arrives and the view transitions to `answering`.
        <AnsweringBody
          result={{
            question: view.question,
            answer: "",
            sources: view.partialSources,
            search_query: { query: "", keywords: [] },
            not_found: false,
            not_found_topic: "",
            sources_scanned_count: 0,
            sources_used: [],
            recent_id: null,
          }}
          selectedPath={view.selectedPath}
          onSelect={(path) => {
            if (view.kind !== "retrieving") return;
            setView({ ...view, selectedPath: path });
          }}
          onFollowUp={focusAndSelectInput}
          highlights={[]}
          loading={true}
        />
      )}

      {view.kind === "answering" && (
        <AnsweringBody
          result={view.result}
          selectedPath={view.selectedPath}
          onSelect={(path) => setView({ ...view, selectedPath: path })}
          onFollowUp={focusAndSelectInput}
          highlights={highlights}
          loading={false}
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
  loading,
}: {
  result: QueryResponse;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onFollowUp: () => void;
  highlights: string[];
  // True during retrieving-with-sources (answer LLM still running);
  // false once the answer has arrived and the view is `answering`.
  // AnswerCard renders animated dots when loading, the rendered
  // answer text otherwise.
  loading: boolean;
}) {
  // Inline `[N]` markers are 1-based indexes into sources_used (the
  // ordered list of files the answer drew from) — NOT into the full
  // retrieval list. Resolving against the wrong list made citation
  // pills open unrelated files (e.g. [4] = 4th-ranked candidate, a
  // random shell script, instead of the 4th cited document). If a
  // cited path is missing from the retrieval list (backend filtered
  // it), synthesize a stub so the pill still previews the right file.
  const citedSources: Source[] = result.sources_used.map(
    (path) =>
      result.sources.find((s) => s.path === path) ?? {
        path,
        summary: "",
        score: 0,
        cited: true,
      },
  );
  return (
    <div className="magpie-grid">
      <div className="magpie-col-left">
        <AnswerCard
          answer={result.answer}
          sources={citedSources}
          highlights={highlights}
          error={null}
          loading={loading}
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
    sources_used: entry.result.sources_used,
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
    sources_used: [],
    recent_id: null,
  };
}

async function hideWindow() {
  // DO NOT shrink the window before hiding. Earlier versions did
  // setSize(WIDTH, HEIGHT_RESTING_EMPTY) here for the "next summon
  // appears compact" effect, but it broke state preservation: on
  // re-summon, the window stayed at 96px even though view.kind was
  // still answering/retrieving (the resize useEffect's deps include
  // targetHeight, which didn't change across the hide/show), so the
  // body content rendered below the input was simply clipped — the
  // user saw a blank bar and thought the state was lost. Keeping the
  // current size means re-summon shows the same window the user left.
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().hide();
  } catch {
    // not under Tauri
  }
}
