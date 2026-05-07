# NotAnotherSpotlight — command runner

# Auto-load .env into every recipe's environment. Without this, recipes
# that shell out to `python -c "..."` snippets (reset-index, qdrant-counts,
# recover-fast-tier, disk-usage, manifest-stats, fast-tier-files, etc.)
# never see HF_TOKEN / OPENROUTER_API_KEY / other LLM keys, because they
# bypass the CLI entrypoints that call `load_dotenv()` themselves. `just
# sync` etc. work without this because they invoke `python -m src.ingest`,
# which loads dotenv from inside main(). Once the app is packaged
# (Plan #10), `.env` goes away — see Plans/Future Plans.md #19 for the
# JSON-config + keychain-secrets replacement.
set dotenv-load

# Install all dependencies (Python venv + CLI tool). Renamed from `sync`
# in 2026-05 — `sync` now means "ingest everything in indexing_rules.json".
# See Plans/Ingestion Rules/Implementation Plan.md.
sync-environment:
    uv sync
    uv pip install -e cli

# Reinstall llama-cpp-python with the right hardware-acceleration flag for
# the current platform. Run this AFTER `just sync-environment` if you want
# Metal/CUDA acceleration — otherwise pip installs a CPU-only build that
# works but is much slower for local LLM inference.
#
#   macOS Apple Silicon → Metal
#   Linux + nvidia-smi  → CUDA
#   anything else       → CPU (no-op, the wheel is fine)
#
# See Plans/Local LLM Plan.md.
install-llama:
    #!/usr/bin/env bash
    set -euo pipefail
    OS="$(uname -s)"
    ARCH="$(uname -m)"
    if [ "$OS" = "Darwin" ] && [ "$ARCH" = "arm64" ]; then
        echo "==> macOS Apple Silicon: building llama-cpp-python with Metal"
        CMAKE_ARGS="-DGGML_METAL=on" \
            uv pip install --force-reinstall --no-cache-dir llama-cpp-python
    elif [ "$OS" = "Linux" ] && command -v nvidia-smi >/dev/null 2>&1; then
        echo "==> Linux + CUDA detected: building llama-cpp-python with CUDA"
        CMAKE_ARGS="-DGGML_CUDA=on" \
            uv pip install --force-reinstall --no-cache-dir llama-cpp-python
    else
        echo "==> CPU build (no GPU acceleration detected)"
        uv pip install --force-reinstall --no-cache-dir llama-cpp-python
    fi
    echo "==> done. Verify with: uv run python -c 'from llama_cpp import Llama; print(Llama.__module__)'"

