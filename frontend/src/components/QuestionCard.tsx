import { forwardRef, useCallback, useEffect } from "react";
import magpieLogo from "../assets/magpie-logo.png";

import "./QuestionCard.css";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  loading: boolean;
  submittedQuestion: string | null;
}

// Explicit drag: call startDragging() on mousedown anywhere on the card that
// isn't an interactive element. More reliable than data-tauri-drag-region
// alone when the window has backdrop-filter / vibrancy — on macOS the
// attribute sometimes fails to pick up events through the blur layer.
const INTERACTIVE = "input, textarea, button, [role=button], [contenteditable]";
function startDragOnMouseDown(e: React.MouseEvent) {
  if (e.button !== 0) return;
  const target = e.target as HTMLElement;
  if (target.closest(INTERACTIVE)) return;
  import("@tauri-apps/api/window")
    .then(({ getCurrentWindow }) => getCurrentWindow().startDragging())
    .catch(() => {
      /* not under Tauri — ignore */
    });
}

export const QuestionCard = forwardRef<HTMLInputElement, Props>(
  function QuestionCard({ value, onChange, onSubmit, loading, submittedQuestion }, ref) {
    useEffect(() => {
      if (typeof ref === "object" && ref?.current) ref.current.focus();
    }, [ref]);

    const onMouseDown = useCallback(startDragOnMouseDown, []);
    const display = submittedQuestion ?? value;
    const isActive = submittedQuestion !== null;

    return (
      <div
        className={`question-card magpie-card ${isActive ? "is-active" : ""}`}
        data-tauri-drag-region
        onMouseDown={onMouseDown}
      >
        <img
          src={magpieLogo}
          alt="Magpie"
          className={`question-card__logo ${value || isActive ? "is-active" : ""}`}
          data-tauri-drag-region
        />
        {isActive ? (
          <div className="question-card__title" data-tauri-drag-region>
            {display}
          </div>
        ) : (
          <input
            ref={ref}
            className="question-card__input"
            value={value}
            placeholder="Ask magpie"
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSubmit();
              }
            }}
            disabled={loading}
            spellCheck={false}
            autoComplete="off"
          />
        )}
        <kbd className="question-card__hint" data-tauri-drag-region>
          ⌥ Space
        </kbd>
      </div>
    );
  }
);
