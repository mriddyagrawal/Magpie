"""One-command machine prep for the eval harness (and Magpie dev generally).

    just prepare-eval-harness            # binaries + models this machine will use
    just prepare-eval-harness --check    # report what is present/missing, change nothing

Steps (each idempotent, each skippable):
  1. qdrant binary        -> scripts/download_qdrant.py (per-platform)
  2. llama-server binary  -> src.tools.install_llama_server (per-platform,
                             LLAMA_SERVER_GPU env picks metal/cuda/cpu)
  3. model prefetch       -> the SAME registries the app uses, never
                             duplicated URLs:
                               - col model via src.stage1_fast.device (auto =
                                 what THIS machine will load; --col overrides)
                               - answer LLM via src.inference.profiles /
                                 model_downloader (--llm lfm[,gemma])
  4. claude CLI check     -> required for the judge + skills (warn, not fail)

Everything lands where lazy first-run downloads would put it anyway
(<app-data>/cache, <app-data>/bin), so runs after prep hit only caches.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval_harness" / "harness"))

import os

import envctl  # noqa: E402  (harness path inserted above)

# Point HF at the shared app cache BEFORE any huggingface import - this is
# where runs (and the app) put models; without it, --check looks at
# ~/.cache/huggingface and wrongly reports everything missing.
for _k in ("HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE"):
    os.environ.setdefault(_k, str(
        envctl.SHARED_MODEL_CACHE / "hub" if _k == "HF_HUB_CACHE"
        else envctl.SHARED_MODEL_CACHE))


def _hr(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(0, 60 - len(title)))


def step_qdrant(check: bool) -> bool:
    _hr("qdrant binary")
    import backend
    try:
        p = backend.qdrant_binary()
        print(f"present: {p}")
        return True
    except RuntimeError as e:
        if check:
            print(f"MISSING: {e}")
            return False
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "download_qdrant.py")])
    return r.returncode == 0


def step_llama(check: bool) -> bool:
    _hr("llama-server binary")
    p = envctl.SHARED_LLAMA_SERVER
    if p.exists():
        print(f"present: {p}")
        return True
    if check:
        print(f"MISSING: {p} - run `just install-llama-server`")
        return False
    r = subprocess.run([sys.executable, "-m", "src.tools.install_llama_server"], cwd=REPO)
    return r.returncode == 0


def step_col_model(check: bool, col: str) -> bool:
    _hr(f"col model (visual retriever) - selection: {col}")
    from src.stage1_fast import device as dev
    if col == "auto":
        cfg = dev.detect_device()          # ~10-15s first time (torch probe)
        model_id, base_id = cfg.model_id, (
            dev.COLQWEN_BASE_ID if cfg.model_family == "colqwen2_5" else dev.COLSMOL_BASE_ID
        )
        print(f"machine resolution: device={cfg.device} -> {model_id}")
    elif col == "qwen":
        model_id, base_id = dev.COLQWEN_MODEL_ID, dev.COLQWEN_BASE_ID
    else:
        model_id, base_id = dev.COLSMOL_MODEL_ID, dev.COLSMOL_BASE_ID
    from huggingface_hub import snapshot_download
    ok = True
    for repo in (model_id, base_id):
        try:
            path = snapshot_download(repo, local_files_only=True)
            print(f"present: {repo} ({path})")
        except Exception:
            if check:
                print(f"MISSING: {repo}")
                ok = False
                continue
            print(f"downloading {repo} …")
            snapshot_download(repo)
    return ok


def step_llm(check: bool, llms: list[str]) -> bool:
    _hr(f"answer LLM(s): {', '.join(llms)}")
    from src.inference import profiles
    from src.inference.model_downloader import ensure_model
    ok = True
    for name in llms:
        if name == "lfm":
            repo, quant = profiles.DEFAULT_REPO, profiles.DEFAULT_QUANT
        elif name == "gemma":
            # repo + filename convention already known to model_downloader
            repo, quant = "unsloth/gemma-4-E4B-it-GGUF", "Q4_K_M"
        else:
            print(f"unknown --llm {name!r} (valid: lfm, gemma)")
            ok = False
            continue
        if check:
            # ensure_model downloads on miss; in check mode just report the
            # cache state via a local-only snapshot probe.
            from huggingface_hub import snapshot_download

            from src.drift.pins import model_revision
            try:
                snapshot_download(repo, local_files_only=True, revision=model_revision(repo),
                                  allow_patterns=[f"*{quant}*"])
                print(f"present: {repo} [{quant}]")
            except Exception:
                print(f"MISSING: {repo} [{quant}]")
                ok = False
            continue
        print(f"ensuring {repo} [{quant}] …")
        path = ensure_model(repo, quant)
        print(f"present: {path}")
    return ok


def step_claude(check: bool) -> bool:  # noqa: ARG001 - same in both modes
    _hr("claude CLI (judge + skills)")
    p = shutil.which("claude")
    if p:
        print(f"present: {p}")
        return True
    print("MISSING: `claude` not on PATH. The harness runs without it, but "
          "the judge and the /magpie-eval skills need it. Install Claude "
          "Code and log in.")
    return False


def step_provenance(check: bool) -> bool:
    """Pre-warm the drift-guard fingerprint (src/drift/provenance.py): the
    first fingerprint on a machine hashes ~3 GB of GGUF + mmproj. Doing it
    here means no eval run ever pays those 10-20 s, and the pins are checked
    once at prep time. Warn-only: a mismatch is reported, never fatal."""
    _hr("drift fingerprint")
    try:
        from src.drift import pins, provenance

        prov = provenance.runtime_fingerprint(hash_models=not check)
        summ = provenance.summary(prov)
        print(f"  fingerprint {summ['fingerprint']}: llama-server {summ['llama_server']}, "
              f"model {summ['model']}, col {summ['col_model']}")
        for m in pins.check_pins(prov):
            print(f"  WARN {m['component']}: installed {m['installed']} != pinned {m['pinned']}")
        if check:
            print("  (hash cache not warmed in --check mode)")
        return True
    except Exception as e:  # noqa: BLE001 - prep must not fail on the guard
        print(f"  skipped: {e}")
        return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    ap.add_argument("--col", choices=("auto", "qwen", "smol"), default="auto")
    ap.add_argument("--llm", default="lfm",
                    help="comma list: lfm (default), gemma (large - opt-in)")
    args = ap.parse_args()
    llms = [s.strip() for s in args.llm.split(",") if s.strip()]

    results = {
        "qdrant": step_qdrant(args.check),
        "llama-server": step_llama(args.check),
        "col model": step_col_model(args.check, args.col),
        "answer llm": step_llm(args.check, llms),
        "claude cli": step_claude(args.check),
        "drift fingerprint": step_provenance(args.check),
    }
    _hr("summary")
    for k, v in results.items():
        print(f"  {'OK     ' if v else 'MISSING'} {k}")
    hard = [k for k, v in results.items() if not v and k != "claude cli"]
    if hard:
        sys.exit(f"prepare-eval-harness: incomplete ({', '.join(hard)})"
                 + ("" if not args.check else " - rerun without --check to install"))
    print("\nready. next: eval_harness/HOW_TO_RUN_EVALS.md")


if __name__ == "__main__":
    main()
