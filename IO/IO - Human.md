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


uv run python -m src.ingest /home/astavak/sem6
uv run python -m src.ingest /mnt/hardisk/sem_4
