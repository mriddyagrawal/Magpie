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


def _warn_if_bundled_key_missing() -> None:
    """Bundled OpenRouter key powers the in-app Cloud toggle for end users.

    Lives at `src/config/bundled_key.txt` (gitignored). When present, it gets
    pulled into the bundle automatically via `--add-data src:src` below, so
    `src/config/secrets.py:_bundled_key()` finds it at runtime and seeds
    `secrets.json` on first launch. When MISSING, the bundled binary still
    builds and runs fine — but the Cloud toggle in Settings will silently
    401 because there's no key for it to use.

    Print a clear warning so the dev sees this in build output. Don't fail
    the build; dev iteration shouldn't require the key.

    Plan #40 tracks the post-beta migration to a hosted backend that
    replaces this bundled-key approach.
    """
    key_path = ROOT / "src" / "config" / "bundled_key.txt"
    if key_path.exists() and key_path.read_text(encoding="utf-8").strip():
        print(f"  bundled_key.txt present — Cloud toggle will work in this build")
    else:
        print(f"  ⚠  bundled_key.txt MISSING — Cloud toggle will 401 in this build")
        print(f"  ⚠  copy src/config/bundled_key.txt.example → bundled_key.txt and")
        print(f"  ⚠  paste the OpenRouter key. Acceptable for dev builds; release")
        print(f"  ⚠  builds need this populated before tagging.")


def main() -> None:
    triple = target_triple()
    is_windows = platform.system() == "Windows"
    output_name = f"magpie-sidecar-{triple}" + (".exe" if is_windows else "")

    print(f"Building magpie-sidecar for {triple}...")
    _warn_if_bundled_key_missing()
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
        # ── Tier 2 (medium confidence, ~80–100 MB more) ─────────────────────
        # PyTorch occasionally lazy-imports these in unexpected places, so
        # they CAN break runtime if a code path we don't notice triggers
        # them. The CI smoke-test step in .github/workflows/build.yml
        # (`Smoke-test bundled sidecar`) launches the bundled binary and
        # hits /health on every push — if any of these break the import
        # graph, that step fails immediately on whichever platform broke.
        # If you see CI red on a specific platform after a Tier 2 change,
        # comment that one out and reopen as a narrow workaround.
        "--exclude-module", "torch.fx",                # symbolic graph tracing
        "--exclude-module", "torch._dynamo",           # torch.compile machinery
        "--exclude-module", "sympy",                   # torch's symbolic shapes (~29 MB)
        "--exclude-module", "mpmath",                  # transitive sympy
        # ── Tier 3 (transformers.models.<unused arch>) — NOT IN CI ─────────
        # Tier 3 excludes interact with HuggingFace's `AutoModel.from_pretrained`
        # dynamic-string-name dispatch: a missing architecture does NOT break
        # bundle import (so /health stays green) — it ImportErrors only when
        # someone runs a query that loads that specific arch. Catching this
        # in CI would require actually loading ColPali / sentence-transformers
        # models (~5 GB downloads per matrix job) which is wasteful, slow,
        # and fragile in CI runners.
        #
        # DECISION (2026-05-08): Tier 3 is validated MANUALLY ON EACH TARGET
        # PLATFORM (macOS arm64, macOS x86_64, Linux x86_64, Windows x86_64)
        # before tagging a release, never in CI. The /health smoke test in
        # build.yml deliberately covers T1+T2 only. Do not add T3 flags to
        # this list as part of branch/PR work — only add them on a release-
        # cutting machine after the per-platform validation flow below.
        #
        # Per-platform matters because each matrix job produces its own
        # PyInstaller bundle, and a missing arch can ImportError on any one
        # of them at query time. In practice this means: at least one team
        # member on Mac, one on Linux, one on Windows runs the manual flow.
        #
        # Generator: `python scripts/list_unused_transformers_models.py`.
        # That script imports transformers, walks transformers/models/, and
        # subtracts an ALLOWLIST of architectures we know are needed by
        # colpali_engine (paligemma, qwen2_vl, gemma, siglip, ...) and
        # sentence-transformers (bert, mpnet, ...). Everything else is
        # printed as `--exclude-module transformers.models.X` lines.
        #
        # Estimated saving: ~150 architectures × 3-5 MB each = ~450-750 MB.
        #
        # Manual release-cutting validation (run on each target platform):
        #   1. Run scripts/list_unused_transformers_models.py, paste output here
        #   2. Rebuild (uv run python scripts/build_sidecar.py)
        #   3. End-to-end smoke EVERY tier (T0 text, T1 code, T2 PDF,
        #      T3 vision PDF, T4 ColPali) on a real corpus.
        #   4. If anything ImportErrors at runtime → identify the missing
        #      architecture, ADD it to ALLOWLIST in the helper script, regen.
        #   5. Only after green on every platform: commit T3 lines, tag release.
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
