"""One-time cache warm for the visual (fast) tier — then verify offline.

Why this exists: the shared app cache holds the ColQwen weights, but the
colqwen2.5-v0.2 PROCESSOR resolves its tokenizer from the Qwen base repo,
which the app auto-downloads online on first visual-tier use and which was
never cached on this machine (first observed: eval smoke-01, index phase,
OSError offline). Eval runs are offline by contract (HF_HUB_OFFLINE=1), so
the miss is fatal there. This script does the download ONCE, into the same
shared cache the app uses, by running the app's own loader — then re-runs
the load fully offline to prove eval runs will succeed.

Run:  uv run python eval_harness/scripts/warm_model_cache.py
Network: yes (this script only — eval runs stay offline).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harness"))

import envctl  # noqa: E402

REPO = HERE.parents[1]

LOADER_SNIPPET = r"""
import sys
sys.path.insert(0, {repo!r})
from src.stage1_fast.model import get_model
model, processor, cfg = get_model()
print("LOADED", cfg.model_id, type(model).__name__, type(processor).__name__)
"""


def run_load(offline: bool) -> int:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "MAGPIE_DATA_DIR": "/tmp/magpie-eval-cache-warm-scratch",
        "HF_HOME": str(envctl.SHARED_MODEL_CACHE),
        "HF_HUB_CACHE": str(envctl.SHARED_MODEL_CACHE / "hub"),
        "TRANSFORMERS_CACHE": str(envctl.SHARED_MODEL_CACHE),
        "FASTEMBED_CACHE_PATH": str(envctl.SHARED_MODEL_CACHE / "fastembed"),
    }
    if offline:
        env["HF_HUB_OFFLINE"] = "1"
    code = LOADER_SNIPPET.format(repo=str(REPO))
    proc = subprocess.run([sys.executable, "-c", code], env=env, cwd=str(REPO))
    return proc.returncode


def main() -> int:
    before = envctl.cache_fingerprint()
    print(f"warm: cache before = {before}")
    print("warm: ONLINE load via the app's own loader (downloads any missing "
          "processor/tokenizer files into the shared cache) …")
    rc = run_load(offline=False)
    if rc != 0:
        print("warm: online load FAILED — cannot warm the cache", file=sys.stderr)
        return rc
    mid = envctl.cache_fingerprint()
    print(f"warm: cache after online load = {mid} "
          f"(+{mid['files'] - before['files']} files, "
          f"+{(mid['bytes'] - before['bytes']) / 1e6:.1f} MB)")
    print("warm: verifying fully OFFLINE load …")
    rc = run_load(offline=True)
    if rc != 0:
        print("warm: offline verify FAILED — eval runs would still break",
              file=sys.stderr)
        return rc
    after = envctl.cache_fingerprint()
    if after != mid:
        print(f"warm: WARNING offline load changed the cache?! {mid} -> {after}",
              file=sys.stderr)
        return 2
    print("warm: PASS — visual tier loads offline; eval runs are unblocked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
