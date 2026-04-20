"""Fast-tier indexing via late-interaction visual embeddings (ColPali / ColQwen).

See `Plans/IO - Colpali.md` for the design and roadmap. Modules:

- `device`: detect CUDA / MPS / CPU and pick the right model
- `model`:  cached singleton loader for the chosen ColPali-family model
- `index`:  batch indexer — renders pages, encodes, upserts to fast_tier
"""
