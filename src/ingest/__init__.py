"""Tier workers: one module per tier (T0/T1/T2/T3).

Every tier worker's `run(...)` produces a Stage-2-compatible summary markdown
and updates the manifest. Stage 2's existing ingest path then picks these up
and embeds them into Qdrant unchanged. See `Plans/Indexing Tiers.md`.
"""
