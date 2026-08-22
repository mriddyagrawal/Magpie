/**
 * ConfirmModal — reusable destructive-action confirmation. Used by
 * the Reindex button (typed-RESET pattern, per the spec) and by
 * Remove folder (single-button confirm, simpler copy).
 *
 * For typed confirmation: pass `requireWord` (e.g., "RESET") and the
 * confirm button is disabled until the user types it exactly. For
 * plain confirms, omit `requireWord`.
 */

import { useEffect, useRef, useState } from "react";

interface Props {
  open: boolean;
  title: string;
  body: React.ReactNode;
  /** When set, the confirm button is disabled until the user types
   *  this exact word into a verification input. Used for high-risk
   *  actions like Reindex. */
  requireWord?: string;
  confirmLabel?: string;
  confirmTone?: "danger" | "neutral";
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({
  open,
  title,
  body,
  requireWord,
  confirmLabel = "Confirm",
  confirmTone = "danger",
  onConfirm,
  onCancel,
}: Props) {
  const [typed, setTyped] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset typed state when the modal opens. Without this, a previous
  // confirmation's input value would persist into the next show.
  useEffect(() => {
    if (open) {
      setTyped("");
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Esc cancels. Captured at the document level so it works even if
  // focus is on the typed-confirmation input.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  const verified = !requireWord || typed === requireWord;

  return (
    <div className="confirm-modal-overlay" role="dialog" aria-modal="true">
      <div className="confirm-modal">
        <h2 className="confirm-modal__title">{title}</h2>
        <div className="confirm-modal__body">{body}</div>
        {requireWord && (
          <label className="confirm-modal__verify">
            <span className="confirm-modal__verify-label">
              Type <code>{requireWord}</code> to continue:
            </span>
            <input
              ref={inputRef}
              className="confirm-modal__verify-input"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              spellCheck={false}
              autoComplete="off"
            />
          </label>
        )}
        <div className="confirm-modal__actions">
          <button
            type="button"
            className="confirm-modal__btn confirm-modal__btn--cancel"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className={`confirm-modal__btn confirm-modal__btn--${confirmTone}`}
            onClick={() => verified && onConfirm()}
            disabled={!verified}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
