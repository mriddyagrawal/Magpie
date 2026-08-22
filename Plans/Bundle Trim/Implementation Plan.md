# Bundle Trim — Implementation Plan

> **Status:** Active design as of 2026-05-08. Working branch: `bundle-trim` (off `UI`).
> Goal: shrink the production install footprint from 3.5 GB → ~600 MB so the
> shipped `.dmg` / `.AppImage` / `.exe` are reasonable for non-developers to
> download. Pairs naturally with [Plan #10 — Self-contained packaging](../Future%20Plans.md).

---

## 1. Why this matters

Every megabyte you ship is a megabyte the user downloads, a megabyte Apple's
notarization service hashes, a megabyte SmartScreen flags as "unfamiliar," and
a megabyte your CI uploads to GitHub Releases on every build. **Smaller bundle
compounds across all three installer formats and the entire CI matrix.**

Today's `.venv` is **3.5 GB**. About **70%** of that is libraries the runtime
never calls (CUDA on Mac, AWS SDK we don't use, Temporal worker SDK we don't
use, Jupyter notebook server we use only for dev).

---

## 2. Baseline — the 3.5 GB audit

Top 15 packages by disk size in `.venv/lib/python3.11/site-packages/`:

| # | Package | Size | Used at runtime? | Action |
|---:|---|---:|---|---|
| 1 | **`nvidia/`** (cudnn, cublas, cusolver, cufft, ...) | **2.4 GB** | ❌ on Mac (uses MPS), ❌ on CPU-only Linux | **Strip via `torch+cpu` wheel** |
| 2 | `triton` | 171 MB | ❌ Mac, conditional on Linux | Strip with CUDA |
| 3 | `cuda` (cuda-bindings) | 107 MB | ❌ same | Strip with CUDA |
| 4 | `scipy` | 66 MB | ✅ (transitive via sklearn / colpali) | Keep |
| 5 | **`notebook`** | 65 MB | ❌ dev-only | **Move to dev-deps** |
| 6 | `pymupdf` | 57 MB | ✅ PDF parsing in router | Keep |
| 7 | `onnxruntime` | 50 MB | ✅ used by `fastembed` | Keep |
| 8 | **`temporalio`** | 48 MB | ❌ unused (came in as `pydantic-ai[temporal]` extra) | **Remove** |
| 9 | `babel` | 32 MB | ❌ transitive via Jupyter | Drops with #5 |
| 10 | `sklearn` | 31 MB | ✅ used by sentence-transformers | Keep |
| 11 | `numpy + scipy.libs` | ~58 MB | ✅ everywhere | Keep |
| 12 | `sympy` | 29 MB | ❌ transitive via torch (symbolic shapes — unused at runtime) | Strip via PyInstaller `excludes` |
| 13 | **`botocore`** (+ `boto3`, `s3transfer`) | ~24 MB | ❌ unused (came in as `pydantic-ai[bedrock]` extra) | **Remove** |
| 14 | `IPython` (transitive) | ~20 MB | ❌ via Jupyter | Drops with #5 |

**The math:** items marked **bold** above sum to **~2.74 GB** of strippable
weight. That's the entire goal of this branch — not by clever new tooling, just
by stopping the install of code we never call.

The HF model cache (`~/.cache/huggingface/hub` — ~5 GB) is **not** included in
the venv and never bundled. It downloads on first model use. No action needed.

---

## 3. Goals & non-goals

### Goal
Production `.venv` ≤ **800 MB** for the default Mac/CPU build, ≤ **1.5 GB**
for an opt-in CUDA build. End-user `.dmg` ≤ **350 MB** after PyInstaller/Nuitka
shipping (Python interpreter + `.venv` minus excludes + Tauri shell).

### Success criteria
1. `du -sh .venv` after a fresh `uv sync` on Mac < 800 MB.
2. `pnpm tauri build` on Mac produces a `.dmg` ≤ 350 MB.
3. Mridul's CSV ingestion + Astavak's text/PDF ingestion both still work
   end-to-end on the trimmed bundle (no functionality regression).
4. T4 (ColPali) opt-in — does NOT ship by default, is downloaded/loaded only
   when the user explicitly opts into visual indexing.
5. Cold-start time of Tauri sidecar (first `import` chain) ≤ 3 s on Mac.

### Non-goals (explicitly deferred)
- Replacing torch with ONNX-only inference. (Big win in theory, but ColPali
  needs full torch + LoRA via peft — converting is a separate research project.)
- Bundling the Qdrant standalone binary. (That's [Plan #10](../Future%20Plans.md) work,
  paired with self-contained Python packaging.)
- Cross-compilation infrastructure changes. (CI matrix already exists in
  `.github/workflows/build.yml`.)
- Migrating away from `pydantic-ai`. (We just need to stop pulling its extras.)

---

## 4. The five levers, with concrete steps

### Lever A — Strip CUDA / NVIDIA libs (2.7 GB saved, biggest win)

`torch v2.10.0` (today's pin) includes ALL CUDA libs on every platform via
hard transitive deps on `nvidia-*` packages. This is wrong for Mac (which
uses MPS) and for users without a CUDA GPU on Linux/Windows.

**Fix:** use `[tool.uv.sources]` to swap to the CPU-only wheel for Mac and
non-CUDA Linux. Provide an opt-in CUDA build path for users who want GPU
acceleration on Linux/Windows.

```toml
# pyproject.toml — sketched

[project]
dependencies = [
    "torch>=2.0",
    # ... rest unchanged
]

[tool.uv.sources]
torch = [
    { index = "pytorch-cpu", marker = "sys_platform != 'linux' or extra == 'cpu'" },
    { index = "pytorch-cu121", marker = "sys_platform == 'linux' and extra == 'cuda'" },
]

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[[tool.uv.index]]
name = "pytorch-cu121"
url = "https://download.pytorch.org/whl/cu121"
explicit = true
```

**Impact:** ~2.4 GB nvidia/ + 171 MB triton + 107 MB cuda → **gone on Mac and
default Linux.** Astavak's existing GPU workflow on Linux still works via
`uv sync --extra cuda`.

**Risk:** ColPali on Linux without `--extra cuda` falls back to CPU at MUCH
lower throughput. Document this clearly. Mac users continue to use MPS as
before — no regression.

### Lever B — Move dev-only deps out of `dependencies` (~300 MB)

Move `ipykernel`, `jupyter`, `notebook` to `[tool.uv]` `dev-dependencies`.
These are tools developers use to open `notebooks/*.ipynb` files; the runtime
never imports them. Removes the 65 MB `notebook` package and ~250 MB of
transitive Jupyter web-server deps (`tornado`, `jinja2`, `babel`, `bleach`,
`prompt-toolkit`, `nbconvert`, `nbformat`, `defusedxml`, etc.).

```toml
[project]
dependencies = [
    # ... runtime-only deps. NO ipykernel, jupyter, notebook here.
]

[tool.uv]
dev-dependencies = [
    "ipykernel",
    "jupyter",
    "notebook",
    "pytest>=7.0",  # already separated probably; verify
]
```

Developers run `uv sync --dev` to get notebooks back. CI / production use
plain `uv sync`.

### Lever C — Drop unused `pydantic-ai` extras (~70 MB)

`uv tree` shows we're pulling `pydantic-ai[temporal,bedrock]`. We use neither:
- We use OpenRouter (HTTP REST), not AWS Bedrock → no need for `boto3`/`botocore`/`s3transfer`/`jmespath`.
- We use synchronous LLM calls, not Temporal workers → no need for `temporalio`.

**Fix:** pin pydantic-ai to its base extras only. Investigate where the
extras come from (probably an over-eager pin like `pydantic-ai[all]`) and
narrow it.

```toml
# Before (likely):
"pydantic-ai>=0.0.14"          # implicitly grabs everything? or transitive [all]

# After:
"pydantic-ai[openai]>=0.0.14"  # or whatever the minimum extras we genuinely need
```

Verify with `uv tree | grep -E "temporalio|botocore"` after — should be empty.

### Lever D — Lazy-import ML deps in startup path (no disk savings, big UX win)

The Tauri sidecar's cold start currently pulls in torch + transformers +
sentence-transformers eagerly via `colpali-engine`. Goal: defer these until
a query actually exercises the embedder.

**Audit:** grep `^from torch|^import torch|from transformers|from sentence_transformers` in `src/`
and check whether each is module-scope (eager) or function-scope (lazy).

Most of stage2's hot models should already be lazy; verify by profiling.

```bash
uv run python -X importtime -c 'from src.server import app' 2>&1 | tail -50
# Look for torch / transformers in the slow imports
```

Anything > 100 ms for ML modules at module-load time is a candidate to push
into a function body. Net effect: ~2-3 s faster Tauri first-paint, ~1.5 GB
less peak RAM at startup (matters on 8 GB Macs).

### Lever E — PyInstaller / Nuitka excludes for unused submodules (~200 MB)

When the Tauri build packages the Python sidecar, pass an explicit
`excludes=[...]` list of submodules we never call:

```python
# PyInstaller .spec (approximate)
a = Analysis(
    ['src/server.py'],
    excludes=[
        'torch.distributed',    # we never multi-node
        'torch.onnx',           # we don't export
        'torch.fx',             # we don't symbolic-trace
        'torch.profiler',       # not in production code
        'torch.tensorboard',    # never used
        'torch._dynamo',        # not using torch.compile
        'torch.optim',          # we never train
        'torch.autograd.profiler',
        'transformers.models.<long list of unused arches>',
        'sympy',                # only loaded by torch's symbolic shapes
        'mpmath',               # transitive sympy
    ],
    ...
)
```

This is the most fragile lever — incorrect excludes cause runtime
ImportErrors that don't surface until a specific code path runs. Validate
with the smoke test (Step 8 in PR breakdown). **Do this last.**

---

## 5. PR breakdown — 5 commits on `bundle-trim`

Each commit is mergeable on its own and self-contained.

### PR-A. Move dev deps to `[tool.uv].dev-dependencies` *(safest, do first)*
- Edit `pyproject.toml`: pull `ipykernel`, `jupyter`, `notebook` out of `dependencies`, add to `dev-dependencies`.
- Run `uv sync` (default) + verify `notebook` no longer in `.venv`.
- Run `uv sync --dev` + verify it comes back.
- Tests still pass (no production code imports any of these).
- **~300 MB saved.**

### PR-B. Drop `pydantic-ai` extras `[temporal]` and `[bedrock]`
- Investigate which dep declares the `[temporal,bedrock]` request (probably a transitive over-pin).
- Pin `pydantic-ai` with explicit extras list — only what we need (OpenRouter / OpenAI / Moonshot — we use HTTP REST, not provider SDKs).
- Verify `uv tree | grep -E "temporalio|botocore|boto3"` returns empty after `uv sync`.
- **~70 MB saved.**

### PR-C. Switch to `torch+cpu` wheel via `[tool.uv.sources]` *(biggest win)*
- Add `[tool.uv.sources]` block with conditional indexes per the sketch in §4 Lever A.
- Add `cuda` extra for the opt-in GPU build.
- Update README with: "default install is CPU; Linux GPU users run `uv sync --extra cuda`."
- Verify on Mac: `uv sync && du -sh .venv` shows the nvidia/ and triton/ folders gone.
- Verify on Linux: `uv sync --extra cuda` brings them back.
- **~2.7 GB saved on Mac and CPU Linux.**

### PR-D. Audit + tighten lazy-imports of ML deps
- Run `uv run python -X importtime -c 'from src.server import app'` and capture the slow-import list.
- For any torch / transformers / sentence-transformers import that fires at module scope of a hot startup file, push into a function body.
- Smoke-test cold start: `time uv run uvicorn src.server:app --port 8765` → first response < 3 s.
- **0 disk savings, ~1.5 GB peak-RAM-at-startup savings, ~2-3 s faster cold start.**

### PR-E. PyInstaller / Nuitka `excludes` (do this with the actual bundling work)
- This PR happens in coordination with the [Plan #10](../Future%20Plans.md) packaging work.
- Add the `.spec` file (or Nuitka equivalent) with the `excludes` list from §4 Lever E.
- Run a smoke build, install on a fresh test env, run a query end-to-end.
- If any ImportError surfaces, narrow the excludes.
- **~200 MB saved.**

---

## 6. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `torch+cpu` wheel breaks ColPali on Linux without GPU | High | Medium | ColPali is T4-only and already opt-in. Plus `uv sync --extra cuda` brings full torch back. |
| `pydantic-ai` minimum extras still pull a transitive `boto3` | Low | Low | If so, hard-pin `pydantic-ai==<exact-version-without-extras>` and document the constraint. |
| Lazy-import refactor breaks a code path that depended on eager init | Medium | Low | Each move is a small commit; pytest run gates each. |
| PyInstaller `excludes` accidentally drops a transitively-needed module | High | High | Smoke-test the bundled artifact in CI on every change. Iterate the excludes list. |
| `.github/workflows/build.yml` doesn't handle the new `[tool.uv.sources]` syntax | Medium | Medium | Test locally before pushing; fall back to manual `uv sync --extra` invocations in CI if needed. |

---

## 7. Validation checkpoints

After each PR, run:

```bash
# 1. Disk
du -sh .venv

# 2. Imports clean
uv run python -c "import torch, transformers, src.server, src.config; print('ok')"

# 3. Tests
uv run pytest tests/

# 4. End-to-end ingest of a tiny corpus
mkdir -p /tmp/bundle-trim-smoke && echo "Test content" > /tmp/bundle-trim-smoke/test.txt
just walk /tmp/bundle-trim-smoke
just check-dir /tmp/bundle-trim-smoke

# 5. Tauri dev mode launches without import errors
cd frontend && pnpm tauri dev      # smoke; close once window opens
```

Add a CI job to `.github/workflows/build.yml`: post-`uv sync`, fail the build
if `du -sb .venv | awk '{print $1}'` > a configured byte limit (e.g.
`900_000_000`). Prevents accidental size regressions.

---

## 8. Cross-references

### Tightly related
- [Plan #10 — Self-contained packaging](../Future%20Plans.md): bundling the
  trimmed venv + Python interpreter + Qdrant binary into the `.app`. PR-E of
  this plan ships **inside** Plan #10.

### Loosely related
- [Plan #11 — Unify orphan-cleanup pattern](../Future%20Plans.md): not blocked
  by this work.
- [Plan #13 — Daemon as OS service](../Future%20Plans.md): the daemon's RAM
  footprint matters more once we promote it to launchctl / systemd. This work
  cuts that footprint at startup.

### Source
- The 5 levers were proposed during the 2026-05-08 conversation about
  distribution size; the audit (§2) was generated in the same session and
  drove all the magnitude estimates.
