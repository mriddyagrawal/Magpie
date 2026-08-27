"""In-app feedback: the post-answer "Feedback" box.

`POST /feedback` (see src/server.py) hands the user's typed message to
`submit()`, which forwards it to the team's webhook. The webhook URL
comes from, in order:

  1. `FEEDBACK_WEBHOOK_URL` env var — dev/testing override.
  2. `src/config/bundled_webhook.txt` — baked in at build time by the
     CI "Seed bundled secrets" step, exactly like the OpenRouter key in
     `bundled_key.txt`. Dev checkouts don't have it (gitignored), so
     dev builds without the env var report "not configured".

Payload shape is detected from the URL: Discord webhooks want
`{"content": ...}` (2000-char cap), Slack wants `{"text": ...}`,
anything else gets `{"message": ...}` raw JSON — so whichever webhook
the team pastes into the GitHub secret Just Works.

Store-and-forward: if delivery fails (offline, webhook down), the
formatted message is appended to `feedback_outbox.jsonl` under
APP_DATA_DIR and retried on the next submit and on sidecar startup —
feedback typed on a plane still arrives eventually.

Privacy contract (this is a local-first app; keep it honest): nothing
is ever sent except from the user's explicit Submit click. The payload
is the typed text plus coarse build metadata (app version, OS,
provider name) — and the question/answer pair ONLY when the user
ticked the include-context box. No file contents, no paths, no index
data.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
from pathlib import Path

# Discord rejects `content` over 2000 chars; leave headroom for safety.
_DISCORD_CONTENT_CAP = 1990
# Server-side cap on the typed message itself (UI enforces the same).
MESSAGE_CAP = 4000
# Q/A context is a courtesy attachment, not a transcript dump.
_CONTEXT_CAP = 700

_outbox_lock = threading.Lock()


def _bundled_webhook() -> str:
    """Read the build-time-baked webhook URL from
    `src/config/bundled_webhook.txt` if present, empty otherwise.

    Mirrors `src/config/secrets.py:_bundled_key()` — one ASCII line,
    utf-8-sig so a BOM can't silently poison the URL."""
    p = Path(__file__).resolve().parent / "config" / "bundled_webhook.txt"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


def _webhook_url() -> str:
    return os.environ.get("FEEDBACK_WEBHOOK_URL", "").strip() or _bundled_webhook()


def webhook_configured() -> bool:
    return bool(_webhook_url())


def _outbox_path() -> Path:
    from src.manifest import APP_DATA_DIR

    return Path(APP_DATA_DIR) / "feedback_outbox.jsonl"


def _app_version() -> str:
    try:
        from importlib.metadata import version

        return version("magpie")
    except Exception:  # noqa: BLE001 — metadata is best-effort in frozen builds
        return os.environ.get("MAGPIE_VERSION", "unknown")


def _provider_name() -> str:
    try:
        from src.llm import active_provider

        return active_provider().name
    except Exception:  # noqa: BLE001 — feedback must never depend on LLM state
        return "unknown"


def _format_text(message: str, context: dict | None) -> str:
    """The human-readable message that lands in the team channel."""
    meta = (
        f"Magpie v{_app_version()} · {platform.system()} {platform.release()}"
        f" · provider: {_provider_name()}"
    )
    parts = ["**Magpie feedback**", message.strip(), "", f"_{meta}_"]
    if context:
        q = str(context.get("question", ""))[:_CONTEXT_CAP]
        a = str(context.get("answer", ""))[:_CONTEXT_CAP]
        if q or a:
            parts.append(f"> Q: {q}")
            parts.append(f"> A: {a}")
    return "\n".join(parts)


def _shape_payload(url: str, text: str) -> dict:
    """Match the payload to the webhook family the URL belongs to."""
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        return {"content": text[:_DISCORD_CONTENT_CAP]}
    if "hooks.slack.com" in url:
        return {"text": text}
    return {"message": text}


def _deliver(text: str) -> bool:
    """One delivery attempt. True on 2xx. Never raises."""
    url = _webhook_url()
    if not url:
        return False
    try:
        import httpx

        r = httpx.post(url, json=_shape_payload(url, text), timeout=10.0)
        return 200 <= r.status_code < 300
    except Exception:  # noqa: BLE001 — offline/DNS/timeout all mean "queue it"
        return False


def _queue(text: str) -> None:
    """Append to the on-disk outbox. Never raises — worst case the
    feedback is lost, which must not take the endpoint down with it."""
    try:
        entry = json.dumps({"ts": time.time(), "text": text})
        with _outbox_lock:
            p = _outbox_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(entry + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"[feedback] could not queue to outbox: {e}", file=sys.stderr)


def flush_outbox() -> int:
    """Retry every queued entry; keep the ones that still fail.
    Returns how many were delivered. Safe to call any time."""
    if not webhook_configured():
        return 0
    with _outbox_lock:
        p = _outbox_path()
        if not p.exists():
            return 0
        try:
            lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except OSError:
            return 0
        kept: list[str] = []
        sent = 0
        for ln in lines:
            try:
                entry = json.loads(ln)
                text = entry["text"]
            except Exception:  # noqa: BLE001 — a corrupt line is dropped, not fatal
                continue
            if _deliver(text):
                sent += 1
            else:
                kept.append(ln)
        try:
            if kept:
                p.write_text("\n".join(kept) + "\n", encoding="utf-8")
            else:
                p.unlink()
        except OSError as e:
            print(f"[feedback] could not rewrite outbox: {e}", file=sys.stderr)
        return sent


def submit(message: str, context: dict | None = None) -> dict:
    """Format, deliver, and (on failure) queue one feedback message.

    Returns {"delivered": bool, "queued": bool} for the UI: delivered
    → "Thanks!", queued → "Saved — will send when you're back online."
    """
    text = _format_text(message[:MESSAGE_CAP], context)
    # Older queued feedback rides along with any fresh submit.
    flush_outbox()
    if _deliver(text):
        return {"delivered": True, "queued": False}
    _queue(text)
    return {"delivered": False, "queued": True}
