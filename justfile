# Magpie — command runner

# Auto-load .env into every recipe's environment (HF_TOKEN, LLM keys, etc.).
set dotenv-load

# Install all dependencies (Python venv + CLI tool).
sync-environment:
    uv sync
    uv pip install -e cli

# Cheat-sheet for the dependency-group system. Prints groups + when to use each.
deps:
    @echo "==============================================================="
    @echo " Magpie dependency-groups"
    @echo "==============================================================="
    @echo ""
    @echo " Default (everyone, ~10 MB on top of project):"
    @echo "   uv sync                       project + dev (pytest, magpie-cli)"
    @echo ""
    @echo " Opt-in (only when you need them):"
    @echo "   uv sync --group packaging     + PyInstaller (Plan #10 build pipeline)"
    @echo "   uv sync --group notebooks     + Jupyter stack (~200 MB) for .ipynb files"
    @echo ""
    @echo " Production (used by CI to build the .dmg/.AppImage/.exe):"
    @echo "   uv sync --no-dev              project only, ~1.3 GB on Mac/CPU-Linux"
    @echo ""
    @echo " GPU users on Linux who want CUDA torch instead of torch+cpu:"
    @echo "   UV_TORCH_BACKEND=cu121 uv sync"
    @echo ""
    @echo " Inspect what would actually install:"
    @echo "   uv tree                       full dep graph"
    @echo "   uv tree --group packaging     just the packaging group"
    @echo ""
    @echo " For the full list of just recipes:"
    @echo "   just --list"
    @echo "==============================================================="

# Download the llama-server binary for this platform. Run AFTER sync-environment.
# Env knobs: LLAMA_SERVER_VERSION, LLAMA_SERVER_GPU (cpu|vulkan|cuda-*|metal),
# SKIP_MMPROJ_DOWNLOAD=1.
install-llama-server:
    uv run python -m src.tools.install_llama_server

# Walk every enabled include_paths entry in indexing_rules.json ("do everything").
# Extra args pass through to `python -m src.ingest` (--include-data, --force, -v).
# Each include_path runs independently; one failure doesn't abort the rest.
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
    # Capture exit codes ourselves to gate the auto-backup on success.
    all_walks_ok=1
    while IFS= read -r path; do
        echo "== walking $path =="
        if ! uv run python -m src.ingest "$path" {{args}}; then
            all_walks_ok=0
            echo "  warn: walk failed for '$path' (continuing with remaining paths)"
        fi
    done <<< "$paths"
    # Auto-backup on success so the next reset-index restores fast. Skipped
    # if any walk failed. A backup failure doesn't make sync exit nonzero.
    if [ "$all_walks_ok" = "1" ]; then
        echo
        echo "== auto-backup =="
        just backup || echo "warn: auto-backup failed; run 'just backup' manually once Qdrant is healthy"
    else
        echo
        echo "== auto-backup skipped: at least one walk failed (see warnings above) =="
        echo "Fix the failing path(s), then run 'just backup' manually."
    fi

# Check whether a file/folder will be indexed under current rules, with reason.
# Example: just check ~/Documents/secret.pdf
check path:
    @uv run python -m scripts.check_indexing "{{path}}"

# Dry-run: print the (allow/skip + reason) decision for every file under <path>.
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

# Full reset: drop ALL Qdrant collections, clear the manifest, delete every
# summary markdown. Leaves indexing_rules.json, the model cache, and source
# files untouched. Next `just sync --include-data` rebuilds everything.
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

# Snapshot the entire indexed state (manifest + summaries + Qdrant) to
# <APP_DATA_DIR>/backup/. Single slot, atomic overwrite. Auto-fired by `just sync`.
backup: qdrant-up
    @uv run python -m src.backup

# Restore the entire indexed state from <APP_DATA_DIR>/backup/. DESTRUCTIVE:
# drops current Qdrant collections, replaces manifest + summaries on disk.
restore: qdrant-up
    @uv run python -m src.backup restore

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
# MAGPIE_DAEMON_IDLE_MINUTES; 0 disables idle shutdown).
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
    uv run magpie-repl

# ----------------------------------------------------------------------------
# Desktop app build
# ----------------------------------------------------------------------------

# Download the Qdrant binary for the current platform into binaries/.
# Safe to re-run — skips if already present. Pass --force to re-download.
download-qdrant:
    uv run python scripts/download_qdrant.py

