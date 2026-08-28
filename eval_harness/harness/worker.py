"""Eval worker: the only process that imports `src.*`.

Spawned by backend.run_worker with a from-scratch environment (envctl), so by
the time Python starts here, MAGPIE_DATA_DIR / the four cache vars /
HF_HUB_OFFLINE / QDRANT_CLUSTER_ENDPOINT / MAGPIE_FORCE_PROVIDER are already
process env — satisfying the src/manifest.py setdefault contract by
construction, with no import-order footguns.

Phases:
  boot    import the backend, report every resolved path/knob (Phase 0 proof)
  index   write scratch settings/rules, run sync_files, emit index report rows
  answer  loop golden questions through pipeline.ask(), flush per-question

stdout/stderr go to a per-phase log (the backend prints rich [query] traces
to stderr — kept verbatim as evidence and mined later for stage timings).
The structured result is written to --result as JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import envctl  # noqa: E402  (sibling module; no src.* import happens here)

_ENV_PREFIXES = (
    "MAGPIE_", "LOCAL_", "LLAMA_", "LLM_", "HF_", "QDRANT_",
    "OPENROUTER_", "MOONSHOT_", "REWRITE", "TRANSFORMERS_", "FASTEMBED_",
)


def _resolved_env_snapshot() -> dict[str, str]:
    """The env as the backend actually sees it, AFTER src import ran
    load_dotenv (manifest.py:63, override=False). Everything envctl set
    explicitly won; anything the repo .env contributed for UNSET vars shows
    up here — recorded evidence instead of invisible state. Secrets redacted."""
    import os
    relevant = {
        k: v for k, v in os.environ.items() if k.startswith(_ENV_PREFIXES)
    }
    return envctl.snapshot_env(relevant)


def _write_result(path: Path, obj: dict) -> None:
    obj.setdefault("resolved_env", _resolved_env_snapshot())
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _assert_controlled_env(payload: dict) -> None:
    """Runtime verification (review #26 fix 2): after src import ran
    load_dotenv, every managed variable must still hold exactly the value
    envctl built. A mismatch means the environment the run record claims is
    not the environment that executed — fail the phase, loudly."""
    import os
    expected: dict[str, str] = payload.get("expected_env") or {}
    mismatches = {
        k: {"expected": v, "actual": os.environ.get(k)}
        for k, v in expected.items()
        if os.environ.get(k) != v
    }
    if mismatches:
        raise RuntimeError(
            "controlled-env violation after src import: "
            + json.dumps(mismatches, default=str)
        )


def _provider_of(params: dict) -> str:
    provider = params.get("provider")
    if not provider:
        raise ValueError(
            "worker payload params carry no resolved provider — run configs "
            "must pass through envctl.resolve_model_config (review #27)"
        )
    return provider


def _scratch_appdata() -> Path:
    import os
    d = os.environ.get("MAGPIE_DATA_DIR", "")
    assert d, "worker must run with MAGPIE_DATA_DIR set"
    return Path(d)


def _write_settings(params: dict) -> Path:
    """Scratch settings.json BEFORE any src import that reads it.

    pipeline.ask() reads settings for answer temperature (default 0.7!) and
    enumerate_lists; llm.py reads provider (though MAGPIE_FORCE_PROVIDER
    overrides it). Everything a run sweeps must be pinned here or in env.
    """
    appdata = _scratch_appdata()
    appdata.mkdir(parents=True, exist_ok=True)
    settings = {
        "provider": _provider_of(params),
        "temperature": float(params.get("temperature", 0.0)),
        "top_k": int(params.get("top_k", 5)),
        "rewrite_default": bool(params.get("rewrite", True)),
        "enumerate_lists": bool(params.get("enumerate_lists", True)),
    }
    path = appdata / "settings.json"
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return path


def phase_boot(payload: dict) -> dict:
    """Import the backend under the controlled env and report what resolved
    where. The isolation test asserts on these values."""
    import os
    _write_settings(payload.get("params", {}))

    from src import manifest  # first src import — setdefaults fire (or no-op) here

    _assert_controlled_env(payload)

    from src.llm import active_provider
    from src.inference.profiles import default_text_profile, get_profile
    prof = get_profile(default_text_profile())
    try:
        # import inside the try so a renamed symbol reports as <unresolved>
        # instead of crashing boot (review #36 — the resolve_binary
        # ImportError did exactly that)
        from src.inference.llama_server_binary import find_llama_server

        binary = str(find_llama_server())
    except Exception as e:  # noqa: BLE001 — report, don't crash boot
        binary = f"<unresolved: {e}>"

    return {
        "app_data_dir": str(manifest.APP_DATA_DIR),
        "hf_home": os.environ.get("HF_HOME", ""),
        "hf_hub_offline": os.environ.get("HF_HUB_OFFLINE", ""),
        "fastembed_cache": os.environ.get("FASTEMBED_CACHE_PATH", ""),
        "qdrant_endpoint": os.environ.get("QDRANT_CLUSTER_ENDPOINT", ""),
        "provider": active_provider().name,
        "text_profile": default_text_profile(),
        "resolved_ctx_size": prof.args.ctx_size,
        "resolved_temperature": prof.args.temperature,
        "llama_server_binary": binary,
        "settings_path": str(_scratch_appdata() / "settings.json"),
    }


def phase_index(payload: dict) -> dict:
    import asyncio

    params = payload.get("params", {})
    corpus = Path(payload["corpus_dir"])
    assert corpus.is_dir(), f"corpus dir missing: {corpus}"
    _write_settings(params)

    from src import manifest  # noqa: F401 — trigger load_dotenv before the check
    _assert_controlled_env(payload)

    appdata = _scratch_appdata()
    (appdata / "indexing_rules.json").write_text(
        json.dumps({"include_paths": [{"path": str(corpus), "enabled": True}]}, indent=2),
        encoding="utf-8",
    )

    from src.pipeline import sync_files

    t0 = time.monotonic()
    summary_tier_note = None
    try:
        asyncio.run(
            sync_files(
                corpus,
                do_fast=bool(params.get("index_fast_tier", True)),
                do_summary=bool(params.get("index_summary_tier", True)),
            )
        )
    except SystemExit as e:
        # src/stage1/summarize.py:603 sys.exit()s when the summary tier finds
        # zero supported files — expected-benign for all-image corpora (every
        # file routed to the fast tier, which has already run by then).
        # Anything else is a real failure.
        msg = str(e)
        if "no supported files" in msg:
            summary_tier_note = msg
        else:
            raise
    wall_s = time.monotonic() - t0

    manifest_path = appdata / "manifest.json"
    manifest_raw = {}
    if manifest_path.exists():
        try:
            manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            manifest_raw = {"_parse_error": str(e)}

    return {
        "corpus_dir": str(corpus),
        "wall_s": round(wall_s, 2),
        "summary_tier_note": summary_tier_note,
        "manifest_path": str(manifest_path),
        "manifest": manifest_raw,
    }


def phase_answer(payload: dict) -> dict:
    """Answer golden questions through the REAL pipeline (pipeline mode).

    Resume-safe: answers already in the output JSONL are skipped; each result
    is flushed before the next question starts.
    """
    import hashlib

    params = payload.get("params", {})
    _write_settings(params)
    questions = payload["questions"]          # [{id, question}, ...]
    out_path = Path(payload["answers_jsonl"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume guard (review #32): answers.jsonl is only appendable under the
    # exact params that started it — otherwise one file silently merges two
    # configurations and every downstream metric averages across both.
    params_hash = hashlib.sha256(
        json.dumps(params, sort_keys=True, default=str).encode()
    ).hexdigest()
    guard_path = out_path.with_suffix(out_path.suffix + ".params.json")
    if out_path.exists() and guard_path.exists():
        prior = json.loads(guard_path.read_text(encoding="utf-8"))
        if prior.get("params_sha256") != params_hash:
            raise RuntimeError(
                f"refusing to resume: {out_path} was produced by different "
                f"params (prior {prior.get('params_sha256', '?')[:12]}, "
                f"now {params_hash[:12]}). Move the file aside or use a new "
                f"run dir."
            )
    elif out_path.exists() and not guard_path.exists():
        raise RuntimeError(
            f"refusing to resume: {out_path} exists with no params guard "
            f"({guard_path.name}) — provenance unknown; move it aside."
        )
    else:
        guard_path.write_text(
            json.dumps({"params_sha256": params_hash, "params": params},
                       indent=2, default=str),
            encoding="utf-8",
        )

    done: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["qa_id"])
            except Exception:  # noqa: BLE001 — malformed line = redo that qa
                pass

    from src.pipeline import ask
    import asyncio

    from src import manifest  # noqa: F401
    _assert_controlled_env(payload)

    from src.inference.llm_log import session_log_path

    _provider_of(params)  # raise before any question if unresolved
    top_k = int(params.get("top_k", 5))
    rewrite = bool(params.get("rewrite", True))
    # Production ships visual-tier search OFF (server.py:303-306, ask()
    # default False). Review #31: baseline must match production; datasets
    # that need it (scanned receipts) turn it on EXPLICITLY in their config.
    fast = bool(params.get("fast_search", False))

    n_ok = n_err = 0
    for q in questions:
        qa_id = q["id"]
        if qa_id in done:
            continue
        print(f"[eval] qa_id={qa_id} begin", file=sys.stderr, flush=True)
        row: dict = {"qa_id": qa_id, "variant": 0, "question": q["question"]}
        t0 = time.monotonic()
        try:
            res = asyncio.run(
                ask(q["question"], top_k=top_k, rewrite=rewrite, fast=fast)
            )
            row.update(
                rewritten_query={
                    "query": res.search_query.query,
                    "keywords": list(getattr(res.search_query, "keywords", []) or []),
                },
                retrieved=[
                    {
                        "path": str(r.path),
                        "score": float(r.score),
                        "rank": i,
                        "tier": getattr(r, "tier", None),
                    }
                    for i, r in enumerate(res.retrieved, 1)
                ],
                answer=res.answer,
                cited=[str(p) for p in res.sources_used],
                not_found=bool(res.not_found),
                not_found_topic=res.not_found_topic,
                error=None,
            )
            n_ok += 1
        except Exception as e:  # noqa: BLE001 — record and continue, never abort the run
            row.update(
                retrieved=[], answer="", cited=[], not_found=False,
                error=f"{type(e).__name__}: {e}",
            )
            n_err += 1
        row["latency_s"] = {"total": round(time.monotonic() - t0, 2)}
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        print(f"[eval] qa_id={qa_id} end ok={row['error'] is None}",
              file=sys.stderr, flush=True)

    llm_log = session_log_path()

    # Review #33: an all-errors run must not look finished. Per-question
    # errors are recorded and tolerated, but a majority-broken phase fails.
    attempted = n_ok + n_err
    if attempted and (n_err / attempted) > 0.5:
        raise RuntimeError(
            f"answer phase majority-failed: {n_err}/{attempted} questions "
            f"errored — configuration is likely broken; see the rows in "
            f"{out_path}"
        )

    return {
        "answers_jsonl": str(out_path),
        "answered": n_ok,
        "errors": n_err,
        "skipped_done": len(done),
        "llm_log": str(llm_log) if llm_log else None,
    }


def phase_retrieve(payload: dict) -> dict:
    """Retrieval-only pass (PLAN.md §3 `--retrieval-only`, composed mode).

    Mirrors pipeline.ask()'s search step exactly — same rewrite builder, same
    run_search arguments — but WITHOUT gate_to_solo and at k_max, because
    ask() returns the post-gate list: on solo-gated questions the answer pass
    records one file and the true ranking is unrecoverable from it. This
    phase is therefore the sole source of retrieval metrics, and the
    solo-gate observation falls out of comparing the two passes.
    """
    params = payload.get("params", {})
    _write_settings(params)
    questions = payload["questions"]
    out_path = Path(payload["retrieve_jsonl"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    from src import manifest  # noqa: F401
    _assert_controlled_env(payload)
    _provider_of(params)

    import asyncio

    from src.stage2.search import run_search
    from src.stage2.search import rewrite_query, raw_query

    k_max = int(params.get("top_k_retrieval_max", 12))
    rewrite = bool(params.get("rewrite", True))
    fast = bool(params.get("fast_search", False))
    enumerate_lists = bool(params.get("enumerate_lists", True))

    rows_out = []
    for q in questions:
        t0 = time.monotonic()
        row: dict = {"qa_id": q["id"], "question": q["question"]}
        try:
            sq = rewrite_query(q["question"]) if rewrite else raw_query(q["question"])
            t_search = time.monotonic()
            hits = run_search(
                sq, k_max, question=q["question"], skip_fast=not fast,
                rerank=True, enumerate_lists=enumerate_lists,
            )
            row.update(
                rewritten_query={"query": sq.query,
                                 "keywords": list(getattr(sq, "keywords", []) or [])},
                ranked=[
                    {"path": str(r.path), "score": float(r.score), "rank": i,
                     "tier": getattr(r, "tier", None)}
                    for i, r in enumerate(hits, 1)
                ],
                latency_s={"rewrite": round(t_search - t0, 3),
                           "search": round(time.monotonic() - t_search, 3)},
                error=None,
            )
        except Exception as e:  # noqa: BLE001
            row.update(ranked=[], error=f"{type(e).__name__}: {e}")
        rows_out.append(row)

    with out_path.open("w", encoding="utf-8") as f:
        for row in rows_out:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    n_err = sum(1 for r in rows_out if r.get("error"))
    if rows_out and n_err / len(rows_out) > 0.5:
        raise RuntimeError(
            f"retrieve phase majority-failed: {n_err}/{len(rows_out)} — see {out_path}"
        )
    return {"retrieve_jsonl": str(out_path), "n": len(rows_out), "errors": n_err}


PHASES = {
    "boot": phase_boot,
    "index": phase_index,
    "retrieve": phase_retrieve,
    "answer": phase_answer,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=sorted(PHASES))
    ap.add_argument("--payload", required=True)
    ap.add_argument("--result", required=True)
    args = ap.parse_args()

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    result = PHASES[args.phase](payload)
    _write_result(Path(args.result), result)


if __name__ == "__main__":
    main()
