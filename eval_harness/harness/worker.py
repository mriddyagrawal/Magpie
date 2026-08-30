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
import progress  # noqa: E402  (sibling; stdlib-only, no src.* import)


def _progress(payload: dict, **kw) -> None:
    """Best-effort progress.json update. run_worker injects `raw_dir` into
    every payload; a payload without it (tests, hand-run phases) is a no-op,
    and progress.update itself never raises."""
    raw = payload.get("raw_dir")
    if raw:
        progress.update(Path(raw), **kw)


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

    try:
        from src.stage1_fast.device import detect_device
        col_resolved = detect_device().model_family
    except Exception:  # noqa: BLE001 - stamp is provenance, never fatal
        col_resolved = None
    return {
        "corpus_dir": str(corpus),
        "wall_s": round(wall_s, 2),
        "summary_tier_note": summary_tier_note,
        "manifest_path": str(manifest_path),
        "manifest": manifest_raw,
        "col_model_resolved": col_resolved,
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
    _progress(payload, phase="answer",
              done=len(done), total=len(questions))
    for q in questions:
        qa_id = q["id"]
        if qa_id in done:
            continue
        print(f"[eval] qa_id={qa_id} begin", file=sys.stderr, flush=True)
        _progress(payload, done=len(done) + n_ok + n_err,
                  total=len(questions), current=qa_id)
        row: dict = {"qa_id": qa_id, "variant": 0, "question": q["question"]}
        t0 = time.monotonic()
        try:
            res = asyncio.run(
                ask(q["question"], top_k=top_k, rewrite=rewrite, fast=fast)
            )
            row.update(
                search_query={
                    "final_query": res.search_query.query,
                    "keywords": list(getattr(res.search_query, "keywords", []) or []),
                    # whether the LLM rewrite step ran (config), not whether
                    # the text happens to differ from the raw question
                    "rewritten": rewrite,
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
                magpie_answer=res.answer,
                magpie_cited=[str(p) for p in res.sources_used],
                not_found=bool(res.not_found),
                not_found_topic=res.not_found_topic,
                error=None,
            )
            n_ok += 1
        except Exception as e:  # noqa: BLE001 — record and continue, never abort the run
            row.update(
                retrieved=[], magpie_answer="", magpie_cited=[], not_found=False,
                error=f"{type(e).__name__}: {e}",
            )
            n_err += 1
        row["latency_s"] = {"total": round(time.monotonic() - t0, 2)}
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        print(f"[eval] qa_id={qa_id} end ok={row['error'] is None}",
              file=sys.stderr, flush=True)
        _progress(payload, done=len(done) + n_ok + n_err, total=len(questions))

    llm_log = session_log_path()

    # Review #33: an all-errors run must not look finished. Per-question
    # errors are recorded and tolerated, but a majority-broken phase fails.
    # #106: uniformly-empty retrieval is failure, not measurement - the
    # pipeline short-circuits to not_found without invoking the model, so
    # error counting alone (#33) is blind to it.
    rows_all = [json.loads(l) for l in out_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    n_zero_retrieved = sum(1 for r in rows_all if not r.get("retrieved"))
    if rows_all and n_zero_retrieved / len(rows_all) > 0.9:
        raise RuntimeError(
            f"answer phase degenerate (#106): {n_zero_retrieved}/{len(rows_all)} "
            f"rows retrieved nothing - the model was never invoked; the index "
            f"is empty or unsearchable"
        )

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
    """Pre-gate ranking pass at k_max (PLAN.md §3; runs AFTER the answer
    phase in composed mode).

    ask() returns the post-gate, top_k-truncated list, so the full ranking
    the metrics need is unrecoverable from the answer pass alone. This phase
    supplies it — but it must rank the SAME query the answer pass searched
    with, or the metrics describe a different run (measured 2026-08-30:
    a second LLM rewrite diverged on 45/120 questions, partly because the
    rewriter embeds wall-clock text, and flipped top-1 on 9/120).

    Composed mode therefore REPLAYS each question's recorded
    (query, keywords) from answers.jsonl (payload["answers_jsonl"]) instead
    of rewriting again; `query_source` records which path produced each row.
    Standalone --retrieval-only mode (no answer pass) still rewrites here.

    Residual divergence that replay cannot remove: the answer pass fetches
    per-tier pools sized by top_k while this pass uses k_max, and
    approximate search can order near-ties differently at different pool
    sizes. enrich records that divergence per row instead of hiding it.
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

    from src.stage2.search import SearchQuery, run_search
    from src.stage2.search import rewrite_query, raw_query

    k_max = int(params.get("top_k_retrieval_max", 12))
    rewrite = bool(params.get("rewrite", True))
    fast = bool(params.get("fast_search", False))
    enumerate_lists = bool(params.get("enumerate_lists", True))
    # #112-adjacent fix: rerank was hardcoded True here and survived only
    # because envctl always pins MAGPIE_RERANK; thread the param properly.
    rerank = bool(params.get("rerank", True))

    # Composed mode: replay the answer pass's exact search inputs.
    recorded: dict[str, dict] = {}
    replay_path = payload.get("answers_jsonl")
    if replay_path and Path(replay_path).exists():
        for line in Path(replay_path).read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001 — malformed line = no replay for it
                continue
            rq = rec.get("search_query") or rec.get("rewritten_query") or {}
            q = rq.get("final_query") or rq.get("query")
            if q:
                recorded[rec["qa_id"]] = {
                    "final_query": q,
                    "keywords": list(rq.get("keywords") or []),
                    "rewritten": rq.get("rewritten", None),
                }

    rows_out = []
    _progress(payload, phase="retrieve", done=0, total=len(questions))
    for q in questions:
        t0 = time.monotonic()
        _progress(payload, done=len(rows_out), total=len(questions),
                  current=q["id"])
        row: dict = {"qa_id": q["id"], "question": q["question"]}
        try:
            rec = recorded.get(q["id"])
            if rec is not None:
                sq = SearchQuery(
                    query=rec["final_query"],
                    keywords=list(rec.get("keywords") or []),
                )
                row["query_source"] = "replayed_from_answer_pass"
            else:
                # standalone retrieval-only mode, or an answer row that
                # errored before recording its query
                sq = rewrite_query(q["question"]) if rewrite else raw_query(q["question"])
                row["query_source"] = "own_rewrite" if rewrite else "raw"
            t_search = time.monotonic()
            hits = run_search(
                sq, k_max, question=q["question"], skip_fast=not fast,
                rerank=rerank, enumerate_lists=enumerate_lists,
            )
            row.update(
                search_query={
                    "final_query": sq.query,
                    "keywords": list(getattr(sq, "keywords", []) or []),
                    # replayed rows inherit the answer pass's flag when it
                    # recorded one; otherwise (standalone mode, or replaying
                    # an old-format run) the config param is the truth -
                    # the same config drove both passes.
                    "rewritten": (rec.get("rewritten")
                                  if rec is not None and rec.get("rewritten") is not None
                                  else rewrite),
                },
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

    n_zero = sum(1 for r in rows_out if not r.get("ranked"))
    if rows_out and n_zero / len(rows_out) > 0.9:
        raise RuntimeError(
            f"retrieve phase degenerate (#106): {n_zero}/{len(rows_out)} "
            f"questions got zero hits - index empty or unsearchable"
        )
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
