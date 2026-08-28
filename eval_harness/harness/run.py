"""Run orchestrator (PLAN.md §3): config in → runs/<run_id>/ out.

    uv run python eval_harness/harness/run.py \
        --config eval_harness/configs/baseline.json \
        [--questions-limit N] [--index-only | --retrieval-only] \
        [--reuse-index <prior_run_id>] [--run-id NAME]

Produces (committed, directly in runs/<run_id>/): run.json (provenance),
metrics.json, report.md. Everything else — scratch appdata, qdrant storage,
worker logs, answer/retrieve JSONL — lives under runs/<run_id>/raw/
(gitignored; holds indexed corpus content).

--reuse-index copies a prior run's scratch appdata + qdrant storage instead
of re-indexing: the embryonic form of PLAN §7 Phase 4's index cache. Valid
only when the prior run used the same dataset + index-side params (enforced
via the index params hash recorded in run.json).
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

REPO = HERE.parents[1]
EVAL = REPO / "eval_harness"

INDEX_SIDE_PARAMS = (
    "model_config", "index_fast_tier", "index_summary_tier", "local_n_ctx",
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
    ap.add_argument("--reuse-index", metavar="PRIOR_RUN_ID")
    ap.add_argument("--slot", type=int, default=0)
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    params = dict(config["params"])
    resolved = envctl.resolve_model_config(params)
    params["provider"] = resolved["provider"]
    params["grammar"] = resolved["grammar"]

    dataset = load_dataset(config["dataset"], config.get("dataset_dir"))
    golden = dataset["golden"]
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
    run_record: dict = {
        "run_id": run_id,
        "config_name": config["config_name"],
        "dataset": config["dataset"],
        "params": params,
        "index_params_hash": idx_hash,
        "questions": len(questions),
        "backend_git_sha": envctl.git_sha(REPO),
        "machine": envctl.machine_info(),
        "env_snapshot": envctl.snapshot_env(env),
        "dataset_manifest_files": dataset["manifest"].get("n_files"),
        "started_utc": ts,
        "ports": {"qdrant_http": ports.qdrant_http, "llama_base": ports.llama_base},
        "phases": {},
    }

    def save_record() -> None:
        envctl.dump_json(run_dir / "run.json", run_record)

    save_record()
    fp_app_before = envctl.appdata_fingerprint()
    fp_cache_before = envctl.cache_fingerprint()

    # --- index reuse (embryonic Phase 4 cache) ---
    if args.reuse_index:
        prior_dir = EVAL / "runs" / args.reuse_index
        prior = json.loads((prior_dir / "run.json").read_text(encoding="utf-8"))
        if prior.get("index_params_hash") != idx_hash:
            raise SystemExit(
                f"--reuse-index refused: prior run's index params hash "
                f"{prior.get('index_params_hash')} != this config's {idx_hash} "
                f"(dataset or index-side params differ)"
            )
        for sub in ("appdata", "qdrant"):
            src, dst = prior_dir / "raw" / sub, raw / sub
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        run_record["reused_index_from"] = args.reuse_index
        print(f"[run] reusing index from {args.reuse_index}")

    qdrant = backend.QdrantInstance(
        storage_dir=raw / "qdrant", http_port=ports.qdrant_http,
        grpc_port=ports.qdrant_grpc, log_path=raw / "qdrant.log",
    )

    t0 = time.monotonic()
    try:
        qdrant.start()

        if not args.reuse_index:
            print(f"[run] indexing {dataset['corpus_root']} …")
            t = time.monotonic()
            idx = backend.run_worker(
                "index", run_dir, env,
                {"params": params, "corpus_dir": str(dataset["corpus_root"]),
                 "expected_env": expected_env},
                timeout_s=6 * 3600,
            )
            run_record["phases"]["index"] = {
                "wall_s": round(time.monotonic() - t, 1),
                "manifest_entries": len(idx.get("manifest") or {}),
            }
            save_record()
            print(f"[run] index done in {run_record['phases']['index']['wall_s']}s")

        if not args.index_only:
            print(f"[run] retrieval pass ({len(questions)} questions) …")
            t = time.monotonic()
            ret = backend.run_worker(
                "retrieve", run_dir, env,
                {"params": params, "questions": questions,
                 "retrieve_jsonl": str(raw / "retrieve.jsonl"),
                 "expected_env": expected_env},
                timeout_s=3600,
            )
            run_record["phases"]["retrieve"] = {
                "wall_s": round(time.monotonic() - t, 1), "errors": ret["errors"],
            }
            save_record()

        if not args.index_only and not args.retrieval_only:
            print(f"[run] answer pass ({len(questions)} questions) …")
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
    finally:
        qdrant.stop()

    run_record["isolation"] = {
        "real_appdata_untouched": envctl.appdata_fingerprint() == fp_app_before,
        "cache_unchanged": envctl.cache_fingerprint() == fp_cache_before,
    }
    run_record["wall_s_total"] = round(time.monotonic() - t0, 1)
    save_record()

    if not run_record["isolation"]["real_appdata_untouched"]:
        print("[run] WARNING: real app dir fingerprint changed — investigate "
              "before trusting this run", file=sys.stderr)

    if not args.index_only:
        print("[run] enriching + scoring …")
        enrich.enrich_run(run_dir, golden, params)
        print(f"[run] report: {run_dir / 'report.md'}")

    print(f"[run] done in {run_record['wall_s_total']}s -> {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
