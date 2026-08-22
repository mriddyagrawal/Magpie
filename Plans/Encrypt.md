# Encrypt — local-first IP & data protection plan

> **Status:** Draft, 2026-05-02. Living doc — extend over time.
> **What this is.** The plan for protecting Magpie's code, data, and model files
> once we ship a downloadable installer. Pairs with [Port.md](Port.md) (cross-platform
> distribution) and [IO - Privacy.md](../IO/IO%20-%20Privacy.md) (user-data privacy
> guarantees).

---

## Why this exists

Magpie is a **local-first** product. Once we ship a `.dmg` / `.exe` / `.deb`,
the binary lives on the user's machine — and so does our Python source if we do
nothing. Three concrete things go wrong if we ignore this:

1. A competitor decompiles `.pyc` in 60 seconds with `uncompyle6` and clones
   our two-layer indexing architecture.
2. Another app or another user on the same machine reads the user's local Qdrant
   index — every summary, every embedding, every file path — because Qdrant has
   **no native at-rest encryption**.
3. A cracker strips the license check, redistributes the `.app`, and the $29/mo
   tier becomes free for anyone who searches "magpie crack".

This doc is the layered defense against those three.

---

## What we ARE protecting

These are the assets that justify real engineering effort:

| Asset | Where it lives | Why it's a moat |
|---|---|---|
| **Two-layer summary architecture** | `src/stage1/summarize.py`, `src/pipeline.py` | The whole "summarize first, descend on hit" pattern that makes us cheaper than naive RAG at scale |
| **Lazy-chunking page picker** | `src/content.py:extract_pdf_relevant_pages` + `_looks_like_toc_page` | The smart bit that finds the right pages of a textbook instead of dumping the front matter |
| **Adaptive query classifier** | `src/stage2/query_classify.py` (regex patterns + class config) | Years of real-transcript tuning encoded in regex. Easy to copy if visible. |
| **`.nasignore` walker logic** | `src/stage1/...` (file walker) | Decides what gets indexed vs skipped. Trivial to mimic if source is open. |
| **Daemon RPC protocol** | `src/daemon/protocol.py`, `src/daemon/server.py` | Hot-model architecture is our search-as-you-type unlock |
| **Stage-3 video / colpali pipeline** | `src/stage3/...` | The visual-tier flow that handles images and frames |
| **Tier orchestration** | Tier-1 / Tier-2 / Tier-3 routing logic | How we decide which tier services which query |
| **User's local index** | Qdrant data dir, embeddings, summaries on disk | Sensitive personal data — financials, contracts, photos. Privacy promise depends on this. |
| **License & activation logic** | License keys, hardware binding | Pure anti-piracy |

---

## What we are explicitly NOT protecting

Spend zero effort on these. They're either uncopyable-anyway or a distraction.

