"""Disk cache for a llama-server slot's processed prompt prefix.

The answer step's user message starts with the retrieved files and ends with
the question. The file part is the same every time the same files come up,
so we process it once, save the server's state for it to disk, and restore
it the next time. Restoring a 2.7K-token prefix takes 20-60 ms; re-reading
it takes ~1 s on GPU and far longer on CPU (measured 2026-08-28, see
Evaluations/phyll/REPORT.md).

Slot files are ~16 KB per token for LFM2.5-VL-3B, so a 6K-token document is
~100 MB on disk. The cache is a plain LRU capped at MAGPIE_KV_CACHE_MB.
MAGPIE_KV_CACHE=0 turns the whole thing off.

The cap is a working-set limit: at ~100 MB a slot, 2 GB holds about twenty
distinct file sets. Cycling through more than that (the 25-question warm
eval arm of 2026-08-28) evicts each slot just before it is asked for again
and hits nothing — every question logged "saved", none "restored". That is
the LRU doing its job on a working set bigger than the cap, not a broken
restore; raise MAGPIE_KV_CACHE_MB for such runs. The product pattern this
is built for — several questions in a row about the same document — fits.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import httpx

from src.inference.llama_server_pool import kv_slot_dir

CACHE_CAP_MB = int(os.environ.get("MAGPIE_KV_CACHE_MB", "2048"))
ENABLED = os.environ.get("MAGPIE_KV_CACHE", "1").strip() != "0"
REQUEST_TIMEOUT_S = 300.0


def cache_key(model_id: str, system_prompt: str, prefix_text: str) -> str:
    h = hashlib.sha256()
    for part in (model_id, system_prompt, prefix_text):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:32] + ".bin"


def _slot_name(client: httpx.Client, base_url: str, model_id: str, system_prompt: str, prefix_text: str) -> str:
    # The key must name the weights actually loaded, not the profile label:
    # LLAMA_SERVER_MODEL_PATH swaps the GGUF without changing model_id, and a
    # slot computed by one quant restored into another with the same
    # tokenizer passes every count check and answers from garbage state.
    # /props reports the served file.
    model_file = model_id
    try:
        served = str(client.get(f"{base_url}/props").json().get("model_path") or "")
        if served:
            st = os.stat(served) if os.path.exists(served) else None
            model_file = f"{model_id}|{served}|{st.st_size if st else 0}|{int(st.st_mtime) if st else 0}"
    except Exception:  # noqa: BLE001 — older servers; fall back to the label
        pass
    return cache_key(model_file, system_prompt, prefix_text)


def slot_exists(base_url: str, model_id: str, system_prompt: str, prefix_text: str) -> bool:
    """True when a saved slot for this exact prefix is on disk. The answer
    step asks this BEFORE building the prompt: with a slot it leads with the
    files (so the slot can be restored), without one it leads with the
    question (the small model reads better when it knows what it is looking
    for) and builds the slot afterwards for next time."""
    if not ENABLED or not prefix_text:
        return False
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_S) as client:
            return (kv_slot_dir() / _slot_name(client, base_url, model_id, system_prompt, prefix_text)).is_file()
    except Exception:  # noqa: BLE001
        return False


def build_in_background(base_url: str, model_id: str, system_prompt: str, prefix_text: str) -> None:
    """Prefill + save the prefix on a daemon thread once an answer is out.
    The server is idle right after an answer; a question that arrives in the
    meantime queues behind ~1-3 s of prefill, and the slot is there for the
    next question about the same files."""
    if not ENABLED or not prefix_text:
        return
    import threading

    def _build() -> None:
        # The server has one slot and the next question's calls share it, so
        # a build can lose the race between its prefill and its save (the
        # token-count check then rejects the save — correct, but the slot is
        # not built). Questions arrive seconds apart in real use and the
        # first retry wins; in a back-to-back eval it took a few.
        import time

        status = "failed"
        for _attempt in range(5):
            status = ensure_prefix(base_url, model_id, system_prompt, prefix_text)
            if status != "failed":
                break
            time.sleep(1.0)
        print(f"  kv-cache: background build {status}", file=sys.stderr)

    threading.Thread(target=_build, daemon=True, name="kv-prefix-build").start()


def ensure_prefix(base_url: str, model_id: str, system_prompt: str, prefix_text: str) -> str:
    """Leave the server's slot holding the processed prefix, restoring it
    from disk when we have it and building + saving it when we don't.
    Returns a one-word status for the query trace."""
    if not ENABLED or not prefix_text:
        return "off"
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_S) as client:
            name = _slot_name(client, base_url, model_id, system_prompt, prefix_text)
            path = kv_slot_dir() / name
            # Render exactly what the chat endpoint will see for this prefix,
            # then cut at the end of our text so the saved state stops on the
            # boundary the real prompt continues from. Anything the template
            # appends after the user turn must not be in the saved state.
            # Same template kwargs the chat request sends (local_llm.py
            # _build_request_body): a template that branches on them would
            # otherwise render a different prefix from the one it later sees.
            r = client.post(
                f"{base_url}/apply-template",
                json={
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prefix_text},
                    ],
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            r.raise_for_status()
            rendered = r.json()["prompt"]
            cut = rendered.rfind(prefix_text)
            if cut < 0:
                print("  kv-cache: the chat template altered the prefix text; cannot cache it",
                      file=sys.stderr)
                return "failed"
            exact = rendered[: cut + len(prefix_text)]

            # How many tokens the slot must hold afterwards. The server has
            # one slot and the walker's summaries queue on it too, so a save
            # or restore can land on somebody else's prompt; the token count
            # is the cheap check that it did not. (+/-2: the raw prefill may
            # add one generated token.)
            r = client.post(f"{base_url}/tokenize", json={"content": exact})
            r.raise_for_status()
            expected = len(r.json().get("tokens", []))

            if path.is_file():
                r = client.post(f"{base_url}/slots/0?action=restore", json={"filename": name})
                if r.status_code == 200 and abs(int(r.json().get("n_restored", -9)) - expected) <= 2:
                    os.utime(path, None)  # LRU touch
                    return "restored"
                print("  kv-cache: slot on disk does not match this prefix; rebuilding",
                      file=sys.stderr)
                path.unlink(missing_ok=True)

            r = client.post(
                f"{base_url}/completion",
                json={"prompt": exact, "n_predict": 0, "cache_prompt": True, "temperature": 0},
            )
            r.raise_for_status()
            r = client.post(f"{base_url}/slots/0?action=save", json={"filename": name})
            r.raise_for_status()
            if abs(int(r.json().get("n_saved", -9)) - expected) <= 2:
                _evict_over_cap()
                return "saved"
            # another request took the slot between prefill and save
            path.unlink(missing_ok=True)
            return "failed"
    except Exception as e:  # noqa: BLE001 — the cache is a speedup, never a failure
        print(f"  kv-cache: skipped ({type(e).__name__}: {e})", file=sys.stderr)
        return "failed"


def _evict_over_cap() -> None:
    files = sorted(kv_slot_dir().glob("*.bin"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    cap = CACHE_CAP_MB * 1024 * 1024
    dropped = 0
    for p in files:
        if total <= cap:
            break
        total -= p.stat().st_size
        p.unlink(missing_ok=True)
        dropped += 1
    if dropped:
        # visible in the query trace, so a run that never restores can be
        # told apart from one whose slots were pushed out before reuse
        print(f"  kv-cache: evicted {dropped} slot(s) to stay under {CACHE_CAP_MB} MB",
              file=sys.stderr)


def cache_stats() -> dict:
    files = list(kv_slot_dir().glob("*.bin"))
    return {"files": len(files), "mb": round(sum(p.stat().st_size for p in files) / 1e6, 1)}
