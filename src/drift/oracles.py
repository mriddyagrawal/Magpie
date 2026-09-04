"""Executable checks for every assumption Magpie mirrors about upstream.

Each oracle asks the REAL component (a running llama-server, the live
Qdrant) whether the behaviour our code assumes still holds:

  image_tokens        answer.estimate_image_tokens mirrors llama.cpp's
                      LFM2 tiling math - measure a few synthetic sizes and
                      require estimate >= measured (an under-estimate is
                      the HTTP-400 failure)
  grammar             llama-server's sampler enforces the GBNF grammar
                      LocalLLM sends (compiled from the output schema by
                      src/inference/gbnf.py) - the load-bearing constraint
                      behind every answer/summary/rewrite; a build that
                      ignores it returns prose that only the repair path
                      can salvage
  context_window      the server's PER-SLOT window (/props n_ctx, i.e.
                      -c divided by -np) covers the ctx_size the answer
                      budget is sized from - raising parallelism without
                      raising -c would 400 every multi-file answer
  vector_dims         the stored Qdrant collections' vector widths match
                      the encoders we would write with

Results are cached per provenance fingerprint under
<APP_DATA_DIR>/drift/oracles-<fp>.json, so the checks run once per new
(binary, model, lockfile) combination: on demand via `just check-drift` /
POST /drift/check, or automatically the first time the vision server sits
idle after a new fingerprint appears (see `schedule_after_idle`). They are
never run in the path of a user's query.
"""

from __future__ import annotations

import base64
import json
import struct
import sys
import threading
import time
import urllib.request
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from src.drift.provenance import DRIFT_DIR

# Sizes chosen to hit the tiling branches the first-cut estimator got wrong
# (4:3, square) plus the untiled branch and a 9:16 screenshot. Small on
# purpose: ~10 s against a warm server.
IMAGE_ORACLE_SIZES: tuple[tuple[int, int], ...] = ((800, 600), (1024, 768), (1200, 1200), (1080, 1920))
_REQUEST_TIMEOUT_S = 180


@dataclass
class OracleResult:
    name: str
    ok: bool
    detail: str
    data: dict = field(default_factory=dict)


# ---- helpers ----------------------------------------------------------------


def synthetic_png(w: int, h: int) -> bytes:
    """A valid RGB PNG of the given size, stdlib only. Content is irrelevant
    to token counting; the pattern keeps the file small."""
    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))
    row = bytes([0]) + bytes((x * 7 + 13) & 0xFF for x in range(w * 3))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * h, 1))
            + chunk(b"IEND", b""))


def _chat(base_url: str, body: dict) -> dict:
    req = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_S) as r:
        return json.load(r)


def _prompt_tokens(base_url: str, content: list) -> int:
    data = _chat(base_url, {"messages": [{"role": "user", "content": content}],
                            "max_tokens": 1, "temperature": 0})
    return int(data["usage"]["prompt_tokens"])


# ---- oracles ----------------------------------------------------------------


def oracle_image_tokens(base_url: str) -> OracleResult:
    from src.answer import estimate_image_tokens

    try:
        text = "Describe."
        base = _prompt_tokens(base_url, [{"type": "text", "text": text}])
        rows = []
        under = []
        for w, h in IMAGE_ORACLE_SIZES:
            b64 = base64.b64encode(synthetic_png(w, h)).decode()
            measured = _prompt_tokens(base_url, [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]) - base
            est = estimate_image_tokens(w, h)
            rows.append({"size": f"{w}x{h}", "measured": measured, "estimate": est,
                         "ratio": round(est / measured, 3) if measured else None})
            if est < measured:
                under.append(f"{w}x{h}: estimate {est} < measured {measured}")
        if under:
            return OracleResult("image_tokens", False,
                                "estimator UNDER-counts (would become HTTP 400s): " + "; ".join(under),
                                {"rows": rows})
        worst = max((r["ratio"] or 0) for r in rows)
        note = " (over-estimating >20% - budget is wasteful, not unsafe)" if worst > 1.2 else ""
        return OracleResult("image_tokens", True,
                            f"estimate >= measured on {len(rows)} sizes, max ratio {worst:.2f}{note}",
                            {"rows": rows})
    except Exception as e:  # noqa: BLE001
        return OracleResult("image_tokens", False, f"probe failed: {e}", {})


_GRAMMAR_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "ok": {"type": "boolean"}},
    "required": ["answer", "ok"],
    "additionalProperties": False,
}


def grammar_probe_body() -> dict:
    """The exact constraint shape LocalLLM sends: a GBNF grammar compiled by
    src/inference/gbnf.py and NOTHING else. The product deliberately omits
    `response_format` when a grammar is present (local_llm._build_request_body:
    "sending both risks a double constraint") - and the first cut of this
    probe proved that comment right by sending both and getting a reply
    truncated mid-string on a build the product works on."""
    from src.inference.gbnf import schema_to_gbnf

    return {
        "messages": [{"role": "user", "content":
                      "Write two sentences about the sea. Do not use JSON."}],
        "max_tokens": 120, "temperature": 0,
        "grammar": schema_to_gbnf(_GRAMMAR_SCHEMA),
    }