# Compile the Python backend into a self-contained binary.
# Must run on the target OS — PyInstaller cannot cross-compile.
build-sidecar:
    uv run python scripts/build_sidecar.py

# Build the Tauri installer for the current platform.
# Requires both download-qdrant and build-sidecar to have run first.
build-app:
    cd frontend && pnpm tauri build

# Full release build: download Qdrant + compile sidecar + build installer.
build: download-qdrant build-sidecar build-app

# Dev mode: hot-reload frontend + Tauri shell. Python server spawns via uv.
# Qdrant is NOT spawned automatically — run `just qdrant-up` in another terminal.
dev: _stub-sidecar-binaries
    cd frontend && pnpm tauri dev

# ----------------------------------------------------------------------------
# Start the FastAPI sidecar (the backend that the Tauri GUI talks to).
# Data goes to APP_DATA_DIR (~/.local/share/Magpie on Linux). Override
# with MAGPIE_DATA_DIR=/some/path if you want a different location.
serve:
    uv run uvicorn src.server:app --port 8765

# Same as `serve`, but auto-reloads on src/ changes — use during dev.
serve-dev:
    uv run uvicorn src.server:app --port 8765 --reload

# Launch the Magpie window (dev). Tauri auto-spawns the Python sidecar;
# single terminal, interleaved logs. ⌥Space summons/hides; Ctrl-C quits.
run-magpie: _stub-sidecar-binaries
    cd frontend && pnpm tauri dev

# Internal: create empty stub files at the externalBin paths tauri.conf.json
# declares, to satisfy Tauri's build validation in dev (never executed — lib.rs
# runs the sidecar via `uv run` in debug). Production replaces them with real
# binaries via `build-sidecar` + `download-qdrant`.
_stub-sidecar-binaries:
    #!/usr/bin/env bash
    set -e
    BIN_DIR="frontend/src-tauri/binaries"
    mkdir -p "$BIN_DIR"
    # Detect the current target triple. Tauri's externalBin name is
    # `binaries/<name>-<triple>` so the stub filename has to match.
    case "$(uname -s)-$(uname -m)" in
        Darwin-arm64)  TRIPLE="aarch64-apple-darwin" ;;
        Darwin-x86_64) TRIPLE="x86_64-apple-darwin" ;;
        Linux-x86_64)  TRIPLE="x86_64-unknown-linux-gnu" ;;
        Linux-aarch64) TRIPLE="aarch64-unknown-linux-gnu" ;;
        *)             echo "warn: unrecognized platform; stubbing macOS arm64 anyway" >&2
                       TRIPLE="aarch64-apple-darwin" ;;
    esac
    for name in magpie-sidecar qdrant; do
        STUB="$BIN_DIR/${name}-${TRIPLE}"
        # Only create if missing — don't clobber a real PyInstaller
        # build when one is present.
        if [ ! -f "$STUB" ]; then
            touch "$STUB"
            echo "[stub] created $STUB"
        fi
    done

# Start Magpie Cloud — the remote LLM-orchestration backend (vs `serve`, the
# local desktop sidecar). See server/README.md.
cloud-serve:
    cd server && uv run uvicorn magpie_server.main:app --port 8000 --reload

# Run the desktop CLI through the local Magpie Cloud (pair with `just cloud-serve`).
chat-cloud:
    LLM_PROVIDER=magpie-cloud \
    MAGPIE_CLOUD_URL=http://127.0.0.1:8000 \
    MAGPIE_INVITE_CODE="${MAGPIE_INVITE_CODE:-dev-anonymous}" \
    uv run magpie-repl

# Install global aliases (magpie-repl, ns, nas) via uv tool
install:
    uv tool install -e cli --force
    @echo "Installed! You can now run: magpie-repl, ns, or nas from anywhere."

# Uninstall global aliases (tries the old package name too, for machines
# that installed before the magpie-cli rename)
uninstall:
    uv tool uninstall magpie-cli || uv tool uninstall notspotlight

# ----------------------------------------------------------------------------
# Qdrant standalone server — same Rust binary as Qdrant Cloud, run as a
# background process (no Docker).
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
# 6433/6434 instead of Qdrant's default 6333/6334 to avoid colliding with
# other apps that bundle Qdrant on the defaults.
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

