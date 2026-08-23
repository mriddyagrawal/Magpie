/**
 * ErrorCard — what the ask bar shows when the query failed, as opposed
 * to succeeding with nothing to report.
 *
 * This card exists because the two used to be the same thing. Every
 * backend failure — a crashed reranker, an OpenRouter 429, a dropped
 * connection — was funnelled into `kind: "not_found"` with a synthetic
 * result carrying `sources_scanned_count: 0`, so the user read
 * "Magpie hasn't read any folders that look like they'd contain X"
 * when the truth was "the query never ran." That copy sends people off
 * to re-index a corpus that was fine, and it hid a broken reranker for
 * an entire session.
 *
 * The server already does the hard part: `_user_facing_error` in
 * src/server.py maps the exception to a short, jargon-free line
 * ("Service is busy right now. Try again in a few seconds.") and keeps
 * the stack trace in stderr. All this card has to do is stop throwing
 * that line away.
 *
 * Retry is the only affordance. Unlike NotFoundCard's "add a folder"
 * CTA, there is nothing for the user to configure here — the failures
 * this card reports are transient or ours to fix.
 */

import { AlertCircle, RotateCw } from "lucide-react";

interface Props {
  /** User-safe message from the server's `error` SSE frame. Already
   *  sanitized server-side — no model names, no provider names, no
   *  stack traces. Falls back to a generic line when the stream died
   *  before sending one (network drop, sidecar gone). */
  detail: string;
  /** Re-run the question that failed. */
  onRetry: () => void;
}

export function ErrorCard({ detail, onRetry }: Props) {
  return (
    <section className="error-card magpie-card" aria-live="assertive">
      <header className="error-card__header">
        <span className="error-card__icon" aria-hidden="true">
          <AlertCircle size={15} />
        </span>
        <h2 className="error-card__title">Couldn't finish that search</h2>
      </header>
      <p className="error-card__body">{detail}</p>
      <button type="button" className="error-card__cta" onClick={onRetry}>
        <span className="error-card__cta-icon" aria-hidden="true">
          <RotateCw size={16} />
        </span>
        <span>Try again</span>
      </button>
    </section>
  );
}