# Walk every enabled include_paths entry in indexing_rules.json. This is
# the "do everything" command — replaces running `just walk <path>` once
# per directory. Reads from $MAGPIE_DATA_DIR/indexing_rules.json (default
# ~/.local/share/Magpie on Linux, ~/Library/Application Support/Magpie on
# macOS). If no include_paths are configured, prints a hint and exits 0.
#
# Any extra args pass through to `python -m src.ingest`. So:
#   just sync                  → default walk
#   just sync --include-data   → also index .json/.csv/.dat (data category)
#   just sync --force          → re-summarize even unchanged files
#   just sync -v               → verbose per-file routing decisions
# A single failed walk doesn't abort the rest — each include_path runs
# independently, mirroring the prior `subprocess.run(check=False)` behavior.
sync *args:
    #!/usr/bin/env bash
    set -uo pipefail
    paths=$(uv run python -c "
    from src.config import load_user_rules
    for ip in load_user_rules().include_paths:
        if ip.enabled:
            print(ip.path)
    ") || exit 1
    if [ -z "$paths" ]; then
        echo "No included folders configured. Add one with: just walk <folder>"
        exit 0
    fi
    while IFS= read -r path; do
        echo "== walking $path =="
        uv run python -m src.ingest "$path" {{args}} || true
    done <<< "$paths"

# Check whether a single file or folder will be indexed under the current
# rules. Prints the (allowed/skipped) decision and the reason that fired
# (which rule layer rejected/accepted it). Useful for debugging "why isn't
# this file showing up in search?" without running a real walk.
#
# Example: just check ~/Documents/secret.pdf
check path:
    @uv run python -m scripts.check_indexing "{{path}}"

# Walk a directory and print the (allow/skip + reason) decision for every
# file inside, without running any LLM/embedding/Qdrant work. The dry-run
# explainer — answers "if I ran sync now, exactly what would happen?"
#
# Example: just check-dir ~/Documents
check-dir path:
    @uv run python -m scripts.check_indexing --recursive "{{path}}"

# Run all tests
test:
    uv run pytest tests/ -v

# Run stage2 tests only
test-stage2:
    uv run pytest tests/stage2/ -v

# Walk a folder end-to-end: discover -> route -> summarize -> upsert.
walk path:
    uv run python -m src.ingest "{{path}}"

# Walk including .json/.csv/.dat (default-skipped data files).
walk-data path:
    uv run python -m src.ingest "{{path}}" --include-data

# Re-encode every file under this root, including T4 ColPali pages.
walk-force path:
    uv run python -m src.ingest "{{path}}" --force

# Drop Qdrant collections + clear manifest under this root, then re-ingest.
walk-rebuild path:
    uv run python -m src.ingest "{{path}}" --rebuild

# Full reset: drop ALL Qdrant collections (summaries + fast_tier), clear
# the manifest, delete every summary markdown. Use when the manifest has
# drifted (test pollution, schema changes like the 2026-05 row_index →
# chunk_index rename) and you want a clean slate.
#
# DOES NOT touch:
#   - indexing_rules.json (your include_paths / exclude_paths stay)
#   - the GGUF / HF model cache (no re-download)
#   - source files on disk
#
# Different from `just sync --force`, which re-summarizes existing files
# but doesn't drop collections, clear the manifest, or delete markdowns.
#
# After running, your next `just sync --include-data` rebuilds everything.
reset-index: qdrant-up
    @uv run python -c "\
    from src.pipeline import reset; \
    s = reset(); \
    print(f'manifest removed:             {s[\"manifest_removed\"]}'); \
    print(f'summaries deleted:            {s[\"summaries_deleted\"]}'); \
    print(f'summaries collection dropped: {s[\"collection_dropped\"]}'); \
    print(f'fast_tier collection dropped: {s[\"fast_tier_dropped\"]}'); \
    print(f'qdrant error:                 {s[\"qdrant_error\"]}') if s.get('qdrant_error') else None; \
    print(); \
    print('indexing_rules.json untouched. Next: just sync --include-data')\
    "

# Per-child mode: ingest each immediate subdirectory of <path> sequentially.
# Useful for huge multi-TB roots where a single walk feels stuck.
walk-each path:
    uv run python -m src.ingest "{{path}}" --per-child

# Dry-run: print the ingest command for each immediate subdirectory and exit.
walk-preview path:
    uv run python -m src.ingest "{{path}}" --list-children

# Router-only inspection: show what tier each file under <path> would route to.
# No writes, no LLM calls. Use to estimate cost before a big walk.
walk-explain path:
    uv run python -m src.router "{{path}}"

# Walk with per-file routing decisions printed (tier + scores + criticality).
walk-verbose path:
    uv run python -m src.ingest "{{path}}" -v

# Push existing summaries into Qdrant (Stage 2 only — no walk, no summarize).
# Pass extra flags through, e.g. `just ingest -v` for per-file verbose output.
ingest *args:
    uv run python -m src.stage2 ingest {{args}}

# Force re-ingest (drop + recreate Qdrant collection from existing summaries).
ingest-force *args:
    uv run python -m src.stage2 ingest --force {{args}}

# Search documents
search q:
    uv run python -m src.stage2 search "{{q}}"

# ----------------------------------------------------------------------------
# Daemon — keeps search models hot across CLI invocations so subsequent
# queries are sub-second instead of paying ~3-5s of model load each time.
# Auto-spawns on first use; auto-shuts down after 15 min idle (override with
# NS_DAEMON_IDLE_MINUTES; 0 disables idle shutdown).
# ----------------------------------------------------------------------------

# Start the daemon (no-op if already running). Idempotent.
daemon-start:
    uv run python -m src.daemon --detach

# Show whether the daemon is running, plus uptime / idle countdown.
# `-` prefix suppresses just's complaint when the daemon isn't running
# (exit code 1 is the intentional "not running" signal for shell scripts).
[no-exit-message]
daemon-status:
    uv run python -m src.daemon --status

# Ask the running daemon to shut down cleanly. Releases ~250 MB - 3 GB of RAM.
daemon-stop:
    uv run python -m src.daemon --stop

# Tail the daemon's log (errors, dispatch crashes, model-load failures).
daemon-log:
    @tail -f "$(uv run python -c 'from src.daemon.paths import daemon_log_path; print(daemon_log_path())')"

# Summarize a file or directory (Stage 1)
summarize path:
    uv run python src/stage1/summarize.py "{{path}}"

# Launch interactive CLI
chat:
    uv run notspotlight

# Start the FastAPI sidecar (the backend that the Tauri GUI talks to).
# Data goes to APP_DATA_DIR (~/.local/share/Magpie on Linux). Override
# with MAGPIE_DATA_DIR=/some/path if you want a different location.
serve:
    uv run uvicorn src.server:app --port 8765

# Same as `serve`, but auto-reloads on src/ changes — use during dev.
serve-dev:
    uv run uvicorn src.server:app --port 8765 --reload

# One-shot: launch the Magpie window. Tauri auto-spawns its own Python
# sidecar internally (see frontend/src-tauri/src/lib.rs), so this is a
# single process / single terminal. Logs from both Tauri and the
# sidecar interleave in this same window. ⌥Space summons the window
# (or hides it). Ctrl-C kills everything cleanly.
#
# Want hot-reload of Python code? That needs `just serve-dev` in a
# separate terminal AND a small lib.rs change to make Tauri skip its
# auto-spawn. See the note in the recipe — ask if you want it.
run-magpie:
    cd frontend && pnpm tauri dev

# Start Magpie Cloud (the LLM-orchestration backend that holds prompts
# and proxies LLM calls). Different process from `just serve` — that
# one is the LOCAL desktop sidecar; this one is the REMOTE server the
# desktop app talks to. See server/README.md for what each is for.
cloud-serve:
    cd server && uv run uvicorn magpie_server.main:app --port 8000 --reload

# Run the desktop CLI through the local Magpie Cloud (instead of
# direct-to-OpenRouter). Pair with `just cloud-serve` running in
# another terminal. Useful for verifying the full cloud-mode flow
# end-to-end on a single laptop.
chat-cloud:
    LLM_PROVIDER=magpie-cloud \
    MAGPIE_CLOUD_URL=http://127.0.0.1:8000 \
    MAGPIE_INVITE_CODE="${MAGPIE_INVITE_CODE:-dev-anonymous}" \
    uv run notspotlight

# Install global aliases (notspotlight, ns, nas) via uv tool
install:
    uv tool install -e cli --force
    @echo "Installed! You can now run: notspotlight, ns, or nas from anywhere."

# Uninstall global aliases
uninstall:
    uv tool uninstall notspotlight

# ----------------------------------------------------------------------------
# Qdrant standalone server (lives on /mnt/hardisk to avoid filling the root drive)
# Same Rust binary as Qdrant Cloud — supports int8/fp16/binary quantization,
# unlike the embedded Python local mode. Spawned as a background process; no
# Docker. The same subprocess pattern is what we'll bundle for end-user
# distribution later (see backlog E5).
# ----------------------------------------------------------------------------

# Resolve the app's data directory once.
DATA_DIR         := `uv run python -c 'from src.manifest import APP_DATA_DIR; print(APP_DATA_DIR)'`
SUMMARIES_DIR    := `uv run python -c 'from src.manifest import SUMMARIES_DIR; print(SUMMARIES_DIR)'`
MANIFEST_PATH    := `uv run python -c 'from src.manifest import DEFAULT_MANIFEST_PATH; print(DEFAULT_MANIFEST_PATH)'`

# Where to keep the Qdrant binary, data, and pidfile. Defaults to a subfolder 
# in the app's data directory. Override with QDRANT_HOME env var.
QDRANT_HOME      := env_var_or_default("QDRANT_HOME", DATA_DIR / "qdrant")
QDRANT_BIN       := QDRANT_HOME / "qdrant"
QDRANT_DATA      := env_var_or_default("QDRANT_DATA", QDRANT_HOME / "storage")
QDRANT_LOGS      := QDRANT_HOME / "qdrant.log"
QDRANT_PIDFILE   := QDRANT_HOME / "qdrant.pid"
QDRANT_VERSION   := "v1.17.1"
# 6433/6434 instead of Qdrant's default 6333/6334. OpenWhispr ships its own
# bundled Qdrant on the default ports; co-existing on the same machine on
# defaults caused Magpie to silently write into OpenWhispr's storage tree.
# These ports are Magpie-only. See Plans/Future Plans.md #18 for the
# layer-2 auth follow-up.
QDRANT_PORT      := "6433"
QDRANT_GRPC_PORT := "6434"

# Download the Qdrant standalone binary onto QDRANT_HOME (one-time, ~30 MB).
qdrant-install:
    @mkdir -p "{{QDRANT_HOME}}"
    @if [ -x "{{QDRANT_BIN}}" ]; then \
        echo "Qdrant binary already at {{QDRANT_BIN}} — delete it first if you want to reinstall."; \
        "{{QDRANT_BIN}}" --version; \
    else \
        echo "Downloading Qdrant {{QDRANT_VERSION}} into {{QDRANT_HOME}}..."; \
        OS=`uname -s | tr '[:upper:]' '[:lower:]'`; \
        ARCH=`uname -m`; \
        if [ "$ARCH" = "arm64" ]; then ARCH="aarch64"; elif [ "$ARCH" = "x86_64" ]; then ARCH="x86_64"; fi; \
        FILE="qdrant-$ARCH-apple-darwin.tar.gz"; \
        if [ "$OS" = "linux" ]; then FILE="qdrant-$ARCH-unknown-linux-gnu.tar.gz"; fi; \
        curl -L -o "{{QDRANT_HOME}}/qdrant.tar.gz" \
            "https://github.com/qdrant/qdrant/releases/download/{{QDRANT_VERSION}}/$FILE"; \
        tar -xzf "{{QDRANT_HOME}}/qdrant.tar.gz" -C "{{QDRANT_HOME}}"; \
        rm "{{QDRANT_HOME}}/qdrant.tar.gz"; \
        chmod +x "{{QDRANT_BIN}}"; \
        echo "Installed: \"{{QDRANT_BIN}}\" --version"; \
        "{{QDRANT_BIN}}" --version; \
    fi

# Start Qdrant as a background process. Data + logs go to QDRANT_DATA/QDRANT_LOGS.
qdrant-up:
    @mkdir -p "{{QDRANT_DATA}}"
    @if [ -f "{{QDRANT_PIDFILE}}" ] && kill -0 $(cat "{{QDRANT_PIDFILE}}") 2>/dev/null; then \
        echo "Qdrant already running (pid $(cat "{{QDRANT_PIDFILE}}")). Use 'just qdrant-status' to inspect."; \
    elif [ ! -x "{{QDRANT_BIN}}" ]; then \
        echo "Qdrant binary missing at {{QDRANT_BIN}}. Run 'just qdrant-install' first."; \
        exit 1; \
    else \
        echo "Starting Qdrant on port {{QDRANT_PORT}} (gRPC {{QDRANT_GRPC_PORT}}), data at {{QDRANT_DATA}}..."; \
        QDRANT__STORAGE__STORAGE_PATH="{{QDRANT_DATA}}" \
        QDRANT__SERVICE__HOST="127.0.0.1" \
        QDRANT__SERVICE__HTTP_PORT="{{QDRANT_PORT}}" \
        QDRANT__SERVICE__GRPC_PORT="{{QDRANT_GRPC_PORT}}" \
            nohup "{{QDRANT_BIN}}" > "{{QDRANT_LOGS}}" 2>&1 & \
            echo $! > "{{QDRANT_PIDFILE}}"; \
        sleep 2; \
        if kill -0 $(cat "{{QDRANT_PIDFILE}}") 2>/dev/null; then \
            echo "Started (pid $(cat "{{QDRANT_PIDFILE}}")). Logs: {{QDRANT_LOGS}}"; \
            echo "Magpie reaches Qdrant on http://localhost:{{QDRANT_PORT}} by default. Override only if needed: QDRANT_CLUSTER_ENDPOINT=http://localhost:<port>"; \
        else \
            echo "Qdrant failed to start. Last 30 lines of {{QDRANT_LOGS}}:"; \
            tail -30 "{{QDRANT_LOGS}}"; \
            rm -f "{{QDRANT_PIDFILE}}"; \
            exit 1; \
        fi \
    fi

# Stop the running Qdrant process (graceful SIGTERM).
qdrant-down:
    @if [ -f "{{QDRANT_PIDFILE}}" ] && kill -0 $(cat "{{QDRANT_PIDFILE}}") 2>/dev/null; then \
        pid=$(cat "{{QDRANT_PIDFILE}}"); \
        echo "Stopping Qdrant (pid $pid)..."; \
        kill "$pid"; \
        for i in 1 2 3 4 5; do \
            kill -0 "$pid" 2>/dev/null || break; \
            sleep 1; \
        done; \
        if kill -0 "$pid" 2>/dev/null; then \
            echo "  still alive, sending SIGKILL"; \
            kill -9 "$pid"; \
        fi; \
        rm -f "{{QDRANT_PIDFILE}}"; \
        echo "Stopped."; \
    else \
        echo "Qdrant not running (no live pid in {{QDRANT_PIDFILE}})."; \
        rm -f "{{QDRANT_PIDFILE}}"; \
    fi

# Show current Qdrant status (running? collections? recent log lines?).
qdrant-status:
    @if [ -f "{{QDRANT_PIDFILE}}" ] && kill -0 $(cat "{{QDRANT_PIDFILE}}") 2>/dev/null; then \
        echo "Qdrant: RUNNING (pid $(cat "{{QDRANT_PIDFILE}}"), port {{QDRANT_PORT}})"; \
        echo; \
        echo "=== Collections ==="; \
        curl -sS "http://localhost:{{QDRANT_PORT}}/collections" | python3 -m json.tool 2>/dev/null || echo "(server not responding yet)"; \
        echo; \
        echo "=== Disk usage ==="; \
        du -sh "{{QDRANT_DATA}}" 2>/dev/null; \
        echo; \
        echo "=== Last 20 log lines ==="; \
        tail -20 "{{QDRANT_LOGS}}" 2>/dev/null; \
    else \
        echo "Qdrant: STOPPED"; \
        echo "Run 'just qdrant-up' to start (or 'just qdrant-install' first if not yet downloaded)."; \
    fi

# List fast-tier files ranked by pages indexed (biggest consumers first)
fast-tier-files:
    @uv run python -c "\
    import json; from pathlib import Path;\
    m = json.load(open('{{MANIFEST_PATH}}'));\
    files = [(e.get('fast_pages') or 0, p, e.get('size', 0)) for p, e in m.items() if e.get('fast_pages')];\
    files.sort(reverse=True);\
    print(f'{\"pages\":>6}  {\"est_mb\":>7}  {\"src_mb\":>7}  path');\
    print('-' * 100);\
    [print(f'{pages:>6}  {pages*0.993:>7.1f}  {sz/1024**2:>7.1f}  {p}') for pages, p, sz in files[:50]];\
    print();\
    total = sum(pg for pg,_,_ in files);\
    print(f'{len(files)} files, {total} pages total');\
    print(f'Top 10: {sum(pg for pg,_,_ in files[:10])*100/max(total,1):.0f}% of pages');\
    print(f'Top 50: {sum(pg for pg,_,_ in files[:50])*100/max(total,1):.0f}% of pages')\
    "

# Inspect the live Qdrant fast_tier config — shows the vector / quantization
# settings the running server actually has applied.
fast-tier-config:
    @uv run python -c "\
    from src.stage2.db import get_qdrant_client;\
    import json;\
    c = get_qdrant_client();\
    info = c.get_collection('fast_tier');\
    print('Points:    ', info.points_count);\
    print('Segments:  ', info.segments_count);\
    print();\
    print('VECTOR PARAMS (what we requested at create time):');\
    cfg = info.config.params.vectors;\
    print(json.dumps(cfg.model_dump() if hasattr(cfg, 'model_dump') else str(cfg), indent=2, default=str));\
    print();\
    print('COLLECTION-LEVEL QUANTIZATION (what is actually applied):');\
    qc = info.config.quantization_config;\
    print('  ', qc.model_dump() if qc else 'None');\
    "

# Rebuild manifest fast_indexed_at + fast_pages from Qdrant fast_tier — recovers
# from the pre-2026-04-25 mark_summarized bug that silently wiped fast-tier
# fields when a file was re-summarized. Vectors stayed in Qdrant; only the
# manifest forgot. This re-stamps the manifest from the surviving Qdrant data.
recover-fast-tier:
    @uv run python -c "\
    from src.manifest import Manifest;\
    m = Manifest();\
    stats = m.reconcile_from_fast_tier();\
    m.save();\
    print(f'recovered fast-tier state for {stats[\"recovered\"]} manifest entries');\
    print(f'qdrant points without manifest row: {stats[\"missing_in_manifest\"]} (manual cleanup if nonzero)');\
    "

# Drop manifest rows whose source files no longer exist on disk + delete the
# orphaned summary markdowns. Run this after deleting source files outside an
# `python -m src.ingest <root>` walk (e.g. when stale `/tmp/pytest-of-*` entries
# linger from earlier test runs). Qdrant orphans are cleaned automatically on
# the next `python -m src.stage2 ingest` run.
clean-stale-manifest:
    @uv run python -c "\
    from src.manifest import Manifest;\
    m = Manifest();\
    stats = m.clean_stale();\
    m.save();\
    print(f'cleaned manifest: dropped {stats[\"dropped\"]} stale entries, removed {stats[\"summaries_removed\"]} orphan summary markdowns');\
    print('run \'python -m src.stage2 ingest\' to also clean orphan Qdrant points (or do it on next ingest)');\
    "

# Inverse of clean-stale-manifest: clear `summary_file` pointers when the
# on-disk markdown is gone but the source file is still present. Symptom:
# Stage 2 ingest spams `warn: summary missing, skipping: ...` for files
# whose Test Summaries/<hash>_t1.md disappeared (manual cleanup, partial
# --rebuild, backup software treating Test Summaries/ as cache, etc.).
# Cleared rows are re-summarized on the next `python -m src.ingest <root>`.
# If the source ALSO vanished, the row is dropped entirely.
clean-stale-summaries:
    @uv run python -c "\
    from src.manifest import Manifest;\
    m = Manifest();\
    stats = m.clean_missing_summaries();\
    m.save();\
    print(f'manifest cleaned: {stats[\"resummarize\"]} rows marked for re-summarization, {stats[\"dropped\"]} rows dropped (source also missing)');\
    print('run \'python -m src.ingest <your-corpus-root>\' to re-summarize the marked files');\
    "

# Both directions in one shot: drop rows for missing sources AND clear
# pointers for missing summaries. Use when you're not sure which kind of
# drift you have or want a clean slate before a big re-ingest.
clean-stale: clean-stale-manifest clean-stale-summaries

# Show how many manifest entries live under each top-level directory.
# `depth` controls grouping: 2 = /home/astavak (mount-level), 3 = /home/astavak/sem6
# (where actual content lives, default), 4 = one deeper.
# Useful for confirming which corpus roots are indexed and spotting accidental
# inclusions (test fixtures, cache dirs, etc.).
manifest-roots depth='3':
    @uv run python -c "\
    from collections import Counter;\
    from src.manifest import REPO_ROOT, Manifest;\
    m = Manifest();\
    n = {{depth}} + 1;\
    c = Counter();\
    [c.update(['/'.join(p.split('/', n + 1)[:n + 1]) if len(p.split('/')) >= n + 1 else p]) for p in m.paths()];\
    print(f'manifest: {len(m.entries)} total entries, grouped at depth {{depth}}');\
    print('-' * 80);\
    [print(f'{v:>6}  {k}') for k, v in c.most_common()];\
    "

# Manifest summary: total entries, by tier-of-routing, by ingestion status.
# Use to quickly check what state the manifest is in (how many pending push,
# how many fast-tier-only, how many router-skipped, etc.).
manifest-stats:
    @uv run python -c "\
    from collections import Counter;\
    from src.manifest import Manifest;\
    m = Manifest();\
    total = len(m.entries);\
    pending_push = sum(1 for p in m.paths() if m.needs_ingestion(p));\
    fast_only = sum(1 for e in m.entries.values() if not e.summary_file and e.fast_indexed_at);\
    skipped = sum(1 for e in m.entries.values() if e.skip_reason);\
    has_summary = sum(1 for e in m.entries.values() if e.summary_file);\
    tiers = Counter();\
    [tiers.update(e.routes) for e in m.entries.values() if e.routes];\
    print(f'manifest entries:          {total}');\
    print(f'  pending stage-2 push:     {pending_push}');\
    print(f'  has summary file:         {has_summary}');\
    print(f'  fast-tier-only (T4):      {fast_only}');\
    print(f'  router-skipped:           {skipped}');\
    print();\
    print('routes (multi-tier counts each separately):');\
    [print(f'  {t}: {n}') for t, n in tiers.most_common()];\
    "

# Show disk usage of pipeline artifacts (summaries, Qdrant, model cache, venv)
disk-usage:
    @echo "=== Summaries (T0-T3 markdown outputs) ==="
    @du -sh "{{SUMMARIES_DIR}}" 2>/dev/null || echo "  (none)"
    @echo
    @echo "=== Qdrant local DB (summary + fast tier) ==="
    @du -sh "{{DATA_DIR}}/qdrant_data/collection/"* 2>/dev/null || echo "  (no collections)"
    @echo
    @echo "=== HF model cache (one-time, shared) ==="
    @du -sh "{{DATA_DIR}}/cache/hub/"* 2>/dev/null | sort -h || echo "  (none)"
    @echo
    @echo "=== Project venv ==="
    @du -sh .venv 2>/dev/null || echo "  (no venv)"
    @echo
    @echo "=== Manifest stats ==="
    @uv run python -c "\
    import json; from pathlib import Path;\
    m = json.load(open('{{MANIFEST_PATH}}'));\
    src_bytes = sum(e.get('size', 0) for e in m.values());\
    fast_pages = sum(e.get('fast_pages') or 0 for e in m.values());\
    summarized = sum(1 for e in m.values() if e.get('summary_file'));\
    in_fast = sum(1 for e in m.values() if e.get('fast_indexed_at'));\
    skipped = sum(1 for e in m.values() if e.get('skip_reason'));\
    summaries_dir = Path('{{SUMMARIES_DIR}}');\
    summaries_mb = sum(p.stat().st_size for p in summaries_dir.glob('*.md')) / 1024**2 if summaries_dir.exists() else 0;\
    ft_dir = Path('{{DATA_DIR}}/qdrant_data/collection/fast_tier');\
    ft_bytes = sum(p.stat().st_size for p in ft_dir.rglob('*') if p.is_file()) if ft_dir.exists() else 0;\
    print(f'  Files in manifest:   {len(m):,}');\
    print(f'  Source corpus size:  {src_bytes / 1024**3:.2f} GB');\
    print(f'  Summarized (T0-T3):  {summarized:,}');\
    print(f'  In fast tier (T4):   {in_fast:,} files, {fast_pages:,} pages');\
    print(f'  Router-skipped:      {skipped:,}');\
    print(f'  Avg summary:         {summaries_mb*1024 / max(summarized,1):.0f} KB/file');\
    print(f'  Avg fast-tier page:  {ft_bytes / 1024 / max(fast_pages,1):.0f} KB')\
    "

# Show point counts for all Qdrant collections
qdrant-counts:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Qdrant Collection Counts ==="
    for coll in summaries fast_tier; do
        count=$(curl -s "http://localhost:{{QDRANT_PORT}}/collections/$coll" | \
               python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('result', {}).get('points_count', 'not found'))" 2>/dev/null)
        echo "$coll: $count"
    done
