# NotAnotherSpotlight — command runner

# Install all dependencies
sync:
    uv sync
    uv pip install -e cli

# Run all tests
test:
    uv run pytest tests/ -v

# Run stage2 tests only
test-stage2:
    uv run pytest tests/stage2/ -v

# Ingest summaries into Qdrant
ingest:
    uv run python -m src.stage2 ingest

# Force re-ingest (drop + recreate collection)
ingest-force:
    uv run python -m src.stage2 ingest --force

# Search documents
search q:
    uv run python -m src.stage2 search "{{q}}"

# Summarize a file or directory (Stage 1)
summarize path:
    uv run python src/stage1/summarize.py "{{path}}"

# Launch interactive CLI
chat:
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

# Where to keep the Qdrant binary, data, and pidfile. Override with env vars.
QDRANT_HOME      := env_var_or_default("QDRANT_HOME", "/mnt/hardisk/qdrant")
QDRANT_BIN       := QDRANT_HOME / "qdrant"
QDRANT_DATA      := env_var_or_default("QDRANT_DATA", QDRANT_HOME / "storage")
QDRANT_LOGS      := QDRANT_HOME / "qdrant.log"
QDRANT_PIDFILE   := QDRANT_HOME / "qdrant.pid"
QDRANT_VERSION   := "v1.12.4"
QDRANT_PORT      := "6333"

# Download the Qdrant standalone binary onto QDRANT_HOME (one-time, ~30 MB).
qdrant-install:
    @mkdir -p "{{QDRANT_HOME}}"
    @if [ -x "{{QDRANT_BIN}}" ]; then \
        echo "Qdrant binary already at {{QDRANT_BIN}} — delete it first if you want to reinstall."; \
        "{{QDRANT_BIN}}" --version; \
    else \
        echo "Downloading Qdrant {{QDRANT_VERSION}} into {{QDRANT_HOME}}..."; \
        curl -L -o "{{QDRANT_HOME}}/qdrant.tar.gz" \
            "https://github.com/qdrant/qdrant/releases/download/{{QDRANT_VERSION}}/qdrant-x86_64-unknown-linux-gnu.tar.gz"; \
        tar -xzf "{{QDRANT_HOME}}/qdrant.tar.gz" -C "{{QDRANT_HOME}}"; \
        rm "{{QDRANT_HOME}}/qdrant.tar.gz"; \
        chmod +x "{{QDRANT_BIN}}"; \
        echo "Installed: $({{QDRANT_BIN}} --version)"; \
    fi

# Start Qdrant as a background process. Data + logs go to QDRANT_DATA/QDRANT_LOGS.
qdrant-up:
    @mkdir -p "{{QDRANT_DATA}}"
    @if [ -f "{{QDRANT_PIDFILE}}" ] && kill -0 $(cat "{{QDRANT_PIDFILE}}") 2>/dev/null; then \
        echo "Qdrant already running (pid $(cat {{QDRANT_PIDFILE}})). Use 'just qdrant-status' to inspect."; \
    elif [ ! -x "{{QDRANT_BIN}}" ]; then \
        echo "Qdrant binary missing at {{QDRANT_BIN}}. Run 'just qdrant-install' first."; \
        exit 1; \
    else \
        echo "Starting Qdrant on port {{QDRANT_PORT}}, data at {{QDRANT_DATA}}..."; \
        QDRANT__STORAGE__STORAGE_PATH="{{QDRANT_DATA}}" \
        QDRANT__SERVICE__HTTP_PORT="{{QDRANT_PORT}}" \
            nohup "{{QDRANT_BIN}}" > "{{QDRANT_LOGS}}" 2>&1 & \
            echo $! > "{{QDRANT_PIDFILE}}"; \
        sleep 2; \
        if kill -0 $(cat "{{QDRANT_PIDFILE}}") 2>/dev/null; then \
            echo "Started (pid $(cat {{QDRANT_PIDFILE}})). Logs: {{QDRANT_LOGS}}"; \
            echo "Set in .env: QDRANT_PROVIDER=cloud  QDRANT_CLUSTER_ENDPOINT=http://localhost:{{QDRANT_PORT}}"; \
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
        echo "Qdrant: RUNNING (pid $(cat {{QDRANT_PIDFILE}}), port {{QDRANT_PORT}})"; \
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
    import json;\
    m = json.load(open('Test Summaries/_manifest.json'));\
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

# Inspect the live Qdrant fast_tier config — shows what's actually applied
# vs what the code requested (exposes silent local-mode quantization gaps).
fast-tier-config:
    @QDRANT_PROVIDER=local uv run python -c "\
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
    print('  ', qc.model_dump() if qc else 'None  <-- LOCAL MODE DOES NOT APPLY QUANTIZATION; vectors are raw fp32');\
    "

# Rebuild manifest fast_indexed_at + fast_pages from Qdrant fast_tier — recovers
# from the pre-2026-04-25 mark_summarized bug that silently wiped fast-tier
# fields when a file was re-summarized. Vectors stayed in Qdrant; only the
# manifest forgot. This re-stamps the manifest from the surviving Qdrant data.
recover-fast-tier:
    @QDRANT_PROVIDER=local uv run python -c "\
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
    print('run \\'python -m src.stage2 ingest\\' to also clean orphan Qdrant points (or do it on next ingest)');\
    "

# Show disk usage of pipeline artifacts (summaries, Qdrant, model cache, venv)
disk-usage:
    @echo "=== Summaries (T0-T3 markdown outputs) ==="
    @du -sh "Test Summaries" 2>/dev/null || echo "  (none)"
    @echo
    @echo "=== Qdrant local DB (summary + fast tier) ==="
    @du -sh qdrant_data/collection/* 2>/dev/null || echo "  (no collections)"
    @echo
    @echo "=== HF model cache (one-time, shared) ==="
    @du -sh ~/.cache/huggingface/hub/* 2>/dev/null | sort -h || echo "  (none)"
    @echo
    @echo "=== Project venv ==="
    @du -sh .venv 2>/dev/null || echo "  (no venv)"
    @echo
    @echo "=== Manifest stats ==="
    @uv run python -c "\
    import json; from pathlib import Path;\
    m = json.load(open('Test Summaries/_manifest.json'));\
    src_bytes = sum(e.get('size', 0) for e in m.values());\
    fast_pages = sum(e.get('fast_pages') or 0 for e in m.values());\
    summarized = sum(1 for e in m.values() if e.get('summary_file'));\
    in_fast = sum(1 for e in m.values() if e.get('fast_indexed_at'));\
    skipped = sum(1 for e in m.values() if e.get('skip_reason'));\
    summaries_mb = sum(p.stat().st_size for p in Path('Test Summaries').glob('*.md')) / 1024**2;\
    ft_dir = Path('qdrant_data/collection/fast_tier');\
    ft_bytes = sum(p.stat().st_size for p in ft_dir.rglob('*') if p.is_file()) if ft_dir.exists() else 0;\
    print(f'  Files in manifest:   {len(m):,}');\
    print(f'  Source corpus size:  {src_bytes / 1024**3:.2f} GB');\
    print(f'  Summarized (T0-T3):  {summarized:,}');\
    print(f'  In fast tier (T4):   {in_fast:,} files, {fast_pages:,} pages');\
    print(f'  Router-skipped:      {skipped:,}');\
    print(f'  Avg summary:         {summaries_mb*1024 / max(summarized,1):.0f} KB/file');\
    print(f'  Avg fast-tier page:  {ft_bytes / 1024 / max(fast_pages,1):.0f} KB')\
    "
