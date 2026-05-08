"""Build the magpie-sidecar binary using PyInstaller.

Must be run on the target platform — PyInstaller cannot cross-compile.
Run from the project root:

    uv run python scripts/build_sidecar.py

Output (placed in frontend/src-tauri/binaries/):
    Windows : magpie-sidecar-x86_64-pc-windows-msvc.exe
    macOS ARM: magpie-sidecar-aarch64-apple-darwin
    macOS x86: magpie-sidecar-x86_64-apple-darwin
    Linux    : magpie-sidecar-x86_64-unknown-linux-gnu

Tauri's externalBin strips the target triple at bundle time, so the
binary name in tauri.conf.json stays just "binaries/magpie-sidecar".
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
BINARIES_DIR = ROOT / "frontend" / "src-tauri" / "binaries"


def target_triple() -> str:
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows":
        return "x86_64-pc-windows-msvc"
    if system == "Darwin":
        return "aarch64-apple-darwin" if machine == "arm64" else "x86_64-apple-darwin"
    if system == "Linux":
        return "x86_64-unknown-linux-gnu"

    raise RuntimeError(f"unsupported platform: {system} {machine}")


def main() -> None:
    triple = target_triple()
    is_windows = platform.system() == "Windows"
    output_name = f"magpie-sidecar-{triple}" + (".exe" if is_windows else "")

    print(f"Building magpie-sidecar for {triple}...")
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)

    # PyInstaller --add-data separator is ; on Windows, : elsewhere
    sep = ";" if is_windows else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "src/server.py",
        "--name", "magpie-sidecar",
        "--onefile",
        "--noconsole",
        "--noconfirm",
        # Heavy packages that use dynamic imports or include non-Python assets
        "--collect-all", "sentence_transformers",
        "--collect-all", "fastembed",
        "--collect-all", "qdrant_client",
        "--collect-all", "pymupdf",
        # Uvicorn loads its protocol/loop implementations dynamically
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan.on",
        # src.* modules are lazy-imported inside endpoint functions
        "--hidden-import", "src.pipeline",
        "--hidden-import", "src.content",
        "--hidden-import", "src.stage2.db",
        "--hidden-import", "src.stage2",
        "--hidden-import", "src.stage2.__main__",
        "--hidden-import", "src.stage1",
        "--hidden-import", "src.manifest",
        "--hidden-import", "src.ingest",
        "--hidden-import", "src.ingest.walker",
        "--hidden-import", "src.ingest.common",
        "--hidden-import", "src.ingest.ignore",
        "--hidden-import", "src.ingest.csv_stats",
        "--hidden-import", "src.ingest.tier1",
        "--hidden-import", "src.router",
        # Local LLM via llama-server subprocess. The pool / profiles / HTTP
        # client are lazy-imported by src.llm only when LLM_PROVIDER=local,
        # so PyInstaller's static analysis doesn't see them.
        "--hidden-import", "src.inference",
        "--hidden-import", "src.inference.local_llm",
        "--hidden-import", "src.inference.llama_server_pool",
        "--hidden-import", "src.inference.llama_server_binary",
        "--hidden-import", "src.inference.profiles",
        "--hidden-import", "src.inference.model_downloader",
        "--hidden-import", "src.inference.chat_template",
        # Indexing rules + backup are reached via /settings and /backup
        # endpoints, also lazy.
        "--hidden-import", "src.config",
        "--hidden-import", "src.config.indexing_rules",
        "--hidden-import", "src.backup",
        # Bundle the src package so relative imports resolve at runtime
        "--add-data", f"src{sep}src",
        # Packages that call importlib.metadata.version() on themselves at import
        # time — PyInstaller strips .dist-info by default, so the lookup crashes.
        # NOTE: pydantic-ai metapackage was replaced by pydantic-ai-slim in
        # bundle-trim PR-B (see pyproject.toml). The import path is still
        # `pydantic_ai`, but the DISTRIBUTION name is now `pydantic_ai_slim`,
        # so --copy-metadata must reference the new name.
        "--copy-metadata", "genai_prices",
        "--copy-metadata", "pydantic_ai_slim",
        "--copy-metadata", "pydantic_graph",
        # ── Tier 1 excludes (high-confidence, ~80–100 MB savings) ────────────
        # These submodules are well-isolated; PyTorch never imports them
        # internally unless specific code paths run (multi-node training,
        # ONNX export, profiling, training APIs) — none of which Magpie does.
        # Plan #10 PR-E. Tier 2 (torch.fx, torch._dynamo, sympy, mpmath) goes
        # in ONE AT A TIME with smoke tests; Tier 3 (transformers.models.<unused>)
        # is deferred. See `Plans/Packaging/Implementation Plan.md` §5.
        "--exclude-module", "torch.distributed",       # multi-node training
        "--exclude-module", "torch.onnx",              # we don't export
        "--exclude-module", "torch.profiler",          # debug-only
        "--exclude-module", "torch.tensorboard",       # tensorboard logging
        "--exclude-module", "torch.optim",             # we never train
        "--exclude-module", "torch.autograd.profiler", # same family
        "--exclude-module", "IPython",                 # debug REPL (defensive)
        "--exclude-module", "babel",                   # i18n; we don't translate
        # ── Tier 2 candidates (~80–100 MB more, MEDIUM confidence) ──────────
        # UNCOMMENT ONE AT A TIME, rebuild, smoke-test (ingest tiny corpus →
        # run query → exercise T4). If anything ImportErrors at runtime,
        # leave the line commented. PyTorch occasionally lazy-imports these
        # in unexpected places.
        # "--exclude-module", "torch.fx",            # symbolic graph tracing
        # "--exclude-module", "torch._dynamo",       # torch.compile machinery
        # "--exclude-module", "sympy",               # torch's symbolic shapes (~29 MB)
        # "--exclude-module", "mpmath",              # transitive sympy
        # ── Tier 3 (transformers.models.<unused arch>) ─────────────────────
        # Generated by `python scripts/list_unused_transformers_models.py`.
        # That script imports transformers, walks transformers/models/, and
        # subtracts an ALLOWLIST of architectures we know are needed by
        # colpali_engine (paligemma, qwen2_vl, gemma, siglip, ...) and
        # sentence-transformers (bert, mpnet, ...). Everything else is
        # printed as `--exclude-module transformers.models.X` lines.
        #
        # Estimated saving: ~150 architectures × 3-5 MB each = ~450-750 MB.
        # This is much larger than the original brainstorm estimate (which
        # assumed Tier 3 was skipped). Web research 2026-05-08 showed
        # transformers does dynamic-by-string-name loading, so STATIC
        # analysis bundles every architecture even though only ~12 ever
        # load at runtime.
        #
        # Validation (do this BEFORE shipping a Tier-3 build):
        #   1. Run scripts/list_unused_transformers_models.py, paste output here
        #   2. Rebuild
        #   3. Smoke test EVERY tier (T0 text, T1 code, T2 PDF, T3 vision PDF,
        #      T4 ColPali). Each tier exercises different transformers loads.
        #   4. If anything ImportErrors at runtime → identify the missing
        #      architecture, ADD it to ALLOWLIST in the helper script, regen.
        #
        # Tier 3 lines DELIBERATELY NOT included here yet — generated on
        # demand to avoid stale lists that drift as transformers releases
        # new architectures. Run the script once on each release branch.
    ]

    subprocess.run(cmd, cwd=ROOT, check=True)

    src_exe = ROOT / "dist" / ("magpie-sidecar.exe" if is_windows else "magpie-sidecar")
    dst_exe = BINARIES_DIR / output_name

    if dst_exe.exists():
        dst_exe.unlink()
    shutil.move(str(src_exe), dst_exe)

    size_mb = dst_exe.stat().st_size / 1024 / 1024
    print(f"\nDone: {dst_exe}")
    print(f"Size: {size_mb:.0f} MB")
    print(f"\nNext: pnpm tauri build")


if __name__ == "__main__":
    main()
