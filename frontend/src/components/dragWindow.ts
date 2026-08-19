/**
 * Shared "grab to move the window" handler for the ask bar.
 *
 * Explicit drag: call startDragging() on mousedown anywhere that isn't
 * an interactive element. More reliable than `data-tauri-drag-region`
 * alone — the attribute only fires when the mousedown target IS the
 * attributed element (child spans swallow it), and on macOS it
 * sometimes fails to pick up events through the vibrancy blur layer.
 *
 * Used by QuestionCard (the bar itself) and MagpieWindow's root
 * (footer + every empty gap between cards), so the window can be
 * grabbed almost anywhere — Spotlight behavior — while text inside
 * answer/source/preview cards stays selectable.
 */

export const INTERACTIVE =
  "input, textarea, button, [role=button], [contenteditable], a, select";

/** Timestamp (ms) of the most recent startDragging() call. The ask
 *  bar hides itself on `tauri://blur` (Spotlight pattern) — but on
 *  Windows, entering the native window-move loop can fire a blur at
 *  the moment the drag starts, which made every drag attempt hide the
 *  window instead of moving it. The blur handler consults this to
 *  swallow that drag-induced blur. */
export const dragState = { lastDragStartAt: 0 };

export function startDragOnMouseDown(e: React.MouseEvent) {
  if (e.button !== 0) return;
  // Double-click on a drag region is the OS "title-bar double-click"
  // gesture (maximize/restore on Windows) — never start a drag from
  // it, and never let it reach the OS as a caption gesture.
  if (e.detail > 1) {
    e.preventDefault();
    return;
  }
  const target = e.target as HTMLElement;
  if (target.closest(INTERACTIVE)) return;
  dragState.lastDragStartAt = Date.now();
  import("@tauri-apps/api/window")
    .then(({ getCurrentWindow }) => getCurrentWindow().startDragging())
    .catch(() => {
      /* not under Tauri — ignore */
    });
}
