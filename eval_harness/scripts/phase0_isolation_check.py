"""Phase 0 exit test (PLAN.md §7): prove full isolation with a real backend.

Boots the backend against a scratch data dir, indexes a tiny throwaway corpus,
answers one hardcoded question through the real pipeline, and asserts:

  1. WRITE isolation — the real app dir's mutable state is byte-identical
     before/after (content fingerprint; cache/bin/logs excluded as shared-read).
  2. READ isolation — the scratch dir actually got populated (manifest,
     settings, qdrant collections); a run that silently read the real index
     would pass check 1 while measuring the wrong thing.
  3. ZERO downloads — shared model cache file-count and byte-total unchanged
     (HF_HUB_OFFLINE=1 doing its job).
  4. CONTROLLED ENV — the worker's resolved provider/temp/solo-margin match
     the config, not the repo .env (which deliberately conflicts on this
     machine: it sets a cloud provider and nonzero temperature).

Run:  uv run python eval_harness/scripts/phase0_isolation_check.py
Exit: 0 = Phase 0 exit criterion met; nonzero = isolation broken (details on
stderr). Wall-clock: a few minutes (spawns llama-server, loads the 3B).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harness"))

import backend  # noqa: E402
import envctl  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    t_start = time.monotonic()
    params = {
        "provider": "local",
        "temperature": 0.0,
        "solo_margin": 2.0,
        "top_k": 3,
        "rewrite": False,          # keep the check fast: one LLM call, not two
        "fast_search": False,      # tiny corpus is text -> summary tier only
        "index_fast_tier": False,
        "index_summary_tier": True,
    }

    run_dir = Path(tempfile.mkdtemp(prefix="magpie-eval-phase0-"))
    appdata = run_dir / "appdata"
    corpus = run_dir / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "aurora_project.md").write_text(
        "# Project Aurora status\n\n"
        "Project Aurora is an internal test initiative. The project lead is "
        "Dr. Elena Vasquez. The budget for fiscal 2026 is 1.2 million dollars. "
        "The kickoff meeting happened in Reykjavik in March.\n",
        encoding="utf-8",
    )
    (corpus / "unrelated_notes.md").write_text(
        "# Grocery notes\n\nBuy oat milk, rye bread, and coffee beans. "
        "The farmers market opens Saturdays at 8am.\n",
        encoding="utf-8",
    )

    print(f"phase0: run dir {run_dir}")
    print(f"phase0: real app dir {envctl.REAL_APP_DATA} (must stay untouched)")

    fp_app_before = envctl.appdata_fingerprint()
    fp_cache_before = envctl.cache_fingerprint()
    print(f"phase0: cache before = {fp_cache_before}")

    ports = envctl.Ports.for_slot(0)
    env = envctl.build_env(appdata, params, ports)

    qdrant = backend.QdrantInstance(
        storage_dir=run_dir / "qdrant",
        http_port=ports.qdrant_http,
        grpc_port=ports.qdrant_grpc,
        log_path=run_dir / "qdrant.log",
    )

    ok = True
    try:
        qdrant.start()
        print("phase0: qdrant up")

        boot = backend.run_worker("boot", run_dir, env, {"params": params}, timeout_s=300)
        print(f"phase0: boot = {json.dumps({k: boot[k] for k in ('app_data_dir', 'provider', 'resolved_ctx_size', 'text_profile')}, indent=2)}")
        # Path.resolve() both sides: macOS /var is a symlink to /private/var
        # and the backend realpaths its data dir.
        check("boot: scratch app dir",
              Path(boot["app_data_dir"]).resolve() == appdata.resolve(),
              boot["app_data_dir"])
        check("boot: shared HF cache", boot["hf_home"] == str(envctl.SHARED_MODEL_CACHE))
        check("boot: offline locked", boot["hf_hub_offline"] == "1")
        check("boot: provider forced local (repo .env conflicts)", boot["provider"] == "local", boot["provider"])
        check("boot: run-private qdrant", boot["qdrant_endpoint"].endswith(str(ports.qdrant_http)))
        env_snap = boot.get("resolved_env", {})
        check("boot: temp pinned 0 (env)", env_snap.get("LOCAL_TEMPERATURE") == "0.0",
              str(env_snap.get("LOCAL_TEMPERATURE")))
        check("boot: solo margin pinned (absent from .env)", env_snap.get("LOCAL_SOLO_MARGIN") == "2.0",
              str(env_snap.get("LOCAL_SOLO_MARGIN")))

        idx = backend.run_worker("index", run_dir, env,
                                 {"params": params, "corpus_dir": str(corpus)},
                                 timeout_s=1800)
        n_manifest = len(idx.get("manifest") or {})
        print(f"phase0: index done in {idx['wall_s']}s; manifest entries: {n_manifest}")
        check("index: scratch manifest populated", n_manifest > 0 and Path(idx["manifest_path"]).exists(),
              f"{n_manifest} entries at {idx['manifest_path']}")

        ans = backend.run_worker(
            "answer", run_dir, env,
            {
                "params": params,
                "questions": [{"id": "phase0-q1", "question": "Who is the project lead of Project Aurora?"}],
                "answers_jsonl": str(run_dir / "answers.jsonl"),
            },
            timeout_s=1800,
        )
        rows = [json.loads(l) for l in Path(ans["answers_jsonl"]).read_text(encoding="utf-8").splitlines()]
        row = rows[0]
        answered = (row.get("error") is None) and ("vasquez" in (row.get("answer") or "").lower())
        print(f"phase0: answer = {json.dumps(row.get('answer', ''))[:200]}")
        print(f"phase0: retrieved = {[r['path'].rsplit('/', 1)[-1] for r in row.get('retrieved', [])]}")
        check("answer: real pipeline answered from scratch index", answered,
              row.get("error") or (row.get("answer") or "")[:80])
        check("answer: cites the planted file", any("aurora_project" in c for c in row.get("cited", [])),
              str(row.get("cited")))
    except Exception as e:  # noqa: BLE001
        check("run completed without harness exception", False, f"{type(e).__name__}: {e}")
        ok = False
    finally:
        qdrant.stop()
        print("phase0: qdrant stopped")

    fp_app_after = envctl.appdata_fingerprint()
    fp_cache_after = envctl.cache_fingerprint()
    check("WRITE isolation: real app dir untouched", fp_app_before == fp_app_after)
    check("ZERO downloads: cache unchanged", fp_cache_before == fp_cache_after,
          f"before={fp_cache_before} after={fp_cache_after}")
    check("READ isolation: scratch qdrant storage populated",
          any((run_dir / "qdrant").rglob("*")), "")

    failures = [c for c in CHECKS if not c[1]]
    print(f"\nphase0: {len(CHECKS) - len(failures)}/{len(CHECKS)} checks passed "
          f"in {time.monotonic() - t_start:.0f}s")
    if failures:
        print("phase0: FAILED checks:", file=sys.stderr)
        for name, _, detail in failures:
            print(f"  - {name} {detail}", file=sys.stderr)
        print(f"phase0: artifacts kept for debugging at {run_dir}", file=sys.stderr)
        return 1
    shutil.rmtree(run_dir, ignore_errors=True)
    print("phase0: PASS — Phase 0 exit criterion met; scratch cleaned up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
