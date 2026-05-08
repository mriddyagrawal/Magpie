# Plan #10 — Self-contained Packaging (Brainstorm)

> **Status:** Brainstorm / scoping doc, not yet a locked design. Sister doc to
> [`Plans/Bundle Trim/Implementation Plan.md`](../Bundle%20Trim/Implementation%20Plan.md)
> — bundle-trim shrinks the venv we'll bundle; this plan turns that venv into
> shippable installers (`.dmg` / `.AppImage` / `.exe` / `.msi`).
>
> **Owner:** Mridul (distribution pipeline focus).
>
> **Status of sibling work:** bundle-trim PR-A/B/C/D/F all shipped on branch
> `bundle-trim`. Production install is now ~1.3 GB. PR-E (PyInstaller
> excludes) lives in this plan, not in bundle-trim — because excludes only
> make sense once a `.spec` file exists.

---

## 1. Why we need this

Today's "build" path:
- `pnpm tauri build` produces a `Magpie.app` shell.
- The Tauri Rust shell spawns the sidecar via `Command::new("uv").args(["run", "python3", "-m", "src.server"])` — see [frontend/src-tauri/src/lib.rs:145](../../frontend/src-tauri/src/lib.rs#L145).
- That assumes `uv` is in `PATH` and the project source tree is reachable.
- **On a stranger's Mac without dev tools, the sidecar silently fails to start.** The window opens, search returns 503, the app appears broken.

Goal: a `.dmg` (and Linux/Windows equivalents) where the user double-clicks → the app works. No "install Python," no "install uv," no "clone the repo."

This is the gating constraint for shipping to non-developers.

---

## 2. The five sub-problems

A self-contained desktop bundle has five layers, each with a packaging decision:

### 2.1 Python interpreter — bundle CPython 3.11 inside the `.app`

**Options:**
- **PyInstaller** — most popular for Python desktop apps. One-file or one-dir mode. Cross-platform.
- **Nuitka** — compiles Python to C; faster startup, harder to debug.
- **PyOxidizer** — Rust-based, less maintained these days.
- **`python-build-standalone`** — just ship a relocatable Python interpreter (e.g. via `uv python install --target ...`) and our source tree alongside.

**Probable pick:** PyInstaller, one-folder mode. Already in dev-deps as `pyinstaller>=6.0` (now in the `packaging` opt-in group).

### 2.2 Python source — bundle `src/` and `cli/` next to the interpreter

PyInstaller packs them into the bundle. The `--collect-all <pkg>` and `--add-data` flags handle our edge cases (e.g. `magpie_defaults.json`).

### 2.3 Native binaries — Qdrant, llama-server

Both currently downloaded out-of-band by `just qdrant-install` and `just llama-server-install`. For a packaged `.app`, the build pipeline:
1. Downloads the right-arch binary at build time
2. Stages it inside `Magpie.app/Contents/Resources/bin/`
3. Tauri's Rust spawn code finds it via a relative path

### 2.4 Resources — `magpie_defaults.json`, prompts, icons

`src/config/magpie_defaults.json` lives in source today. PyInstaller's `--add-data` flag bundles it, and `_config_dir()` in `src/config/indexing_rules.py` resolves it via `Path(__file__).parent` either way (works in source tree AND inside a frozen bundle, because PyInstaller preserves relative paths).

Need to verify this assumption end-to-end during PR-E.

### 2.5 Code signing & notarization

- **macOS:** Apple Developer ID signature → notarization → stapled ticket. Otherwise users get the "damaged / unidentified developer" Gatekeeper warning. ~$99/yr.
- **Windows:** EV code signing certificate (~$200–500/yr) to dodge SmartScreen. Without one, users get "unrecognized publisher."
- **Linux:** Optional GPG signature on the `.AppImage` or `.deb`; users mostly trust source.

This is *real money* and requires real identities. Out of scope for the immediate brainstorm but needs a budget owner before we ship publicly.

---

## 3. PR-E (PyInstaller `excludes`) — the bundle-trim follow-on

PyInstaller analyzes our imports and pulls in everything reachable. By default, that includes ~200 MB of unused submodules. The `.spec` file's `Analysis(excludes=[...])` strips them.

### Candidate excludes (validate before adding)

| Module | Why exclude | Risk if wrong |
|---|---|---|
| `torch.distributed` | Multi-node training; we never call it | Low — would error only if multi-node code path runs |
| `torch.onnx` | ONNX export; we never export | Low |
| `torch.fx` | Symbolic graph tracing; we never use `torch.compile` | Medium — some torch-internal code lazy-imports it; test on real workloads |
| `torch.profiler`, `torch.tensorboard` | Profiling tools | Low |
| `torch._dynamo` | `torch.compile` machinery | Medium — same as `torch.fx` |
| `torch.optim` | Training; we never train | Low |
| `torch.autograd.profiler` | Same as above | Low |
| `transformers.models.<unused arch>` | Trickier — `transformers` dynamically loads model classes by name | **High** — will break on first ColPali / sentence-transformers load; needs a careful narrow exclude |
| `sympy` | Used by torch's symbolic shapes only; we never use that path | Medium — torch may import it eagerly somewhere; benchmark cold-start before/after |
| `mpmath` | Transitive sympy | Medium |
| `IPython` (if it leaks into prod after PR-F) | Debug-only | Low |
| `babel` | i18n library; transitive somewhere; we don't translate | Low |

### Validation pattern for each exclude

1. Add to `Analysis(excludes=[...])`.
2. Run `pyinstaller magpie.spec`.
3. Launch the bundle on a clean test box.
4. Run an end-to-end smoke: ingest a tiny corpus, run a query, open T4 (image) tier.
5. If something errors with `ImportError` → narrow the exclude (use a more specific submodule path, e.g. `torch.distributed.tensor` instead of `torch.distributed`).
6. If everything works → keep.

### Estimated savings

- Aggressive case (all the above work cleanly): ~200–300 MB stripped from the `.app`.
- Realistic case (some excludes needed to be narrowed): ~100–150 MB.

Either way: meaningful, but secondary to the bundle-trim wins from PR-A/B/C/D/F. The combined goal is a **`.dmg` ≤ 350 MB** for the default Mac/CPU build.

---

## 4. Plan #10 PR breakdown (proposed)

Each PR is small enough to ship individually so the build pipeline matures incrementally.

| PR | Scope | Output |
|---|---|---|
| **P10-1** | First-pass PyInstaller `.spec` for macOS one-folder mode | `Magpie.app` that launches and shows the GUI on the dev's Mac (no signing yet) |
| **P10-2** | PR-E excludes — apply the candidate list, validate one at a time | Same `.app`, ~150–250 MB smaller |
| **P10-3** | Bundle Qdrant + llama-server binaries into `Resources/bin/` | `.app` works end-to-end without `just qdrant-install` etc. |
| **P10-4** | Cross-platform: Linux `.AppImage` + Windows `.msi` | Three installer formats, dev-signed only |
| **P10-5** | Apple Developer signing + notarization wiring in CI | `.dmg` users can open without Gatekeeper warnings |
| **P10-6** | Auto-updater (Tauri's built-in) — release endpoint, signing keys | Users get updates without re-downloading |
| **P10-7** | First-launch onboarding flow (paired with Rahul on UI side) | New users see folder picker + model warm-up progress, not a silent broken app |

---

## 5. Open questions before locking

1. **One-folder vs one-file PyInstaller mode?** One-folder = faster startup, slightly larger; one-file = single executable but extracts to temp on each launch (~3 s slower cold start). Probably one-folder for desktop UX.

2. **Where does `.dmg` host live?** GitHub Releases (free, slow downloads outside US), self-hosted on Fly/CloudFront ($20/mo, faster), homebrew-cask (free + community-managed)?

3. **Auto-updater scope?** Magpie's frontend changes weekly; sidecar Python changes monthly; native binaries (Qdrant, llama-server) change rarely. A naive "replace the whole .app" updater is heavy. Differential updates are nice-to-have, not MVP.

4. **Does the bundled Python need to handle `peft` / `colpali-engine` LoRA-loading correctly under PyInstaller?** Some HF libraries do `__file__`-based path resolution that breaks under frozen bundles. Will surface in P10-2 testing.

5. **Bundle the HF model cache or not?** We agreed in bundle-trim plan §2 to NEVER bundle the ~5 GB cache. First-launch UX has to handle the download gracefully (P10-7).

6. **Universal2 macOS binary (Intel + Apple Silicon)?** Or two separate `.dmg`s (one per arch)? Universal2 is bigger but simpler distribution; two binaries is leaner. Probably start with two arch-specific `.dmg`s.

---

## 6. What to do next, concretely

When Mridul is ready to start P10-1 on his Mac:

1. **Verify bundle-trim landed cleanly** on Mac (`uv sync` produces ~1.3 GB venv, tests pass, Tauri dev launches).
2. **Spike a one-folder PyInstaller `.spec`** for macOS only — get a `Magpie.app` that launches and shows the GUI. Doesn't have to work end-to-end yet, just has to launch without an immediate ImportError.
3. **From that working baseline**, add PR-E excludes one at a time, validating each.
4. **Then** broaden to Linux `.AppImage` and Windows `.msi`.

The bundle-trim work is a prerequisite (smaller venv = smaller bundle = faster CI). Now that it's shipped, P10-1 is unblocked.
