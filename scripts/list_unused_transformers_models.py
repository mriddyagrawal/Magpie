"""Tier 3 exclude-list generator for `scripts/build_sidecar.py`.

Plan #10 P10-2 Tier 3 (originally deferred — re-opened after web research
showed the actual savings are way larger than the brainstorm estimated).

The HuggingFace `transformers` library bundles ~200 model architectures
under `transformers/models/<arch>/`. PyInstaller's static analyzer pulls
EVERY one of them into the bundle by default, even though our actual
runtime path only ever loads a small subset (ColPali's 12-or-so vision-
language families + sentence-transformers' BERT/MPNet for embeddings).

This script prints `--exclude-module transformers.models.<arch>` lines
for every architecture that is NOT in the allowlist below. Pipe the
output into your build flags or copy directly into build_sidecar.py.

Allowlist rationale:
  - Vision-language families needed by colpali-engine ([web research,
    2026-05-08]: ColPali / ColQwen2 / ColQwen2.5 / ColQwen3 / ColQwen3_5 /
    ColGemma3 / ColIdefics3 / ColModernVBert / ColQwen2_5_Omni)
  - Their underlying backbones (paligemma, qwen2_vl, qwen2_5_vl, gemma,
    gemma2, gemma3, qwen2, qwen2_5, qwen3, qwen3_5, qwen2_5_omni, siglip,
    idefics3, modernvbert)
  - Common sentence-transformers backbones (bert, distilbert, mpnet,
    roberta, xlm_roberta, deberta_v2)
  - Tokenizer-compat for HuggingFace dynamic loading machinery (auto, llama,
    t5 — broadly referenced by tokenizer factory code)
  - `auto` — the AutoModel / AutoConfig dispatch tables. NEVER exclude.

Usage:
    UV_PROJECT_ENVIRONMENT=/path/to/venv uv run python scripts/list_unused_transformers_models.py
    # → prints ~150 --exclude-module flags

Validation pattern:
    1. Run this script, capture output.
    2. Paste the lines into build_sidecar.py (or pass via env var).
    3. Run `uv run python scripts/build_sidecar.py`.
    4. Smoke-test the bundle end-to-end:
       - Ingest tiny corpus (txt + pdf + image) → run a query
       - Force T4: drop a scanned PDF in the corpus, query against it
       - Confirm ColPali loads without ImportError
    5. If anything ImportErrors → identify which architecture, REMOVE it
       from this script's exclude list (move to allowlist), regenerate.
"""

from __future__ import annotations

import sys
from pathlib import Path


# Architectures we MUST keep. Anything not in this set goes into excludes.
# Conservative — it's safer to over-include than to under-include and break
# at runtime. Refine downward by running smoke tests with a leaner allowlist.
ALLOWLIST: frozenset[str] = frozenset({
    # Auto-loading machinery — NEVER exclude
    "auto",

    # ColPali / ColQwen / ColGemma / etc. backbones (per colpali_engine 0.3.x)
    "paligemma",
    "qwen2", "qwen2_5", "qwen3", "qwen3_5",
    "qwen2_vl", "qwen2_5_vl", "qwen2_5_omni",
    "gemma", "gemma2", "gemma3",
    "siglip",
    "idefics3",
    "modernvbert",

    # Sentence-transformers / generic-embedder backbones commonly used by
    # `vidore/colqwen2.5-v0.2`, `bge-large`, `all-mpnet-base-v2`, etc.
    "bert", "distilbert", "mpnet", "roberta", "xlm_roberta", "deberta_v2",

    # Tokenizer dispatch — referenced by tokenizer factory code paths
    "llama",
    "t5",
})


def all_model_dirs() -> list[str]:
    """Walk the installed transformers package and list every subdir of
    `transformers/models/` — that's the architecture set."""
    try:
        import transformers
    except ImportError:
        print("error: transformers not installed in this venv. "
              "Run `uv sync` first.", file=sys.stderr)
        sys.exit(1)

    models_root = Path(transformers.__file__).parent / "models"
    if not models_root.is_dir():
        print(f"error: expected dir not found: {models_root}", file=sys.stderr)
        sys.exit(1)

    archs = []
    for child in sorted(models_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("__") or child.name.startswith("."):
            continue
        # Sanity: must contain at least one .py file
        if not any(p.suffix == ".py" for p in child.iterdir()):
            continue
        archs.append(child.name)
    return archs


def main() -> int:
    archs = all_model_dirs()
    excluded = [a for a in archs if a not in ALLOWLIST]
    kept = [a for a in archs if a in ALLOWLIST]

    print(f"# transformers.models.* architectures: {len(archs)} total", file=sys.stderr)
    print(f"# allowlist (kept):  {len(kept)}", file=sys.stderr)
    print(f"# excluded:           {len(excluded)}", file=sys.stderr)
    print(f"# (estimated saving: ~{len(excluded) * 3}–{len(excluded) * 5} MB per arch)",
          file=sys.stderr)
    print("# (paste these lines into scripts/build_sidecar.py's `cmd` list)",
          file=sys.stderr)
    print(file=sys.stderr)

    for arch in excluded:
        print(f'        "--exclude-module", "transformers.models.{arch}",')

    return 0


if __name__ == "__main__":
    sys.exit(main())
