# Local (Embedded) Qdrant — Setup Runbook

By default this project uses Qdrant Cloud. To switch to a fully local,
zero-server, on-disk Qdrant (no network, no account, no hard storage
limits) — flip one env var.

## When to use local

| Use local when… | Use cloud when… |
|---|---|
| Developing / iterating | Shipping to end users on free tier |
| Storage budget is flexible (your SSD) | You want managed backups |
| Privacy requires no vectors leaving the machine | You need multi-host access |
| Your cloud tier is full (4 GB limit, etc.) | Your deployment target runs it for you |

## 1. Switch providers

Edit `.env`:

```bash
# From:
# QDRANT_PROVIDER=cloud
# QDRANT_CLUSTER_ENDPOINT=https://...
# QDRANT_API_KEY=...

# To:
QDRANT_PROVIDER=local
# QDRANT_LOCAL_PATH=/mnt/hardisk/ns-qdrant   # optional override
```

If you don't set `QDRANT_LOCAL_PATH`, it defaults to `./qdrant_data/` at
the repo root. Data persists across runs. Delete the folder to wipe the
index.

## 2. Re-index from scratch

Cloud vectors don't migrate to local. You'll re-run sync:

```bash
# Reset anything stale (summary tier only — doesn't touch fast_tier).
uv run ns --reset -y

# Re-index with smart routing + local Qdrant + both tiers.
uv run ns --sync=/path/to/your/documents --concurrency 8
```

Smart routing sends text-heavy PDFs to summary tier, visual-only files to
fast tier. The `--concurrency 8` speeds up the LLM summarize pass.

## 3. Resource-constrained tuning (already baked in)

The fast-tier Qdrant collection is configured in `src/stage2/fast_db.py`
with laptop/cheap-cloud-tier-friendly settings:

- `quantization.always_ram = False` — int8 blocks live on disk, loaded lazily
- `vectors_config.on_disk = True` — raw vectors memory-mapped, not RAM
- `hnsw_config.on_disk = True` — search graph on disk, not RAM

Trade-off: ~5-20ms extra per query (mmap reads). Win: Qdrant stays under
~200 MB RAM for 10k pages of fast-tier data. Without these, the same load
would use multiple GB.

## 4. Check your footprint

```bash
# Disk usage of local Qdrant data.
du -sh qdrant_data/

# Collection sizes.
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
from src.stage2.db import get_qdrant_client, COLLECTION_NAME
from src.stage2.fast_db import FAST_COLLECTION_NAME
c = get_qdrant_client()
for name in [COLLECTION_NAME, FAST_COLLECTION_NAME]:
    if c.collection_exists(name):
        info = c.get_collection(name)
        print(f'{name}: {info.points_count} points')
    else:
        print(f'{name}: (not created yet)')
"
```

## 5. Porting to another machine

The "database" is just the `qdrant_data/` directory. To share:

- **Don't.** Your indexed data references paths on your disk. Your friend
  should `git clone` the code, set up their own `.env`, and run `--sync`
  on their own files.
- If you MUST migrate your OWN setup (e.g. new laptop), copy:
  - `qdrant_data/` (vectors)
  - `Test Summaries/` (summary `.md` files + `_manifest.json`)
  - Re-export `.env`

## 6. Going back to cloud

Flip the env var back. The local `qdrant_data/` folder persists — you can
switch back and forth. Each provider has its own collections; nothing
syncs between them.

```bash
# .env
QDRANT_PROVIDER=cloud
QDRANT_CLUSTER_ENDPOINT=https://...
QDRANT_API_KEY=...
```
