import { AnswerMarkdown } from "./citations";
import type { Source } from "../types";

import "./AnswerCard.css";

interface Props {
  answer: string;
  /** The CITED sources in `sources_used` order — `[N]` markers in the
   *  answer prose are 1-based indexes into this list (src/answer.py
   *  contract). Do NOT pass the full retrieval list here. The renderer
   *  falls back to plain-text spans for out-of-range markers (Plan #25). */
  sources: Source[];
  /** Tokens to highlight in non-citation text (currency, dates, etc.). */
  highlights: string[];
  loading: boolean;
  error: string | null;
  onFollowUp: () => void;
  /** Called when a citation pill or any source-anchored span is
   *  clicked. Parent uses this to update the selected source in the
   *  sources list / preview pane. */
  onSelectSource?: (path: string) => void;
}

export function AnswerCard({
  answer,
  sources,
  highlights,
  loading,
  error,
  onFollowUp,
  onSelectSource,
}: Props) {
  return (
    <div className="answer-card magpie-card">
      <div className="answer-card__label">ANSWER</div>
      <div className="answer-card__body">
        {error ? (
          <span className="answer-card__error">⚠ {error}</span>
        ) : loading ? (
          <span className="answer-card__loading">
            <span className="answer-card__dot" />
            <span className="answer-card__dot" />
            <span className="answer-card__dot" />
          </span>
        ) : (
          <AnswerMarkdown
            text={answer}
            sources={sources}
            highlightTokens={highlights}
            onSelectSource={onSelectSource}
          />
        )}
      </div>
      {!loading && !error && (
        <button className="answer-card__followup" onClick={onFollowUp} type="button">
          + follow up
        </button>
      )}
    </div>
  );
}