- **Model identity (mostly).** If we ship Llama 3.1 8B or Phi-3, that's
  open-source and a competitor can grab it for free. Hiding the model name is
  a mild speed bump, not a moat. (See "Model confusion" below for the small
  cost-effective version we'll do.)
- **The high-level architecture.** It's already in [CLAUDE.md](../CLAUDE.md)
  and our pitch deck. Anyone who reads our marketing knows we use summary +
  embedding + path. Don't pretend the idea is the secret.
- **Open-source library code.** Pydantic, FastEmbed, Qdrant client — all public.
- **The pipeline shape.** Documented in [IO/IO - Stage 1.md](../IO/IO%20-%20Stage%201.md),
  [IO - Stage 2.md](../IO/IO%20-%20Stage%202.md), etc. — public design.

The moat is *execution speed and tuning*, not the algorithm. Compilation buys
us **time to ship the next version** before anyone copies the current one.

---

## Layered defense

Five layers, each independent. Ship them in priority order; each one raises
the cost-to-copy.

### Layer 1 — Compile Python to native binary

| Tool | Role | Notes |
|---|---|---|
| **Nuitka** | Whole-app compile to standalone executable | Compiles unmodified Python 3 → C → native binary. "Almost as hard to decompile as C++." Standard pipeline. |
| **PyArmor** | Extra obfuscation on hot-IP modules | Add on top of Nuitka for `query_classify.py`, `summarize.py`, the file walker, and the daemon protocol. Hardware-binding option doubles as license enforcement. |
| **Cython** *(alt)* | Per-module C extensions | Faster runtime than Nuitka; trickier packaging. Considered for the stage-2 hot path if profiling shows wins. |

**Decision:** Nuitka for the app, PyArmor on top of the architecture-revealing
modules. Belt-and-suspenders. Nuitka kills the trivial decompile path; PyArmor
slows down assembly-level reverse engineering on the parts we care most about.

Cost-to-copy for a competent attacker: **~1 minute → ~3 weeks.**

### Layer 2 — Code signing & notarization

Non-negotiable. Without it, ~80% of users close the app at the first OS
warning.

| Platform | Cert / mechanism | Annual cost |
|---|---|---|
| **macOS** | Apple Developer ID + `xcrun notarytool` notarization | $99 / yr |
| **Windows** | Authenticode EV cert (hardware token) | $400–$700 / yr |
| **Linux** | GPG-sign `.deb` / `.rpm`; Flatpak / Snap repos | Free |

**macOS-specific:** Python apps need the hardened-runtime entitlement
`com.apple.security.cs.allow-unsigned-executable-memory` because the
interpreter generates code at runtime. Sign inside-out (innermost binaries
first). Always timestamp signatures.

**Test on a clean machine.** Your dev machine has the cert in its keychain so
signing problems hide locally. Always validate the CI-built artifact on a
machine that's never seen your developer cert.

### Layer 3 — Local data encryption (Qdrant, summaries, embeddings)

Qdrant has **no native at-rest encryption** for local deployments
([Qdrant issue #3139](https://github.com/qdrant/qdrant/issues/3139)). The
user's index, every summary, every embedding sits as plaintext on disk by
default. We have to wrap it.

**Approach: encrypt the Qdrant data directory ourselves, decrypt on daemon
startup with a key from the OS keychain.**

| OS | Keychain mechanism | Library |
|---|---|---|
| macOS | Keychain Services | `keyring` (Python) or `security` CLI |
| Windows | DPAPI | `pywin32` |
| Linux | Secret Service / libsecret / KWallet | `keyring` |

Flow:

1. First run: generate a 256-bit key, store in OS keychain under
   `notspotlight.encryption-key`. **Never write the key to disk.**
2. Encrypt the Qdrant `storage/` directory using `age` or `libsodium`
   (AES-256-GCM or XChaCha20-Poly1305).
3. On daemon startup: read key from keychain, decrypt to a tmpfs / memory-only
   mount, run Qdrant against that, re-encrypt on shutdown.
4. Sidecar metadata (e.g., file-mtime cache, settings) — same key, SQLCipher.

Trade-off: roughly +1–2 sec daemon cold start. With our daemon design this is
fine — pays once per idle-shutdown cycle, not per query.

Alternative considered & rejected: **rely on OS-level full-disk encryption**
(FileVault, BitLocker, LUKS). Too weak — protects only against physical theft,
not against another app on the same logged-in user account.

### Layer 4 — License keys & activation

| Provider | Why | Pricing |
|---|---|---|
| **Lemon Squeezy** ⭐ | Native license-key API, activation limits, indie-friendly, Merchant of Record (handles tax) | 5% + $0.50 per transaction |

Implementation rules:

- **Hard-code our `store_id`, `product_id`, and `variant_id`** in the binary
  so a license from another LS product can't unlock Magpie.
- **Activation cap:** 3 devices per individual license. Pro tier: configurable.
- **Hardware-bound license file** for the lifetime tier — combine
  Lemon Squeezy validation with PyArmor's machine-binding so a single license
  can't be cracked once and shared infinitely.
- **Validate at startup AND once per 24h** at runtime. Cache validation result;
  graceful offline mode (we don't lock people out for being on a plane).
- **Refund / deactivation flow:** customer-facing "deactivate device" UI in the
  app so they can move between machines without contacting support.

### Layer 5 — Model-file obfuscation *("confuse people for models")*

The honest answer to *"can we download the correct model but still confuse
people about which model it is?"* is: **partially yes, and it costs us
~30 minutes of effort. Past that, diminishing returns hard.**

#### What works (~30 min, do this)

1. **Self-host the model.** Don't link to HuggingFace at runtime; serve from
   `models.usemagpie.com` (or whichever CDN). Cuts the public URL trail.
2. **Rename the file.** `Llama-3.1-8B-Instruct-Q4_K_M.gguf` → `magpie-core-v1.bin`.
   Anyone running `ls` on the install dir sees only Magpie-named artifacts.
3. **Strip GGUF metadata.** GGUF files have a `general.architecture` and
   `general.name` field. Use `gguf-py` or a small script to blank them or
   override to `magpie-internal`. Tensor names stay (they're load-bearing) but
   the "this is Llama" signage at the top of the file goes.
4. **Encrypt the model file at rest.** Apply the same Layer-3 key to encrypt
   the model file when it's at rest on disk; decrypt on daemon startup into a
   memory-mapped buffer.

#### What doesn't really work (don't waste time)

- Tensor shapes are a fingerprint. A 4096-dim hidden state with 32 attention
  heads and 14336 FFN size *is* Llama 3.1 8B no matter what we name the file.
  An attacker running `gguf-dump` reconstructs the architecture from shapes.
- Behavioral fingerprinting. Feed any LLM a known prompt ("Write a poem about
  a cat in the style of Walt Whitman") and compare the output to public model
  outputs. Identifies the family in seconds.
- "Wrapping" the model in a custom format buys nothing once the binary has to
  decode it — the decoder is in our (compiled but reverse-engineerable) code.

#### License compliance is non-negotiable

If we ship Llama, the **Llama 3.1 Community License** *requires* attribution
and license text included. Hiding the model name in the file is fine; failing
to include the upstream license is not. Same for Mistral (Apache 2.0 — easier),
Phi-3 (MIT — easiest), Qwen (Apache 2.0).

**Recommended:** ship `LICENSES/` folder with all upstream licenses next to
the renamed model file. The folder is the legal cover; the renamed binary is
the friction layer.

#### Verdict

Yes, do steps 1–4. They're cheap and they keep casual users — and most
journalists and bloggers — from immediately writing *"Magpie is just Llama
3.1 with extra steps."* That's a real PR win even though it's not a
real security one. Don't go further.

---

## Implementation phases

Priority order — each phase is independently shippable:

### Phase 1 — Don't ship plaintext source *(week 1, blocking for any release)*
- [ ] Nuitka build pipeline integrated into `justfile`
- [ ] PyArmor on `query_classify.py`, `summarize.py`, `content.py`, `daemon/protocol.py`
- [ ] Smoke test: `strings <binary> | grep extract_pdf_relevant_pages` returns nothing meaningful
- [ ] Smoke test: `uncompyle6` on any artifact in the bundle fails

### Phase 2 — Don't get blocked by Gatekeeper / SmartScreen *(week 2)*
- [ ] Apple Developer Program enrollment, Developer ID Application cert
- [ ] `xcrun notarytool` workflow in CI; signed `.dmg`
- [ ] Authenticode EV cert + hardware token
- [ ] Signed `.exe` / `.msi` in CI
- [ ] Test artifact on a clean Mac and clean Windows VM (no dev tools)

### Phase 3 — User data sovereignty *(weeks 3–4)*
- [ ] OS keychain abstraction (`src/encryption/keystore.py`?) with macOS / Windows / Linux backends
- [ ] Encrypted Qdrant data dir on daemon start/stop
- [ ] SQLCipher for any sidecar SQLite metadata
- [ ] Migration path for existing users' plaintext indexes (decrypt-once-on-upgrade)
- [ ] Tests: kill the daemon mid-write, confirm we can recover or fail safe

### Phase 4 — Anti-piracy *(week 5)*
- [ ] Lemon Squeezy product set up with activation limits
- [ ] License-validation client in the app (cached + offline-friendly)
- [ ] Hardware-binding via PyArmor
- [ ] In-app "deactivate device" UI
- [ ] Test: install on 4 machines, confirm 4th gets blocked

### Phase 5 — Model obfuscation *(half-day)*
- [ ] Self-hosted model CDN (`models.usemagpie.com` or signed S3 URLs)
- [ ] Rename + strip GGUF metadata script in CI
- [ ] Encrypt model file with Layer-3 key
- [ ] Ship `LICENSES/` folder with upstream model license text

---

## Open questions / things still TBD

> Add to this list as we hit decisions. Resolve in pull requests, not in this
> doc.

1. **Tauri shell vs. pure Python distribution.** Tauri gives us better
   sandboxing + smaller installers + mobile path for Wave 2, but adds Rust
   to the stack. Decide before Phase 1 ships, because Nuitka config differs.
2. **Update mechanism.** Sparkle (mac), WinSparkle (win), Tauri updater,
   custom?  Must be over TLS with signed manifest.
3. **What happens if the user's keychain gets corrupted / wiped?** Currently
   means total index loss. Acceptable? Or do we want a recovery passphrase
   they can write down once?
4. **Auto-rotation of the encryption key.** If we ever leak a key, we want
   to push a re-encrypt. How — versioned key IDs in the data header?
5. **Telemetry & tamper detection.** Do we phone home a hash on startup so
   we know when binaries have been modified? Trade-off vs. "private by
   default" brand promise.
6. **Beta releases — sign or skip?** Probably sign even betas; Gatekeeper
   warnings on early adopters tank trust during the most critical phase.
7. **What about colpali / fast-tier model** which is much larger (~2.5 GB)?
   Encrypting at rest costs disk space (no compression possible after
   encryption). Acceptable?
8. **Linux distribution path.** AppImage / Flatpak / Snap / `.deb`? Pick one
   primary; support others lazily.

---

## Cross-references

- [Plans/Port.md](Port.md) — cross-platform distribution
- [IO/IO - Privacy.md](../IO/IO%20-%20Privacy.md) — what we promise users about their data
- [IO/IO - Daemon.md](../IO/IO%20-%20Daemon.md) — daemon lifecycle (where Layer-3 decryption lives)
- [IO/IO - Repo Structure.md](../IO/IO%20-%20Repo%20Structure.md) — where each protected module lives
- [src/daemon/paths.py](../src/daemon/paths.py) — existing authkey + 0o600 socket perms (good baseline; extend for keystore)
- [CLAUDE.md](../CLAUDE.md) — product-level vision, ICP, monetization model
