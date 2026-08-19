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
        # Linux ARM (Raspberry Pi, Asahi Linux on Apple silicon, AWS Graviton, …)
        # produces `aarch64` from platform.machine(); some distros report `arm64`.
        # Without this branch we'd label an ARM binary as x86_64 and Tauri's
        # externalBin would refuse it at bundle time.
        if machine in ("aarch64", "arm64"):
            return "aarch64-unknown-linux-gnu"
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
    # Stick to ASCII in print() — Windows runners default to a cp1252 stdout
    # encoding, and any non-ASCII (emoji, em-dash, arrows) raises
    # UnicodeEncodeError that crashes the build before PyInstaller even
    # starts. This bit only the MISSING branch, so it never reproduced on a
    # dev box that had the key file: the `present` line's em-dash happens to
    # be cp1252-encodable while `⚠` is not. Net effect was that Windows CI
    # had never once produced a build. Keep every print() here 7-bit clean.
    key_path = ROOT / "src" / "config" / "bundled_key.txt"
    if key_path.exists() and key_path.read_text(encoding="utf-8").strip():
        print("  bundled_key.txt present - Cloud toggle will work in this build")
    else:
        print("  WARNING: bundled_key.txt MISSING - Cloud toggle will 401 in this build")
        print("  WARNING: copy src/config/bundled_key.txt.example -> bundled_key.txt")
        print("  WARNING: and paste the OpenRouter key. Acceptable for dev builds;")
        print("  WARNING: release builds need this populated before tagging.")


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
        # Heavy packages that use dynamic imports or include non-Python assets.
        #
        # `torch` is the most dynamically-imported library in our stack:
        # transformers / sentence-transformers / colpali-engine / pydantic-ai
        # all reach into torch submodules (distributed.rpc, autograd.profiler,
        # _dynamo, fx, ...) at module-load time of architectures we don't
        # statically reference. Plan #10 §5's Tier 1/2 static-analysis
        # exclude approach has produced 4 separate runtime regressions
        # tonight (torch.distributed, torch.autograd.profiler, RpcBackendOptions
        # registration, multiprocessing.spawn). Going `--collect-all torch`
        # to make the bundle "all-in" on torch — adds ~300-400 MB but
        # eliminates the entire class of "module excluded but transitively
        # needed" regression. Will revisit once a CI /query smoke test
        # exercises real reranker + answer paths and can gate exclusions.
        "--collect-all", "torch",
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
        # ── Excludes ─────────────────────────────────────────────────────────
        #
        # NOTE 2026-05-09: ALL torch-related excludes (Tier 1 + Tier 2 from
        # Plan #10 §5) have been REMOVED. Decision: ship all of torch / sympy /
        # mpmath until we have a CI /query smoke test that exercises the full
        # pipeline (rerank, answer, ColPali) and can prove which submodules
        # are genuinely unreachable.
        #
        # Why: tonight's packaging smoke produced four separate runtime
        # regressions from supposedly "high-confidence Tier 1" excludes:
        #   - `torch.distributed`         → ModuleNotFoundError on first query
        #                                   (sentence-transformers reaches in)
        #   - `torch.autograd.profiler`   → SIDECAR FAILS TO START
        #                                   (torch.autograd/__init__.py:601
        #                                   does `from . import profiler`
        #                                   unconditionally)
        #   - `torch.profiler`            → preemptive removal (sibling of above)
        #   - RpcBackendOptions conflict  → required a separate runtime stub
        #                                   in src/server.py (42bd7d4)
        #
        # The static-analysis approach to picking excludes (Plan #10 §5)
        # missed real runtime dependencies in transformers's load chain.
        # Until we have CI that actually runs `/query` against a small
        # corpus, every "this submodule is well-isolated" claim is a
        # guess. Better to ship a fat bundle that works than a thin
        # bundle that crashes.
        #
        # Bundle size impact: +300-500 MB. Acceptable given the alternative
        # is "indeterminate runtime regressions, debugged by user reports."
        # Re-enable selective excludes when:
        #   1. `Add CI smoke step that exercises a real /query` (todo #11) lands
        #   2. The smoke test runs on a real corpus and exercises rerank +
        #      answer paths (i.e., loads sentence-transformers + transformers)
        #   3. THEN, with empirical proof, narrow excludes can come back
        #
        # Kept excludes — non-torch, truly unrelated:
        "--exclude-module", "IPython",                 # debug REPL (defensive)
        "--exclude-module", "babel",                   # i18n; we don't translate
        # ── transformers.models.<unused arch> excludes — RELEASE-CUT ONLY ───
        #
        # NOT included in this build. Documented here as the release-time
        # optimization path, applied manually before tagging — never in CI.
        #
        # The mechanism: HuggingFace's `AutoModel.from_pretrained` does
        # dynamic-string-name dispatch (`AutoModel.from_pretrained("bert-...")`
        # imports `transformers.models.bert.*` at call time). Excluding an
        # architecture does NOT break bundle import (so /healthz stays green)
        # — it ImportErrors only when a query loads that specific arch. So
        # CI smoke can't catch a wrong exclude here without downloading
        # ~5 GB of HF models per matrix job, which is wasteful + fragile.
        #
        # 2026-05-09 lessons: the `torch.*` Tier 1/2 excludes (originally
        # alongside this Tier 3 strategy in Plan #10 §5) all turned out to
        # be wrong — they were "broken at module-import time" rather than
        # "broken at first query," and produced four runtime regressions in
        # one packaging session. Those are gone (we --collect-all torch now).
        # This transformers-architecture exclude path is DIFFERENT: the failure
        # mode is genuinely lazy, the validation is genuinely expensive, and
        # the saving is large (~450-750 MB). Stays as a release-cut tool.
        #
        # Validation flow (run on EACH target platform before tagging):
        #   1. Run `scripts/list_unused_transformers_models.py` → prints
        #      candidate `--exclude-module transformers.models.X` lines.
        #      The script's ALLOWLIST keeps architectures known to be needed
        #      by colpali_engine (paligemma, qwen2_vl, gemma, siglip, ...) and
        #      sentence-transformers (bert, mpnet, ...).
        #   2. Paste output into the cmd list above (in this same block).
        #   3. Rebuild: `uv run python scripts/build_sidecar.py`.
        #   4. End-to-end smoke on a real corpus, exercising every tier:
        #      T0 plain text, T1 CSV/code, T2 PDF text, T3 vision-PDF,
        #      T4 ColPali image.
        #   5. If anything ImportErrors at runtime → identify the missing
        #      architecture from the traceback, ADD it to the ALLOWLIST in
        #      the helper script, regen, retry.
        #   6. Repeat for every target platform (each PyInstaller matrix job
        #      produces its own bundle; a missing arch can break on any of
        #      them independently).
        #   7. Only after green on every platform: commit the exclude lines
        #      to this file, tag release.
        #
        # Estimated saving: ~150 architectures × 3-5 MB each = ~450-750 MB
        # off the bundle. By far the biggest single optimization remaining.
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
