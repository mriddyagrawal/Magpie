"""Run orchestrator (PLAN.md §3): config in → runs/<run_id>/ out.

    uv run python eval_harness/harness/run.py \
        --config eval_harness/configs/baseline.json \
        [--questions-limit N] [--index-only | --retrieval-only] \
        [--rebuild-index] [--run-id NAME]

Produces (committed, directly in runs/<run_id>/): run.json (provenance),
metrics.json, report.md. Everything else — scratch appdata, qdrant storage,
worker logs, answer/retrieve JSONL — lives under runs/<run_id>/raw/
(gitignored; holds indexed corpus content).

Indexes are a shared, first-class store: eval_harness/indexes/<index_key>/
(gitignored), keyed by hash(dataset + index-side params). On launch the
runner mounts a matching store entry (seconds) or builds and then publishes
one; --rebuild-index forces a fresh build. Runs are therefore pure
answer-side experiments by default. Every run also stamps golden_sha (hash
of the dataset's golden.json) - the comparability triple is
(params, backend sha, golden sha).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import backend  # noqa: E402
import enrich  # noqa: E402
import envctl  # noqa: E402
import progress  # noqa: E402

REPO = HERE.parents[1]
EVAL = REPO / "eval_harness"
INDEX_STORE = EVAL / "indexes"

INDEX_SIDE_PARAMS = (
    "model_config", "index_fast_tier", "index_summary_tier", "local_n_ctx",
    # col_model: two machines resolving "auto" differently MUST get
    # different index keys - ColQwen and ColSmol vectors are incompatible.
    # The hash uses the param value; the RESOLVED family additionally lands
    # in run.json and the index store meta.
    "col_model",
)


def index_params_hash(dataset: str, params: dict) -> str:
    view = {"dataset": dataset, **{k: params.get(k) for k in INDEX_SIDE_PARAMS}}
    return hashlib.sha256(json.dumps(view, sort_keys=True).encode()).hexdigest()[:16]


def load_dataset(name: str, override_dir: str | None = None) -> dict:
    ds_dir = Path(override_dir) if override_dir else EVAL / "datasets" / name
    golden = json.loads((ds_dir / "golden.json").read_text(encoding="utf-8"))
    pointer = ds_dir / "corpus_root.local.json"
    if not pointer.exists():
        raise SystemExit(
            f"{pointer} missing — run the dataset's prepare script on this "
            f"machine first (corpora are per-machine; PLAN §6)"
        )
    corpus_root = Path(json.loads(pointer.read_text())["corpus_root"])
    if not corpus_root.is_dir():
        raise SystemExit(f"corpus root {corpus_root} missing on this machine")
    manifest = json.loads((ds_dir / "manifest.json").read_text(encoding="utf-8"))
    return {"name": name, "dir": ds_dir, "golden": golden,
            "corpus_root": corpus_root, "manifest": manifest}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--run-id")
    ap.add_argument("--questions-limit", type=int)
    ap.add_argument("--index-only", action="store_true")
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--rebuild-index", action="store_true",
                    help="build a fresh index even when the store has one")
    ap.add_argument("--slot", type=int, default=0)
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    params = dict(config["params"])
    resolved = envctl.resolve_model_config(params)
    params["provider"] = resolved["provider"]
    params["grammar"] = resolved["grammar"]

    dataset = load_dataset(config["dataset"], config.get("dataset_dir"))
    golden = dataset["golden"]

    # Review #37: a dataset whose items require the visual tier must not be
    # run with visual search disabled — the run would complete and score a
    # different system than the golden set declares.
    needs_visual = any((q.get("requires") or {}).get("visual_tier") for q in golden)
    if needs_visual and not params.get("fast_search"):
        raise SystemExit(
            f"dataset {config['dataset']!r} has visual_tier-required items but "
            f"the config sets fast_search={params.get('fast_search')!r} — enable "
            f"it explicitly (see baseline.json _notes) or use a text dataset"
        )
    # Review #35: flat gold basenames anchor path matching on the final
    # segment, which is only sound when basenames are unique.
    basenames = [Path(f["name"]).name for f in dataset["manifest"].get("files", [])]
    if len(basenames) != len(set(basenames)):
        raise SystemExit(f"dataset {config['dataset']!r} has duplicate file basenames")
    questions = [{"id": q["id"], "question": q["question"]} for q in golden]
    if args.questions_limit:
        questions = questions[: args.questions_limit]

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = args.run_id or f"{ts}-{config['dataset']}-{config['config_name']}"
    run_dir = EVAL / "runs" / run_id
    raw = run_dir / "raw"
    appdata = raw / "appdata"
    raw.mkdir(parents=True, exist_ok=True)

    ports = envctl.Ports.for_slot(args.slot)
    env = envctl.build_env(appdata, params, ports, extra=resolved["env_extra"])
    expected_env = envctl.non_secret(env)

    idx_hash = index_params_hash(config["dataset"], params)
    golden_sha = hashlib.sha256(
        (dataset["dir"] / "golden.json").read_bytes()
    ).hexdigest()[:16]
    run_record: dict = {
        "run_id": run_id,
        "config_name": config["config_name"],
        "dataset": config["dataset"],
        "params": params,
        "index_params_hash": idx_hash,
        "golden_sha": golden_sha,
        "questions": len(questions),
        # scoped shas (#102): the last commit touching the code under test,
        # not repo HEAD - so doc/skill commits don't fake a "code change"
        "backend_git_sha": envctl.git_sha(REPO, "src/"),
        "harness_git_sha": envctl.git_sha(REPO, "eval_harness/"),
        "repo_head_sha": envctl.git_sha(REPO),
        "status": "running",  # #54: running | complete | failed
        "machine": envctl.machine_info(),
        "env_snapshot": envctl.snapshot_env(env),
        "dataset_manifest_files": dataset["manifest"].get("n_files"),
        # #112: a solo_gated=0% run is ambiguous - never triggered vs
        # couldn't trigger. The gate is structurally off when the rerank
        # stage is killed (its margin is cross-encoder-scale) or when the
        # margin itself disables it. Stamped so the confound travels with
        # the data, not just envctl comments.
        "solo_gate_structurally_off": (
            not params.get("rerank", True)
            or float(params.get("solo_margin", 2.0)) <= 0
        ),
        "started_utc": ts,
        "ports": {"qdrant_http": ports.qdrant_http, "llama_base": ports.llama_base},
        "phases": {},
    }

    def save_record() -> None:
        envctl.dump_json(run_dir / "run.json", run_record)

    save_record()
    # live-progress sidecar (harness/progress.py + `just eval-watch`): the
    # harness writes counters as data; a localhost page polls them. Both
    # files are gitignored; every call is exception-swallowing by contract.
    progress.write_latest(EVAL / "runs", run_id)
    progress.update(raw, run_id=run_id, status="running")
    fp_app_before = envctl.appdata_fingerprint()
    fp_cache_before = envctl.cache_fingerprint()

    # --- index store mount (three-layer cache: golden / index / run) ---
    index_mounted = False
    store_dir = INDEX_STORE / idx_hash
    if not args.rebuild_index and (store_dir / "meta.json").exists():
        meta = json.loads((store_dir / "meta.json").read_text(encoding="utf-8"))
        for sub in ("appdata", "qdrant"):
            dst = raw / sub
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(store_dir / sub, dst)
        index_mounted = True
        run_record["index_store"] = {
            "key": idx_hash, "hit": True,
            "built_under_sha": meta.get("backend_sha"),
        }
        print(f"[run] index store HIT {idx_hash} (built {meta.get('built_utc')})")
        if meta.get("backend_sha") != run_record["backend_git_sha"]:
            # key is params-only so routine commits don't invalidate; a SHA
            # drift is recorded and warned, since indexing code may differ
            print(f"[run] WARNING: stored index built under "
                  f"{str(meta.get('backend_sha'))[:12]}, current backend is "
                  f"{run_record['backend_git_sha'][:12]} - rebuild with "
                  f"--rebuild-index if indexing code changed", file=sys.stderr)
        # the sidecar mirrors the mount so the watch page needs no inference
        progress.phase_done(raw, "index", note="mounted from store")
    else:
        run_record["index_store"] = {"key": idx_hash, "hit": False}
        print(f"[run] index store MISS {idx_hash} - will build and publish")
    # persist the mount verdict NOW: run.json is otherwise not rewritten
    # until the next phase boundary, and on a store hit that is the END of
    # the answer pass - an hour in which the on-disk record claims no
    # index_store at all (watch-page grey-index bug, 2026-08-30)
    save_record()

    qdrant = backend.QdrantInstance(
        storage_dir=raw / "qdrant", http_port=ports.qdrant_http,
        grpc_port=ports.qdrant_grpc, log_path=raw / "qdrant.log",
    )

    # Drift-guard provenance stamp: its own worker phase, run BEFORE the
    # clock starts and before any timed phase, because the first run on a
    # machine hashes the model files (~3 GB, 10-20 s) and that must not be
    # charged to phases.index.wall_s. Never fatal to the run.
    try:
        prov = backend.run_worker(
            "provenance", run_dir, env,
            {"params": params, "expected_env": expected_env}, timeout_s=600,
        )
        run_record["provenance"] = prov.get("provenance")
    except Exception as e:  # noqa: BLE001 - a missing stamp is not a failed run
        run_record["provenance"] = {"error": str(e)[:200]}
    save_record()

    t0 = time.monotonic()
    completed = False
    try:
        qdrant.start()

        if not index_mounted:
            print(f"[run] indexing {dataset['corpus_root']} …")
            progress.update(raw, phase="index", note=str(dataset["corpus_root"]))
            t = time.monotonic()
            idx = backend.run_worker(
                "index", run_dir, env,
                {"params": params, "corpus_dir": str(dataset["corpus_root"]),
                 "expected_env": expected_env},
                timeout_s=6 * 3600,
            )
            run_record["col_model_resolved"] = idx.get("col_model_resolved")
            run_record["phases"]["index"] = {
                "wall_s": round(time.monotonic() - t, 1),
                "manifest_entries": len(idx.get("manifest") or {}),
                # a sys.exit absorbed as benign is still a product finding (#53)
                "summary_tier_note": idx.get("summary_tier_note"),
            }
            save_record()
            # #106: an index phase that indexed NOTHING must never reach the
            # answer phase - downstream it produces 106 clean-looking
            # not_found rows with zero errors and every provenance signal
            # green, a published zero that measures nothing.
            if run_record["phases"]["index"]["manifest_entries"] == 0:
                run_record["status"] = "failed"
                save_record()
                raise SystemExit(
                    f"[run] FAILED (#106): index produced 0 manifest entries - "
                    f"corpus path or file discovery is wrong; see "
                    f"{raw / 'worker_index.log'}"
                )
            print(f"[run] index done in {run_record['phases']['index']['wall_s']}s")
            progress.phase_done(
                raw, "index",
                manifest_entries=run_record["phases"]["index"]["manifest_entries"],
            )

        # Answer BEFORE retrieve (2026-08-30): the retrieve pass replays the
        # answer pass's recorded queries so both phases rank the same inputs.
        # A second LLM rewrite diverged on 45/120 questions (wall-clock text
        # in the rewriter) and flipped top-1 on 9/120 - retrieval metrics
        # were describing a different run than the answers.
        answered = False
        if not args.index_only and not args.retrieval_only:
            print(f"[run] answer pass ({len(questions)} questions) …")
            progress.update(raw, phase="answer", done=0, total=len(questions))
            t = time.monotonic()
            ans = backend.run_worker(
                "answer", run_dir, env,
                {"params": params, "questions": questions,
                 "answers_jsonl": str(raw / "answers.jsonl"),
                 "expected_env": expected_env},
                timeout_s=12 * 3600,
            )
            run_record["phases"]["answer"] = {
                "wall_s": round(time.monotonic() - t, 1),
                "answered": ans["answered"], "errors": ans["errors"],
                "llm_log": ans.get("llm_log"),
            }
            save_record()
            progress.phase_done(raw, "answer", errors=ans["errors"])
            answered = True

        if not args.index_only:
            print(f"[run] retrieval pass ({len(questions)} questions) …")
            progress.update(raw, phase="retrieve", done=0, total=len(questions))
            t = time.monotonic()
            retrieve_payload = {
                "params": params, "questions": questions,
                "retrieve_jsonl": str(raw / "retrieve.jsonl"),
                "expected_env": expected_env,
            }
            if answered:
                retrieve_payload["answers_jsonl"] = str(raw / "answers.jsonl")
            ret = backend.run_worker(
                "retrieve", run_dir, env, retrieve_payload, timeout_s=3600,
            )
            run_record["phases"]["retrieve"] = {
                "wall_s": round(time.monotonic() - t, 1), "errors": ret["errors"],
            }
            save_record()
            progress.phase_done(raw, "retrieve", errors=ret["errors"])
        completed = True
    finally:
        qdrant.stop()
        if not completed:
            run_record["status"] = "failed"
            save_record()
            progress.update(raw, status="failed")

    fp_cache_after = envctl.cache_fingerprint()
    run_record["isolation"] = {
        "real_appdata_untouched": envctl.appdata_fingerprint() == fp_app_before,
        # "unchanged" = no model blobs added/removed/resized; .locks and
        # .no_exist negative-cache metadata excluded by definition (#48)
        "cache_model_blobs_unchanged": fp_cache_after == fp_cache_before,
        "cache_before": fp_cache_before,
        "cache_after": fp_cache_after,
    }
    run_record["wall_s_total"] = round(time.monotonic() - t0, 1)
    save_record()

    if not args.index_only:
        print("[run] enriching + scoring …")
        progress.update(raw, phase="enrich")
        enrich.enrich_run(run_dir, golden, params)
        progress.phase_done(raw, "enrich")
        print(f"[run] report: {run_dir / 'report.md'}")

    # Isolation violations FAIL the run (review #47: a compensating control
    # that only writes a JSON field nobody must read is not a control). The
    # artifacts above are written first — they are the evidence.
    iso = run_record["isolation"]
    if not (iso["cache_model_blobs_unchanged"] and iso["real_appdata_untouched"]):
        run_record["status"] = "failed_isolation"
        save_record()
        progress.update(raw, status="failed_isolation")
    if not iso["cache_model_blobs_unchanged"]:
        raise SystemExit(
            f"[run] FAILED: shared model cache changed during the run "
            f"(before={fp_cache_before} after={fp_cache_after}) — something "
            f"downloaded. Runs are no longer comparable until the cache is "
            f"reconciled; see {run_dir / 'run.json'}"
        )
    if not iso["real_appdata_untouched"]:
        raise SystemExit(
            f"[run] FAILED: the REAL app data dir changed during the run — "
            f"isolation broken; do not trust these artifacts. "
            f"See {run_dir / 'run.json'}"
        )

    if completed and not index_mounted and (
        run_record.get("phases", {}).get("index", {}).get("manifest_entries", 0) > 0
    ):
        tmp = INDEX_STORE / f".tmp-{idx_hash}"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        for sub in ("appdata", "qdrant"):
            shutil.copytree(raw / sub, tmp / sub)
        envctl.dump_json(tmp / "meta.json", {
            "key": idx_hash,
            "dataset": config["dataset"],
            "index_side_params": {k: params.get(k) for k in INDEX_SIDE_PARAMS},
            "backend_sha": run_record["backend_git_sha"],
            "built_utc": ts,
            "built_by_run": run_id,
        })
        if store_dir.exists():
            shutil.rmtree(store_dir)
        tmp.replace(store_dir)
        print(f"[run] index published to store as {idx_hash}")

    run_record["status"] = "complete"
    save_record()
    progress.update(raw, status="complete")
    print(f"[run] done in {run_record['wall_s_total']}s -> {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
