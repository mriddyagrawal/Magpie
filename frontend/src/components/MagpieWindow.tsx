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

  // Spotlight behavior: Esc always hides. State reset happens on next summon,
  // so the user sees a clean input when they re-invoke the window.
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

  // Wire Tauri window events: blur → hide, focus → reset + focus input.
  // Spotlight semantics: always hide on blur, regardless of dev/prod.
  useEffect(() => {
    let cleanups: Array<() => void> = [];
    (async () => {
      try {
        const { getCurrentWindow } = await import("@tauri-apps/api/window");
        const appWindow = getCurrentWindow();

        const unBlur = await appWindow.listen("tauri://blur", () => {
          appWindow.hide();
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
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().hide();
  } catch {
    /* not under Tauri */
  }
}
