# NotAnotherSpotlight — command runner

# Install all dependencies
sync:
    uv sync

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