def oracle_grammar(base_url: str) -> OracleResult:
    """Ask for prose while constraining to a schema, the way the product
    does. If the sampler enforces the grammar the reply is a JSON object
    with exactly these keys; prose back means structured output is unsafe."""
    content = ""
    finish = None
    try:
        data = _chat(base_url, grammar_probe_body())
        choice = data["choices"][0]
        content = choice["message"]["content"]
        finish = choice.get("finish_reason")
        obj = json.loads(content)
        if set(obj) == {"answer", "ok"} and isinstance(obj["ok"], bool):
            return OracleResult("grammar", True, "GBNF grammar enforced by the sampler",
                                {"sample": content[:120], "finish_reason": finish})
        return OracleResult("grammar", False,
                            f"JSON parsed but keys/types differ from schema: {sorted(obj)}",
                            {"sample": content[:200], "finish_reason": finish})
    except json.JSONDecodeError:
        why = ("reply was cut off (finish_reason=length) - grammar held but the "
               "budget did not" if finish == "length" else
               "server IGNORED the grammar - reply was not JSON; structured output "
               "(every answer/summary/rewrite) is unsafe on this build")
        return OracleResult("grammar", False, why,
                            {"sample": content[:200], "finish_reason": finish})
    except Exception as e:  # noqa: BLE001
        return OracleResult("grammar", False, f"probe failed: {e}", {})


def oracle_vector_dims(client: Any = None) -> OracleResult:
    """Stored collection widths vs the encoders we write with."""
    try:
        from src.stage2.db import COLLECTION_NAME, get_qdrant_client, qdrant_reachable
        from src.stage2.embeddings import DENSE_VECTOR_SIZE
        from src.stage2.fast_db import FAST_COLLECTION_NAME, FAST_VECTOR_DIM

        if client is None:
            # A Qdrant that is not running is a normal state (the app is
            # down, or this is the CLI) - not drift. Report skipped, not failed.
            ok, why = qdrant_reachable(timeout_s=2.0)
            if not ok:
                return OracleResult("vector_dims", True,
                                    f"skipped: Qdrant not reachable ({why})", {"skipped": True})
            client = get_qdrant_client()
        checks: dict[str, Any] = {}
        problems = []

        def width(collection: str, name: Optional[str]) -> Optional[int]:
            if not client.collection_exists(collection):
                return None
            vectors = client.get_collection(collection).config.params.vectors
            cfg = vectors.get(name) if isinstance(vectors, dict) and name else vectors
            size = getattr(cfg, "size", None)
            return size if isinstance(size, int) else None

        dense = width(COLLECTION_NAME, "dense")
        checks["dense"] = {"stored": dense, "expected": DENSE_VECTOR_SIZE}
        if dense is not None and dense != DENSE_VECTOR_SIZE:
            problems.append(f"{COLLECTION_NAME}.dense stored {dense}, encoder writes {DENSE_VECTOR_SIZE}")
        fast = width(FAST_COLLECTION_NAME, None)
        checks["fast"] = {"stored": fast, "expected": FAST_VECTOR_DIM}
        if fast is not None and fast != FAST_VECTOR_DIM:
            problems.append(f"{FAST_COLLECTION_NAME} stored {fast}, encoder writes {FAST_VECTOR_DIM}")
        if problems:
            return OracleResult("vector_dims", False, "; ".join(problems), checks)
        absent = [k for k, v in checks.items() if v["stored"] is None]
        note = f" ({', '.join(absent)} collection not created yet)" if absent else ""
        return OracleResult("vector_dims", True, f"stored widths match encoders{note}", checks)
    except Exception as e:  # noqa: BLE001
        return OracleResult("vector_dims", False, f"probe failed: {e}", {})


def oracle_context_window(base_url: str) -> OracleResult:
    """The context budget (answer.py) is sized from profile.args.ctx_size,
    but the server's real PER-SLOT window is n_ctx / n_parallel. The pool
    passes -np 1 today and invites GPU boxes to raise it via extra_args -
    the moment someone does, every multi-file answer 400s again and nothing
    else notices. /props reports the per-slot window
    (default_generation_settings.n_ctx) and total_slots; assert the slot
    window covers what the budget assumes."""
    try:
        from src.inference.profiles import default_text_profile, get_profile

        assumed = int(get_profile(default_text_profile()).args.ctx_size)
        with urllib.request.urlopen(base_url.rstrip("/") + "/props", timeout=30) as r:
            props = json.load(r)
        slot_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
        slots = props.get("total_slots")
        data = {"slot_n_ctx": slot_ctx, "total_slots": slots, "budget_ctx_size": assumed}
        if not isinstance(slot_ctx, int):
            return OracleResult("context_window", False,
                                "/props carries no default_generation_settings.n_ctx - "
                                "cannot verify the per-slot window", data)
        if slot_ctx < assumed:
            return OracleResult("context_window", False,
                                f"per-slot window {slot_ctx} < budget assumption {assumed} "
                                f"({slots} slot(s)) - multi-file answers will 400; lower the "
                                f"profile ctx_size or raise -c / lower -np", data)
        return OracleResult("context_window", True,
                            f"per-slot window {slot_ctx} >= budget assumption {assumed} "
                            f"({slots} slot(s))", data)
    except Exception as e:  # noqa: BLE001
        return OracleResult("context_window", False, f"probe failed: {e}", {})


