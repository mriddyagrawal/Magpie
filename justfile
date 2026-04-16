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
