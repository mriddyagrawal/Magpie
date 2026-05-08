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

## 4. PR Breakdown — seven sequential PRs

| PR | Scope | Output | Ship-blocker for next |
|---|---|---|---|
| **P10-1** | First-pass cross-platform `magpie.spec` (one-folder mode). Validated on Mac. | `Magpie.app` launches and shows the GUI on Mridul's Mac. The same `.spec` is *expected* to build on Linux → `dist/magpie/` and Windows → `dist/magpie/`, but those runs deferred to P10-4. **No signing yet — Gatekeeper warning is OK at this stage.** | P10-2: needs the working baseline to add excludes against |
| **P10-2** | PR-E excludes — Tier 1 (high-confidence) → smoke test → Tier 2 (medium-confidence, one at a time) → smoke test → stop | All three platforms ~150–200 MB smaller. Tier 3 deferred. Detailed below. | P10-3: not blocking, but nice to do before adding native binaries to keep total size honest |
| **P10-3** | Bundle native binaries (Qdrant, llama-server) into `Resources/bin/` per-arch. Update Tauri Rust spawn code to find them by relative path instead of `uv run python3`. | `.app` (Mac), `dist/magpie/` (Linux), `dist/magpie/` (Windows) all run end-to-end without external installs. **This is where the `uv run python3` failure mode finally goes away.** | P10-4: needs the working bundle to wrap |
| **P10-4** | Per-OS wrappers + CI matrix runs the same `.spec` on Mac/Linux/Windows | `.dmg` (Mac), `.AppImage` + `.deb` (Linux), `.exe` installer + `.msi` (Windows). Dev-signed only — no Apple/MS cert yet. | P10-5: signing layered on top |
| **P10-5** | Apple Developer signing + notarization (Mac), EV cert signing (Windows), GPG signature (Linux) | All three installers open without OS-vendor security warnings. Needs *real money* — Apple Dev ID $99/yr + Win EV cert $200–500/yr. | P10-6: signing keys reused for the updater |
| **P10-6** | Auto-updater (Tauri's built-in) — release endpoint, signing keys for all three platforms | Users get updates regardless of OS without re-downloading. | P10-7: not blocking; ship in parallel |
| **P10-7** | First-launch onboarding flow (paired with Rahul on UI side) — purely frontend, OS-agnostic | New users see folder picker + model warm-up progress, not a silent broken app. | — |

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

### Tier 3 — deferred (skip for v1)

`transformers.models.<unused arch>` exclusions are deferred. `transformers`
loads model classes dynamically by name (`AutoModel.from_pretrained` →
runtime lookup), so excluding the wrong submodule breaks ColPali /
sentence-transformers at first user query, not at build. Getting the
right narrow set is hours of trial-and-error for ~30–50 MB of saving —
poor ROI compared to Tier 1+2.

**Revisit only if:** a user-facing size complaint arises, or we want to
push the bundle size below ~250 MB.

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

## 10. What "ready to start P10-1" looks like

1. `bundle-trim` branch verified on Mac (uv sync produces ~1.3 GB venv, tests pass, Tauri dev launches).
2. Mridul cuts a new branch off latest `UI` (which by then has bundle-trim merged in): `git checkout -b packaging`.
3. `uv sync --group packaging` → installs PyInstaller.
4. Spike a minimal `magpie.spec` with NO excludes yet — just enough that `pyinstaller magpie.spec` produces a `Magpie.app` that launches.
5. Once that baseline works, P10-2 layers excludes on top.

**Today's session ends here** with the locked plan committed. Implementation
deferred to when Mridul is on his Mac with bundle-trim verified locally.