def run_all(base_url: Optional[str], client: Any = None) -> list[OracleResult]:
    """Run every oracle. `base_url` None skips the llama-server ones (they
    report as not-run rather than failed)."""
    out: list[OracleResult] = []
    if base_url:
        out.append(oracle_context_window(base_url))
        out.append(oracle_image_tokens(base_url))
        out.append(oracle_grammar(base_url))
    else:
        out.append(OracleResult("context_window", True, "skipped: no llama-server available", {"skipped": True}))
        out.append(OracleResult("image_tokens", True, "skipped: no llama-server available", {"skipped": True}))
        out.append(OracleResult("grammar", True, "skipped: no llama-server available", {"skipped": True}))
    out.append(oracle_vector_dims(client))
    return out


# ---- cache ------------------------------------------------------------------


def cache_path(fingerprint: str) -> "Path":  # noqa: F821 - Path imported lazily below
    from pathlib import Path

    return Path(DRIFT_DIR) / f"oracles-{fingerprint}.json"


def load_cached(fingerprint: str) -> Optional[dict]:
    try:
        return json.loads(cache_path(fingerprint).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def save(fingerprint: str, results: list[OracleResult]) -> dict:
    record = {
        "fingerprint": fingerprint,
        "ran_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": all(r.ok for r in results),
        "results": [asdict(r) for r in results],
    }
    try:
        DRIFT_DIR.mkdir(parents=True, exist_ok=True)
        p = cache_path(fingerprint)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass
    return record


_run_lock = threading.Lock()


def ensure_for_fingerprint(fingerprint: str, base_url: Optional[str], *, force: bool = False) -> dict:
    """Return cached results for this fingerprint, running the oracles when
    none exist (or `force`). Serialized: two callers racing for the same
    fingerprint (the CLI and the idle hook, say) run the probes once."""
    with _run_lock:
        if not force:
            cached = load_cached(fingerprint)
            if cached is not None:
                return cached
        return save(fingerprint, run_all(base_url))


# ---- idle auto-run ----------------------------------------------------------

_scheduled: set[str] = set()


def claim(fingerprint: str) -> None:
    """Mark a fingerprint as being handled by the caller (the CLI, a
    /drift/check run) so the pool's on-spawn hook does not schedule a
    second, concurrent probe run for it."""
    _scheduled.add(fingerprint)


def schedule_after_idle(
    fingerprint: str,
    profile_name: str,
    base_url: str,
    idle_seconds: Callable[[str], Optional[float]],
    *,
    min_idle_s: float = 20.0,
    max_wait_s: float = 900.0,
) -> bool:
    """Run the oracles once, in a daemon thread, the first time the given
    llama-server has been idle for `min_idle_s` - never while a user is
    waiting on it. `idle_seconds(profile)` returns seconds since the server
    last served a request, or None once it is gone. Returns True when a run
    was scheduled, False when this fingerprint already has results."""
    if load_cached(fingerprint) is not None or fingerprint in _scheduled:
        return False
    _scheduled.add(fingerprint)

    def _worker() -> None:
        deadline = time.monotonic() + max_wait_s
        while time.monotonic() < deadline:
            idle = idle_seconds(profile_name)
            if idle is None:
                _scheduled.discard(fingerprint)
                return  # server evicted; the next spawn reschedules
            if idle >= min_idle_s:
                break
            time.sleep(2.0)
        else:
            _scheduled.discard(fingerprint)
            return
        try:
            rec = ensure_for_fingerprint(fingerprint, base_url)
            status = "OK" if rec.get("ok") else "FAILED"
            print(f"  drift: oracles {status} for fingerprint {fingerprint} "
                  f"({', '.join(r['name'] + ('✓' if r['ok'] else '✗') for r in rec['results'])})",
                  file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"  drift: oracle run failed: {e}", file=sys.stderr)

    threading.Thread(target=_worker, name="drift-oracles", daemon=True).start()
    return True


def on_server_ready(
    profile_name: str,
    base_url: str,
    idle_seconds: Callable[[str], Optional[float]],
) -> None:
    """Pool hook: called (under the pool lock) right after a llama-server
    passes its health check. Only the vision profile carries the mirrored
    assumptions, and computing the fingerprint may hash model files on a
    fresh install, so everything happens on a daemon thread - this returns
    immediately."""
    try:
        from src.inference.profiles import default_vision_profile

        if profile_name != default_vision_profile():
            return
    except Exception:  # noqa: BLE001
        return

    def _kick() -> None:
        try:
            from src.drift.provenance import runtime_fingerprint

            fp = runtime_fingerprint()["fingerprint"]
            schedule_after_idle(fp, profile_name, base_url, idle_seconds)
        except Exception as e:  # noqa: BLE001
            print(f"  drift: could not schedule oracles: {e}", file=sys.stderr)

    threading.Thread(target=_kick, name="drift-fingerprint", daemon=True).start()
