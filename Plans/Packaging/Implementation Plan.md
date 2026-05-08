# Plan #10 — Self-contained Packaging (Implementation Plan)

> **Status:** Locked design as of 2026-05-08. Working branch: TBD (`packaging`
> off latest `UI` once Mridul starts P10-1). Sister doc to
> [`Plans/Bundle Trim/Implementation Plan.md`](../Bundle%20Trim/Implementation%20Plan.md).
>
> **Owner:** Mridul (distribution pipeline) + Rahul (UI / onboarding for P10-7).
>
> **Origin:** [`Plans/Packaging/Brainstorm.md`](Brainstorm.md). This doc
> supersedes the brainstorm where they conflict; the brainstorm stays
> alongside as scoping/discussion context.

---

## 1. Goal & Non-goals

### Goal

Produce shippable, self-contained installers — `.dmg` (macOS), `.AppImage`
+ `.deb` (Linux), `.exe` + `.msi` (Windows) — where a non-developer
double-clicks the installer and Magpie works. **No external dependencies
required at runtime: no `uv`, no Python interpreter, no source tree, no
manual `just qdrant-install` ceremony.**

### Concrete success criteria

1. A stranger on Mac downloads `Magpie-arm64.dmg`, drag-drops to
   `/Applications`, double-clicks. App launches. Folder picker appears
   (P10-7). Picked folder gets indexed. Search returns hits. **Zero
   command-line steps.**
2. Same on Linux via `.AppImage` and Windows via `.exe`.
3. `.dmg` size ≤ **350 MB** for default Mac CPU build. Linux/Windows ~similar.
4. Sidecar cold start (frozen executable launch → first `/health` 200) ≤ **1.5 s** on a typical Mac.
5. macOS Gatekeeper opens cleanly (P10-5 signing); Windows SmartScreen
   does not flag (P10-5 EV cert).
6. Auto-updater (P10-6) updates without users re-downloading the full
   bundle.

### Non-goals (explicitly deferred)

