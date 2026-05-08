import { forwardRef, useCallback, useEffect } from "react";
// Two transparent variants. Dark-mode is the default — the Magpie window
// renders with dark vibrancy (see styles/tokens.css `--bg-card`). The
// light-mode asset swaps in via the <picture> media query below if the
// user's system is in light mode (vibrancy lightens slightly there).
import magpieLogoDark from "../assets/magpie-logo-dark.png";
import magpieLogoLight from "../assets/magpie-logo-light.png";

import "./QuestionCard.css";

/**
 * Props as of PR 4 ([Specs/UI/ask_bar.md] universal-elements
 * rewrite). The settings gear has been lifted OUT of the search pill
 * and into the sibling SettingsBlob component, so QuestionCard is now
 * just logo + input/title + submit-affordance. The previous
 * `onOpenSettings` and `shortcutLabel` props are gone — the blob
 * handles both jobs (the keyboard hint moved to StatusFooter, since
 * the right-side hint there is more discoverable).
 */
interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  loading: boolean;
  booting: boolean;
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
  function QuestionCard(
    { value, onChange, onSubmit, loading, booting, submittedQuestion },
    ref
  ) {
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
        <picture>
          <source srcSet={magpieLogoLight} media="(prefers-color-scheme: light)" />
          <img
            src={magpieLogoDark}
            alt="Magpie"
            className={`question-card__logo ${value || isActive ? "is-active" : ""}`}
            data-tauri-drag-region
          />
        </picture>
        {isActive ? (
          <div className="question-card__title" data-tauri-drag-region>
            {display}
          </div>
        ) : (
          <input
            ref={ref}
            className="question-card__input"
            value={value}
            placeholder={booting ? "Starting Magpie…" : "Ask Magpie about your files…"}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSubmit();
              }
            }}
            disabled={loading || booting}
            spellCheck={false}
            autoComplete="off"
          />
        )}
        {/* Submit-affordance glyph on the right edge of the pill. Click
            equivalent to Enter; visually echoes "you can press return". */}
        <button
          type="button"
          className="question-card__submit"
          onClick={onSubmit}
          disabled={loading || booting || !value.trim()}
          aria-label="Ask"
          tabIndex={-1}
        >
          ⏎
        </button>
      </div>
    );
  }
);
