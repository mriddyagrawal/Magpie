/**
 * FeedbackBox — the one-click beta feedback channel under an answer.
 *
 *   closed   → a quiet "send feedback" text button (followup-button styling)
 *   open     → textarea + privacy hint + optional include-Q&A checkbox
 *   sending  → submit disabled
 *   sent     → "Thanks — it reached us."
 *   queued   → honest offline copy (store-and-forward on the sidecar)
 *   error    → friendlyError line; the typed text is NOT cleared
 *
 * Privacy contract mirrors src/feedback.py: nothing is sent except on
 * an explicit Submit, and the Q&A pair goes along only when the user
 * ticks the checkbox. The hint under the box says exactly that.
 *
 * Parent should key this by question (`<FeedbackBox key={question} …>`)
 * so a fresh answer gets a fresh box instead of a stale "sent" state.
 */

import { useEffect, useRef, useState } from "react";
import { friendlyError, postFeedback } from "../api";
import "./FeedbackBox.css";

type Phase = "closed" | "open" | "sending" | "sent" | "queued" | "error";

const MESSAGE_CAP = 4000; // keep in sync with src/feedback.py MESSAGE_CAP

export function FeedbackBox({
  question,
  answer,
}: {
  question: string;
  answer: string;
}) {
  const [phase, setPhase] = useState<Phase>("closed");
  const [message, setMessage] = useState("");
  const [includeQA, setIncludeQA] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (phase === "open") boxRef.current?.focus();
  }, [phase]);

  const send = async () => {
    const msg = message.trim();
    if (!msg) return;
    setPhase("sending");
    setError(null);
    try {
      const out = await postFeedback(
        msg,
        includeQA ? { question, answer } : undefined
      );
      setPhase(out.delivered ? "sent" : "queued");
      setMessage("");
    } catch (e) {
      // Keep the typed text — losing a paragraph to a network blip is
      // exactly the frustration this box exists to collect.
      setError(friendlyError(e));
      setPhase("error");
    }
  };

  if (phase === "closed") {
    return (
      <button
        type="button"
        className="feedback-box__opener"
        onClick={() => setPhase("open")}
      >
        ✎ send feedback
      </button>
    );
  }

  if (phase === "sent" || phase === "queued") {
    return (
      <div className="feedback-box feedback-box--done">
        {phase === "sent"
          ? "Thanks — your feedback reached us."
          : "Saved — you look offline. It will be sent automatically when Magpie is next online."}
      </div>
    );
  }

  return (
    <div className="feedback-box magpie-card">
      <div className="feedback-box__label">FEEDBACK</div>
      {error && <div className="feedback-box__error">⚠ {error}</div>}
      <textarea
        ref={boxRef}
        className="feedback-box__input"
        placeholder="A line or a paragraph — what worked, what didn't, what's missing…"
        value={message}
        maxLength={MESSAGE_CAP}
        rows={3}
        onChange={(e) => setMessage(e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") send();
        }}
      />
      <label className="feedback-box__context">
        <input
          type="checkbox"
          checked={includeQA}
          onChange={(e) => setIncludeQA(e.target.checked)}
        />
        include my question and the answer
      </label>
      <div className="feedback-box__row">
        <span className="feedback-box__hint">
          Sends only what you type{includeQA ? " + this Q&A" : ""}, plus app
          version &amp; OS. Never your files.
        </span>
        <div className="feedback-box__actions">
          <button
            type="button"
            className="feedback-box__cancel"
            onClick={() => setPhase("closed")}
          >
            cancel
          </button>
          <button
            type="button"
            className="feedback-box__send"
            disabled={phase === "sending" || !message.trim()}
            onClick={send}
          >
            {phase === "sending" ? "sending…" : "send"}
          </button>
        </div>
      </div>
    </div>
  );
}
