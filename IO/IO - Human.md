What you need to do (manual, ~3 min):


# 1. Download the binary onto /mnt/hardisk (~30 MB, one time)
just qdrant-install

# 2. Start the server
just qdrant-up

# 3. Verify it's running
just qdrant-status
If qdrant-status shows RUNNING and prints empty collections JSON, you're good.

Then update .env:


QDRANT_PROVIDER=cloud
QDRANT_CLUSTER_ENDPOINT=http://localhost:6333
# Leave QDRANT_API_KEY blank or omitted — localhost auth is off
Then re-ingest to populate the new server (now with real int8 quantization):

# how to ingest data not included
uv run python -m src.ingest /home/astavak/sem6

# shows which tier used and json, csv, dat data gets included
uv run python -m src.ingest /mnt/hardisk/sem_4 -v --include-data

# monster data 1 tb ingest how?
uv run python -m src.ingest /mnt/hardisk --list-children | head -20 # preview

# chunked ingestion same as previous but chunks
uv run python -m src.ingest /mnt/hardisk --per-child -v     # run

# Append — skip unchanged, push deltas
uv run python -m src.ingest /path

# Re-encode this corpus —  "ignore the manifest, re-encode everything." -- Useful if you change the embedding model or Qdrant config and want to update existing vectors.
uv run python -m src.ingest /path --force

# Nuke + restart — drop both Qdrant collections, clear manifest under root, re-ingest from scratch
uv run python -m src.ingest /path --rebuild

# How to ingest?
just --list

# adds on top of exisiting, skipping unchanged files
just walk-verbose /path/

# How to ns?
just qdrant-up
uv run ns