# Rebuild manifest fast_indexed_at + fast_pages from Qdrant fast_tier (recovers
# from the pre-2026-04-25 mark_summarized bug that wiped those fields).
recover-fast-tier:
    @uv run python -c "\
    from src.manifest import Manifest;\
    m = Manifest();\
    stats = m.reconcile_from_fast_tier();\
    m.save();\
    print(f'recovered fast-tier state for {stats[\"recovered\"]} manifest entries');\
    print(f'qdrant points without manifest row: {stats[\"missing_in_manifest\"]} (manual cleanup if nonzero)');\
    "

# Drop manifest rows whose source files no longer exist + delete orphaned
# summary markdowns. Qdrant orphans clear on the next stage2 ingest.
clean-stale-manifest:
    @uv run python -c "\
    from src.manifest import Manifest;\
    m = Manifest();\
    stats = m.clean_stale();\
    m.save();\
    print(f'cleaned manifest: dropped {stats[\"dropped\"]} stale entries, removed {stats[\"summaries_removed\"]} orphan summary markdowns');\
    print('run \'python -m src.stage2 ingest\' to also clean orphan Qdrant points (or do it on next ingest)');\
    "

# Inverse of clean-stale-manifest: clear summary_file pointers when the markdown
# is gone but the source remains (re-summarized on next ingest). Drops the row
# if the source also vanished.
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
# `depth` controls grouping (default 3).
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

# Manifest summary: total entries, by routing tier, by ingestion status.
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

# Pretty-print the latest LLM session log through `less -R` (on-disk stays JSONL).
llm-log:
    #!/usr/bin/env bash
    set -euo pipefail
    LOG_DIR=$(uv run python -c 'from src.manifest import APP_DATA_DIR; print(APP_DATA_DIR / "logs")')
    LATEST=$(ls -t "$LOG_DIR"/llm-*.log 2>/dev/null | head -1)
    if [ -z "${LATEST:-}" ]; then
        echo "No llm-*.log files in $LOG_DIR" >&2
        echo "Run a query through Magpie first, then re-run this command." >&2
        exit 1
    fi
    echo "Reading: $LATEST" >&2
    jq -C . "$LATEST" | less -R

# Tail the latest LLM session log live, pretty-printed. Useful while
# debugging — keep this open in one terminal, run queries in another.
llm-log-tail:
    #!/usr/bin/env bash
    set -euo pipefail
    LOG_DIR=$(uv run python -c 'from src.manifest import APP_DATA_DIR; print(APP_DATA_DIR / "logs")')
    LATEST=$(ls -t "$LOG_DIR"/llm-*.log 2>/dev/null | head -1)
    if [ -z "${LATEST:-}" ]; then
        echo "No llm-*.log files in $LOG_DIR yet — start a query first." >&2
        exit 1
    fi
    echo "Tailing: $LATEST" >&2
    tail -f "$LATEST" | jq -C .

# Open the latest LLM session log in $EDITOR (or VS Code if EDITOR is unset).
# Writes a `.pretty.json` sibling so the editor gets multi-line
# syntax-highlighted JSON; the JSONL original stays intact.
llm-log-open:
    #!/usr/bin/env bash
    set -euo pipefail
    LOG_DIR=$(uv run python -c 'from src.manifest import APP_DATA_DIR; print(APP_DATA_DIR / "logs")')
    LATEST=$(ls -t "$LOG_DIR"/llm-*.log 2>/dev/null | head -1)
    if [ -z "${LATEST:-}" ]; then
        echo "No llm-*.log files in $LOG_DIR" >&2
        exit 1
    fi
    PRETTY="${LATEST}.pretty.json"
    jq . "$LATEST" > "$PRETTY"
    EDITOR_CMD="${EDITOR:-code}"
    "$EDITOR_CMD" "$PRETTY"
    echo "Opened pretty copy: $PRETTY" >&2
    echo "(The original JSONL is still at: $LATEST)" >&2

# List all session logs with size + last-modified.
llm-log-list:
    #!/usr/bin/env bash
    set -euo pipefail
    LOG_DIR=$(uv run python -c 'from src.manifest import APP_DATA_DIR; print(APP_DATA_DIR / "logs")')
    if [ ! -d "$LOG_DIR" ]; then
        echo "No log dir yet: $LOG_DIR" >&2
        exit 1
    fi
    ls -lhrt "$LOG_DIR"/llm-*.log 2>/dev/null || echo "(no logs yet in $LOG_DIR)"

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
