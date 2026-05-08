import { forwardRef, useCallback, useEffect } from "react";
// Two transparent variants. The asset filenames describe the FILE COLOR
// (a "dark" file is a dark-colored logo); rendering rules for which one
// to show ARE INVERTED from the file name:
//
//   - DARK MODE (default vibrancy) → show the LIGHT-colored asset
//     (`magpie-logo-light.png`) so the logo is visible on the dark bg.
//   - LIGHT MODE → show the DARK-colored asset (`magpie-logo-dark.png`)
//     so the logo is visible on the light bg.
//
// An earlier build had this backwards (rendering dark-on-dark and
// light-on-light, both invisible). Per the user's report (PR 5).
import magpieLogoDark from "../assets/magpie-logo-dark.png";   // dark-colored — for light bg
import magpieLogoLight from "../assets/magpie-logo-light.png"; // light-colored — for dark bg

import "./QuestionCard.css";

/**
 * Props as of PR 4 ([Specs/UI/ask_bar.md] universal-elements
 * rewrite, refined post-smoke). The component is now a single
 * always-rendered <input>. The earlier "submitted question becomes
 * a read-only button" pattern was dropped because it broke the
 * Spotlight selection flow the user wanted: in answering / not_found
 * state, the input shows the submitted question as its value, the
 * focus handler in MagpieWindow selects it on re-summon, and any
 * keystroke replaces it natively (transitioning to typing state via
 * onChange). This also kills a class of view-state-manipulation
 * keydown handlers that were intercepting events in non-input states.
 */
interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  loading: boolean;
  booting: boolean;
  /** True when the bar is showing a result (answering / not_found /
   *  retrieving). Drives a subtle styling change so the user can
   *  distinguish "this is a fresh question" from "this is what I
   *  just asked"; the input remains fully editable either way. */
  isActive: boolean;
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
    { value, onChange, onSubmit, loading, booting, isActive },
    ref
  ) {
    useEffect(() => {
      if (typeof ref === "object" && ref?.current) ref.current.focus();
    }, [ref]);

    const onMouseDown = useCallback(startDragOnMouseDown, []);

    return (
      <div
        className={`question-card magpie-card ${isActive ? "is-active" : ""}`}
        data-tauri-drag-region
        onMouseDown={onMouseDown}
      >
        <picture>
          {/* Light mode → use the DARK-colored asset (visible on light bg). */}
          <source srcSet={magpieLogoDark} media="(prefers-color-scheme: light)" />
          {/* Default (dark mode) → use the LIGHT-colored asset (visible on dark bg). */}
          <img
            src={magpieLogoLight}
            alt="Magpie"
            className={`question-card__logo ${value || isActive ? "is-active" : ""}`}
            data-tauri-drag-region
          />
        </picture>
        <input
          ref={ref}
          className={`question-card__input ${isActive ? "question-card__input--active" : ""}`}
          value={value}
          placeholder={booting ? "Starting Magpie…" : "Ask Magpie about your files…"}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
            }
          }}
          // Only block typing while the sidecar is still booting. NOT
          // disabled during retrieving — the user should be able to
          // edit / re-ask mid-pipeline. The gen-counter race guard
          // in MagpieWindow's submitQuestion discards the old
          // response when the new question fires, so editing during
          // retrieving is safe.
          disabled={booting}
          spellCheck={false}
          autoComplete="off"
        />
        {/* Submit-affordance glyph on the right edge of the pill. Click
            equivalent to Enter; visually echoes "you can press return".
            Stays disabled while loading so an enter-mash doesn't fire
            a second /query before the user has changed the input —
            but the input stays editable so they CAN change it. */}
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