- **PR-E Tier 3 excludes** (`transformers.models.<unused arch>` narrow exclusions). High-risk, low-payoff. Skip for v1; revisit only if a user-facing size complaint arises.
- **CUDA-bundled Linux build.** Default install is CPU/MPS via the [`pytorch-cpu` source](../Bundle%20Trim/Implementation%20Plan.md#5-pr-breakdown--5-commits-on-bundle-trim) from bundle-trim. Linux GPU users continue to use `UV_TORCH_BACKEND=cu121 uv sync` — they're devs, not the target end-user.
- **Differential / patch-style updates.** Auto-updater (P10-6) replaces the whole `.app`. Differential updates are nice-to-have, not v1.
- **Universal2 macOS binary.** Two arch-specific `.dmg`s (Intel + Apple Silicon) instead. Smaller per-user download, simpler signing.
- **Code signing budget approval.** Apple Developer ID (~$99/yr) and Windows EV cert (~$200–500/yr) are real money requiring a budget owner. The plan documents WHERE signing happens; the actual procurement is a non-engineering decision out of scope here.

---

## 2. The five sub-problems

Every desktop-app bundle has to solve five layers. Each one maps to a piece of the PR breakdown:

| # | Layer | Solved in PR(s) | Mechanism |
|---|---|---|---|
| 1 | **Python interpreter** — bundle CPython 3.11 inside the app so users don't need Python installed | P10-1 | PyInstaller one-folder mode. Already in deps as `pyinstaller>=6.0` (in the new `packaging` opt-in dependency-group). |
| 2 | **Python source** — bundle `src/` and `cli/` next to the interpreter | P10-1 | PyInstaller's `Analysis(scripts=...)` + `--collect-all` for tricky packages |
| 3 | **Native binaries** — Qdrant standalone, llama-server | P10-3 | Build pipeline downloads per-arch binaries → stages in `Resources/bin/` → Tauri Rust spawns by relative path |
| 4 | **Resources** — `magpie_defaults.json`, prompts, icons | P10-1 | PyInstaller's `datas=[(...)]`. Verify that `_config_dir()` in `src/config/indexing_rules.py` resolves correctly inside a frozen bundle (PyInstaller preserves `Path(__file__).parent` semantics). |
| 5 | **Code signing & notarization** — keep OS vendors happy | P10-5 | Mac: `codesign` + Apple notary. Win: `signtool` with EV cert. Linux: optional GPG signature on `.AppImage` / `.deb`. |

**None of these touch the frontend code.** Mridul's UI work, Rahul's
settings/secrets work, Astavak's ingestion-rules work — all of it ships
inside whatever this plan produces, unchanged. Plan #10 builds the
**chassis**; the existing app is the **engine**.

---

## 3. The cross-platform `.spec` — one file, three OSes

PyInstaller's `.spec` is a Python script. It's **platform-agnostic by
default**; only the bundle-wrapping step is platform-aware via small
`if sys.platform == ...` blocks.

```python
# magpie.spec — same file, runs on Mac/Linux/Windows
import sys

a = Analysis(
    ['src/server.py'],
    datas=[('src/config/magpie_defaults.json', 'src/config/')],
    hiddenimports=['colpali_engine', 'pydantic_ai_slim'],
    excludes=[
        # PR-E Tier 1 (high confidence)
        'torch.distributed', 'torch.onnx', 'torch.profiler',
        'torch.tensorboard', 'torch.optim', 'torch.autograd.profiler',
        'IPython', 'babel',
        # PR-E Tier 2 (validate one-by-one)
        'torch.fx', 'torch._dynamo', 'sympy', 'mpmath',
        # Tier 3 (transformers.models.<unused>) — deferred. See §5.
    ],
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(pyz, a.scripts, ...)
coll = COLLECT(exe, a.binaries, a.datas, name='Magpie')

# OS-specific wrapping — small blocks at the end of the same file
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='Magpie.app', icon='icons/magpie.icns', ...)
elif sys.platform == 'win32':
    exe.icon = 'icons/magpie.ico'
# Linux: no extra wrapping; .AppImage built by P10-4 around the dist/ folder
```

**One `magpie.spec` file lives in the repo. Three CI runners (Mac, Linux,
Windows) each invoke `pyinstaller magpie.spec` and produce the right output
for their OS.** PyInstaller reads `sys.platform` and produces the right
shape.

P10-1 produces this `.spec` and validates on Mac. P10-4 adds the per-OS
wrappers (`.AppImage` for Linux, NSIS installer for Windows, `.dmg`
builder for Mac) around the `dist/` output the same `.spec` produces.

---

## 4. PR Breakdown — what's already done vs. remaining

> **2026-05-08 reality-check:** when this plan was first written, I assumed
> P10-1 through P10-7 were all greenfield. They aren't — Mridul shipped most
> of the packaging pipeline before the bundle-trim conversation started.
> Commits like `ebe3e80 feat: cross-platform sidecar bundling via PyInstaller`,
> `d5d7f72 build: extend PyInstaller hidden-imports`, `5cbda20 Phase 3: fix
> staging path` did the heavy lifting. This table now reflects actual state.

### Already done ✅

| PR | What was done | Where it lives |
|---|---|---|
| **P10-1** | Cross-platform sidecar build via PyInstaller, all hidden imports + `--collect-all` flags + `--copy-metadata` for libraries that call `importlib.metadata.version()` | [`scripts/build_sidecar.py`](../../scripts/build_sidecar.py). Uses CLI args directly, NOT a `.spec` file. |
| **P10-3** | Native binary bundling — Qdrant pre-downloaded into `frontend/src-tauri/binaries/qdrant-<target-triple>` for each platform. Tauri's `externalBin` config bundles them into the `.app`/`.AppImage`/`.exe`. The Rust sidecar spawn ([frontend/src-tauri/src/lib.rs:573](../../frontend/src-tauri/src/lib.rs#L573)) finds them by `resource_dir().join("magpie-sidecar")`. | [`scripts/download_qdrant.py`](../../scripts/download_qdrant.py), [`tauri.conf.json` line 41](../../frontend/src-tauri/tauri.conf.json) (`"externalBin": ["binaries/magpie-sidecar", "binaries/qdrant"]`) |
| **P10-4** | Cross-platform CI matrix — Mac arm64, Mac x86_64, Linux x86_64, Windows x86_64 — running the full pipeline (uv sync → build_sidecar.py → download_qdrant.py → pnpm tauri build → upload artifacts) | [`.github/workflows/build.yml`](../../.github/workflows/build.yml). `.dmg` for Mac, `.AppImage` + `.deb` for Linux, `.exe` (NSIS) for Windows. |
| **P10-5 infra** | Code-signing infrastructure wired into CI, gated on `APPLE_CERTIFICATE` / `WINDOWS_CERTIFICATE` GitHub secrets being set. CI silently skips signing if the secret is absent. | [`.github/workflows/build.yml`](../../.github/workflows/build.yml) lines 92-145 |
| **P10-2 Tier 1** | High-confidence excludes (`torch.distributed`, `torch.onnx`, `torch.profiler`, `torch.tensorboard`, `torch.optim`, `torch.autograd.profiler`, `IPython`, `babel`) added to `build_sidecar.py`. ~80–100 MB savings. Zero runtime risk — these submodules are well-isolated. | [`scripts/build_sidecar.py`](../../scripts/build_sidecar.py) — added 2026-05-08 |

### Remaining work (the real Plan #10 backlog)

| PR | Scope | Notes |
|---|---|---|
| **P10-2 Tier 2** | Apply `torch.fx`, `torch._dynamo`, `sympy`, `mpmath` excludes ONE AT A TIME with smoke tests in between. | Already added as commented-out `--exclude-module` lines in `build_sidecar.py`. On Mac, uncomment one, rebuild, smoke-test (ingest tiny corpus → run query → exercise T4 image tier). If green, keep; if ImportError, leave commented. ~80–100 MB additional if all four work. |
| **P10-2 Tier 3** | `transformers.models.<unused arch>` narrow exclusions | **Deferred.** ~30–50 MB potential saving but high-risk (transformers loads classes by string name dynamically; wrong exclude breaks ColPali/sentence-transformers at runtime). Revisit only on user-facing size complaint. |
| **P10-5 procurement** | Apple Dev ID ($99/yr) + Windows EV cert ($200–500/yr). Add to GitHub secrets. | The CI is ready; just needs a budget owner to procure and upload base64-encoded `.p12`/`.pfx` to the repo's secrets. |
| **P10-6** | Auto-updater. Tauri 2's built-in `tauri-plugin-updater` — needs (a) plugin in Cargo.toml, (b) `updater` block in tauri.conf.json with endpoint URL + public key, (c) Rust registration in lib.rs, (d) signing keys checked into CI as `TAURI_SIGNING_PRIVATE_KEY` secret. | NOT started. Estimated ~half-day of focused work. Detail in §5. |
| **P10-7** | First-launch onboarding — folder picker dialog, model-download progress UI, "we're warming up the embedder" messaging. | NOT started. Frontend work, paired with Rahul. The `MAGPIE_DATA_DIR` empty-state needs a real UX, not just a 503. |
| **P10-? (renormalize)** | Update naming so binary at `dist/magpie-sidecar` is correctly placed at `frontend/src-tauri/binaries/magpie-sidecar-<target-triple>` for Tauri's `externalBin` to pick up. | Already done in `build_sidecar.py:117` (the `shutil.move(src_exe, dst_exe)` line). No work needed. |

**Net:** the brainstorm-era estimate of "1–2 weeks for Plan #10 from scratch"
collapses to ~2 days of remaining work (Tier 2 iteration + auto-updater
wiring + onboarding pairing), plus whatever procurement signing certs takes.

### Bug found while validating Tier 1 (caught by Linux smoke build, fixed in same commit)

The bundle-trim PR-B replaced `pydantic-ai>=0.0.14` with
`pydantic-ai-slim[openai,retries]>=1.0`. The Python import path stays
the same (`pydantic_ai`), but the distribution name changes from
`pydantic-ai` to `pydantic-ai-slim`. PyInstaller's `--copy-metadata
pydantic_ai` flag fails because that distribution no longer exists:

```
importlib.metadata.PackageNotFoundError: No package metadata was
found for pydantic_ai
```

Fixed by updating `scripts/build_sidecar.py`:

```diff
- "--copy-metadata", "pydantic_ai",
+ "--copy-metadata", "pydantic_ai_slim",
+ "--copy-metadata", "pydantic_graph",  # transitive — also calls version()
```

Without this fix, `build_sidecar.py` fails on every platform after the
bundle-trim merge. **Validated by reaching past the failing line in the
Linux smoke build.** Not merging this fix back into bundle-trim because
build_sidecar.py only runs in CI / packaging contexts; bundle-trim itself
doesn't need it. Lives on the `packaging` branch.

---

## 5. PR-E details — iterative two-tier exclude cycle

### Tier 1 — high confidence (~95%), apply all together

These modules are well-isolated within their parent packages. PyTorch
never internally imports them unless specific code paths run (which we
don't):

```python
excludes = [
    'torch.distributed',          # multi-node training (we never multi-node)
    'torch.onnx',                 # ONNX export (we never export)
    'torch.profiler',             # perf profiling
    'torch.tensorboard',          # tensorboard logging
    'torch.optim',                # training (we never train)
    'torch.autograd.profiler',
    'IPython',                    # debug REPL — should not have leaked through PR-F but defensive
    'babel',                      # i18n — we don't translate
]
```

**Apply all at once, build, smoke test.** If everything works → keep.
Saving: ~80–100 MB.

### Tier 2 — medium confidence (~60-70%), apply one at a time

These are riskier because PyTorch's internal code occasionally lazy-imports them in unexpected places:

```python
excludes_tier_2_candidates = [
    'torch.fx',         # symbolic graph tracing (torch.compile machinery)
    'torch._dynamo',    # torch.compile machinery
    'sympy',            # used by torch's symbolic-shapes path; we don't use it
    'mpmath',           # transitive sympy
]
```

**For each candidate** (in this order):

1. Add to `Analysis(excludes=[...])`.
2. `pyinstaller magpie.spec` — should still build.
3. Launch `Magpie.app`. Assert window opens, sidecar `/health` returns 200.
4. End-to-end smoke: ingest `/tmp/test-corpus/` (5 small files), run a query, exercise T4 (drop one image in the corpus). Assert no `ImportError` traceback in sidecar logs.
5. **If green** → keep that exclude, move to next candidate.
6. **If red** → remove that exclude (or narrow to a sub-submodule like `torch.fx._symbolic_trace`), document, move on.

Total expected: ~80–100 MB additional. Realistically 1-2 of the four
candidates will need to be backed out or narrowed.

### Tier 3 — `transformers.models.<unused arch>` (RE-OPENED 2026-05-08)

Originally deferred on the assumption of "30–50 MB potential saving, hours
of trial-and-error." Web research surfaced two facts that flipped the
calculus:

1. **`transformers` ships ~200 model architectures** under
   `transformers/models/<arch>/`. Each is ~3-5 MB on disk (~600 MB to
   1 GB total). PyInstaller bundles every one because static analysis
   can't see that AutoModel does string-based lookup at runtime.
2. **ColPali's actual surface is narrow** — per the
   [`colpali_engine/models/__init__.py`](https://github.com/illuin-tech/colpali/blob/main/colpali_engine/models/__init__.py)
   imports, it pulls only ~12 architecture families (paligemma, qwen2_vl,
   qwen2_5_vl, qwen2_5_omni, gemma/2/3, qwen2/2_5/3/3_5, siglip, idefics3,
   modernvbert).

Real saving (measured 2026-05-08 against the trimmed venv): the
[generator script](../../scripts/list_unused_transformers_models.py)
prints **437 `--exclude-module` lines** out of **459 total architectures**
(only 22 in the allowlist). At 3-5 MB per architecture this is
**~1.3-2.2 GB** of potential strip — the single biggest exclude-pass
target by an order of magnitude, bigger than Tier 1 + Tier 2 combined.

#### Strategy: allowlist, don't blacklist

Listing 150 `--exclude-module` flags by hand is brittle (transformers adds
new architectures every release). Instead: maintain a small ALLOWLIST of
architectures we KNOW are needed, and exclude everything else
programmatically.

The helper script [`scripts/list_unused_transformers_models.py`](../../scripts/list_unused_transformers_models.py):
1. Imports `transformers`, walks `transformers/models/`
2. Subtracts the allowlist (vision-language families used by ColPali +
   common embedder backbones for sentence-transformers)
3. Prints `--exclude-module transformers.models.<arch>` lines for the
   leftover ~150

Run it on Mac in the project venv:
```bash
uv run python scripts/list_unused_transformers_models.py >> /tmp/tier3-excludes.txt
# Paste contents of /tmp/tier3-excludes.txt into build_sidecar.py's `cmd` list
# (right before the closing `]` per the comment block in that file).
```

#### Validation

This is the highest-risk exclude pass — broken excludes don't surface at
build time, only at first user query. Validation needs to exercise EVERY
tier:

| Tier | Triggers |
|---|---|
| T0 (raw text) | `.txt` ingestion |
| T1 (code) | `.py` / `.js` ingestion |
| T2 (PDF text) | `.pdf` with extractable text |
| T3 (PDF vision-fallback) | `.pdf` with no extractable text (scanned image PDF) → `pix2struct`-shape lookup |
| T4 (ColPali) | image file or vision-heavy PDF → ColQwen2 load |

If any of these ImportError at runtime: identify the missing architecture
from the traceback, ADD it to the ALLOWLIST in the helper script, re-run,
rebuild.

#### Allowlist as committed (subject to refinement)

```python
ALLOWLIST = frozenset({
    "auto",                                    # NEVER exclude — dispatch tables

    # ColPali backbones (per colpali_engine 0.3.x)
    "paligemma", "qwen2", "qwen2_5", "qwen3", "qwen3_5",
    "qwen2_vl", "qwen2_5_vl", "qwen2_5_omni",
    "gemma", "gemma2", "gemma3", "siglip",
    "idefics3", "modernvbert",

    # Sentence-transformers / embedder backbones
    "bert", "distilbert", "mpnet", "roberta",
    "xlm_roberta", "deberta_v2",

    # Tokenizer dispatch
    "llama", "t5",
})
```

Conservative — start here, refine downward by trying smaller subsets
(e.g., drop `gemma3` if you're sure no Gemma-3 model is loaded, drop
`qwen3` family if only Qwen2.5 is in use). Each removal saves ~3-5 MB.

---

## 6. Open questions answered

The brainstorm raised six. Locking these defaults — push back during PR if anything bites:

1. **One-folder vs one-file PyInstaller mode** → **one-folder.** Faster startup, slightly larger; one-file extracts to temp on each launch (~3 s slower cold start). Desktop UX wins.
2. **`.dmg` host** → **GitHub Releases for v1.** Free, integrated with the auto-updater. Migrate to a CDN if download speed becomes a complaint.
3. **Auto-updater scope** → **whole-bundle replacement for v1.** Differential updates are nice-to-have, not blocking.
4. **`peft` / `colpali-engine` LoRA-loading under PyInstaller** → **validate during P10-2.** If breakage, narrow excludes or add `--collect-all peft`.
5. **Bundle the HF model cache?** → **Never.** First-launch downloads handled by P10-7's onboarding progress UI.
6. **Universal2 binary vs split-arch?** → **Split-arch** (`Magpie-arm64.dmg` + `Magpie-x86_64.dmg`). Smaller per-user download, simpler signing.

---

## 7. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `peft` ImportError under frozen bundle (peft uses `__file__`-based path resolution) | Medium | High — T4/ColPali path breaks at first vision query | Add `--collect-all peft` and `--collect-data colpali_engine` in P10-2 if it surfaces. Smoke test T4 explicitly. |
| `magpie_defaults.json` not findable inside frozen bundle | Low | High — IndexingRules silently degrades to no-defaults | Already a defensive code path in `load_magpie_defaults()` (warns + returns empty defaults). P10-1 explicitly tests by checking `should_index('/tmp/something/in_node_modules/foo')` returns rejected. |
| Tier-2 excludes break a non-obvious code path that doesn't surface in smoke test | Medium | Medium — user hits ImportError at runtime weeks later | Keep the smoke test thorough — exercise every tier (T0/T1/T2/T3/T4), not just text. Track exclude regressions in `Plans/Packaging/exclude-history.md` for next time. |
| Tauri Rust shell + frozen Python sidecar IPC drifts (paths, env vars) | Low | High — the whole bundle is broken | Audit `frontend/src-tauri/src/lib.rs` carefully during P10-3. Document the spawn contract (cwd, env, exit handling). |
| macOS notarization rejects the bundle for ad-hoc reasons (entitlements, hardened runtime) | High | Medium — ships without notarization, users see Gatekeeper warning until fixed | P10-5 is its own PR; budget time for ~3 notarization rejections before it goes through. Common: missing `--options runtime`, missing entitlements for sandboxed file access. |
| First-launch model download (~5 GB HF cache) feels broken to users | High | High — they think the app is hung; bad reviews | P10-7's onboarding UI shows real progress (`huggingface_hub` exposes download progress callbacks). Pair tightly with Rahul on the UX. |
| CI matrix becomes flaky (Mac runner timeouts, Windows path issues) | Medium | Low (annoying but not user-facing) | Cache the venv between runs; budget for runner-debug time during P10-4. |
| Apple Developer ID + Windows EV cert procurement blocks shipping | High | High — can't ship to non-developers without these | Start the procurement BEFORE P10-5 starts. Apple ID takes ~1 week to issue; Windows EV cert can take 2–4 weeks for vetting. |

---

## 8. Validation checklist (per PR)

After each PR lands, run:

```bash
# P10-1: bundle builds + launches + sidecar reachable
pyinstaller magpie.spec
open dist/Magpie.app                              # Mac; analogue on Linux/Windows
curl -sS http://localhost:8765/health             # sidecar health

# P10-2: nothing broke from excludes
just walk /tmp/bundle-test                         # tiny corpus
just check-dir /tmp/bundle-test                    # all expected files index

# P10-3: native binaries spawn correctly
ps aux | grep -E "qdrant|llama-server"            # both running, spawned by the bundle

# P10-4: cross-platform — same checks pass on Linux + Windows CI

# P10-5: signing
codesign --verify --deep --strict dist/Magpie.app   # Mac
spctl -a -v dist/Magpie.app                          # Mac Gatekeeper
# Windows: signtool verify /pa Magpie.exe
# Linux: gpg --verify Magpie.AppImage.sig

# P10-6: auto-updater roundtrip
# Build v0.1.0 → install → publish v0.1.1 → in-app update prompt → confirm → relaunches as v0.1.1

# P10-7: cold-start UX
# Fresh user on a Mac without HF cache. Click installed Magpie. See onboarding,
# folder picker, model-download progress. After warm-up, search returns hits
# from the indexed folder. End-to-end with no terminal.
```

---

## 9. Cross-references

### Tightly coupled
- [`Plans/Bundle Trim/Implementation Plan.md`](../Bundle%20Trim/Implementation%20Plan.md) — produces the trimmed `.venv` we're bundling. PR-E (excludes) was originally listed there but lives in P10-2 of this plan instead, because excludes only make sense once a `.spec` exists.
- [`Plans/Packaging/Brainstorm.md`](Brainstorm.md) — earlier scoping doc. Kept for context.
- [`Plans/Future Plans.md`](../Future%20Plans.md) #10 entry — top-level pointer at this plan.

### Loosely related
- [`Plans/Future Plans.md`](../Future%20Plans.md) #4 — Rust-native file watcher; orthogonal but would change which Python deps the bundle needs.
- [`Plans/Future Plans.md`](../Future%20Plans.md) #13 — daemon-as-OS-service. The launchctl/systemd/Task-Scheduler integration would happen on top of the packaged bundle from this plan.
- [`Plans/Ingestion Rules/Implementation Plan.md`](../Ingestion%20Rules/Implementation%20Plan.md) — settings + secrets system that the bundled app relies on for first-launch UX.

---

## 10. What to do next (revised after the 2026-05-08 reality check)

Most of the plan is already shipped. The remaining work, in priority order:

### Step 1 — Validate Tier 1 excludes on Mac (~1 hour)

```bash
git fetch origin
git checkout bundle-trim    # has the Tier 1 exclude additions to build_sidecar.py
uv sync                      # confirm 1.3 GB venv + pyinstaller installs

# Build the sidecar with Tier 1 excludes applied
uv run python scripts/build_sidecar.py
# → frontend/src-tauri/binaries/magpie-sidecar-aarch64-apple-darwin
# Note the size; should be ~80-100 MB smaller than your last build.

# Build the full app
cd frontend && pnpm tauri build
# Verify the .dmg builds successfully and Magpie.app launches.

# Smoke test: ingest a tiny corpus, run a query, exercise T4 (image)
open /tmp/magpie-test          # any folder with mixed file types
just walk /tmp/magpie-test     # via the bundled CLI
just check-dir /tmp/magpie-test
# Open Magpie.app, search → should return hits
```

If everything works, Tier 1 is locked. If something ImportErrors → narrow
the offending exclude and rebuild.

### Step 2 — Iterate Tier 2 excludes (~1-2 hours)

In `scripts/build_sidecar.py`, uncomment ONE of the four Tier-2
`--exclude-module` lines. Repeat the build + smoke test. If green, keep
that one uncommented and try the next. Order doesn't matter much; suggested:

1. `mpmath` (lowest risk — leaf node)
2. `sympy` (next — depends on mpmath)
3. `torch.fx`
4. `torch._dynamo` (highest risk — torch.compile machinery)

Each successful exclude saves ~20-25 MB. Realistic expectation: 2-3 of the
four will work cleanly.

### Step 3 — Auto-updater (P10-6, ~half day)

**Pattern: mirror Tauri's official OSS `tauri-action` template.** Every
Tauri project that ships releases uses `tauri-apps/tauri-action@v0` —
familiar to any reviewer, smaller `build.yml` than what we have now,
handles signing + `latest.json` generation + GitHub Release upload as one
step. Don't write custom signing/upload logic; reuse the standard.

Tauri 2 has a built-in updater plugin. Wiring:

1. **Cargo.toml** — add `tauri-plugin-updater = "2"` to `[dependencies]`.
2. **lib.rs** — register the plugin in `tauri::Builder::default().plugin(tauri_plugin_updater::Builder::new().build())`.
3. **tauri.conf.json** — add a `plugins.updater` block:
   ```json
   "plugins": {
     "updater": {
       "active": true,
       "endpoints": [
         "https://github.com/mriddyagrawal/NotAnotherSpotlight/releases/latest/download/latest.json"
       ],
       "dialog": true,
       "pubkey": "<base64-public-key>"
     }
   }
   ```
4. **Generate signing keys** — `pnpm tauri signer generate -- -w ~/.tauri/magpie-updater.key`. Public key goes in `pubkey` above; private key goes into CI as `TAURI_SIGNING_PRIVATE_KEY` secret.
5. **Generate `latest.json`** in CI — Tauri's GitHub Action template handles this; or write a small script that produces it after `pnpm tauri build`.
6. **Frontend hook** — call `check()` from `@tauri-apps/plugin-updater` on app launch (or behind a "Check for updates" menu item).

Test: build v0.1.0, install, publish v0.1.1 to GitHub Releases, confirm the
in-app prompt appears on next launch and successfully updates.

### Step 4 — Onboarding flow (P10-7, paired with Rahul, ~1 day)

Pure frontend work. When `indexing_rules.json` has zero `include_paths`:

1. Show a welcome screen with "Pick the folders Magpie should index" + a folder-picker button (uses `tauri-plugin-dialog`).
2. After folder pick → call `POST /settings/include-path` (or wire via the existing settings UI Rahul built).
3. While first ingest runs, show progress: "Downloading models (~5 GB, one time)…", "Indexing 1234 files…".
4. When done → drop into normal search UI.

Coordination point: Rahul's `src/config/secrets.py` + Settings UI work
should be the foundation for this; no need to reinvent.

### Step 5 — Procure signing certs (Mridul's call)

- **Apple Developer Program** — ~$99/yr. ~1 week to issue. Required for
  notarization; without it Mac users see the Gatekeeper "damaged"
  warning.
- **Windows EV Code Signing certificate** — ~$200–500/yr. ~2-4 weeks for
  the vendor to vet identity. Required to dodge SmartScreen warnings.
- **Linux** — optional GPG signature on `.AppImage` / `.deb`; users
  mostly trust source.

Once you have them: base64-encode the `.p12` (Apple) and `.pfx` (Windows)
and add to GitHub secrets as `APPLE_CERTIFICATE` / `WINDOWS_CERTIFICATE`
(plus passwords). The existing CI [`.github/workflows/build.yml`](../../.github/workflows/build.yml)
already has the steps; they're just gated on the secrets existing.

---

**Stopped here on the Linux box because the disk is having severe I/O
errors. All edits this session landed on disk but not git (couldn't
commit/push). Mridul re-applies them on Mac (the Tier 1 + Tier 2
exclude changes to `scripts/build_sidecar.py` are the only code edits
that didn't make it to git from this session).**
