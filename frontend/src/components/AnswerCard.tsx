import { Highlighted } from "./Highlighted";

import "./AnswerCard.css";

interface Props {
  answer: string;
  highlights: string[];
  loading: boolean;
  error: string | null;
  onFollowUp: () => void;
}

export function AnswerCard({ answer, highlights, loading, error, onFollowUp }: Props) {
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
          <Highlighted text={answer} tokens={highlights} />
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
