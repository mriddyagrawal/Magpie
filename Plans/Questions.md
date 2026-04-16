# Development Log

## Open Questions

### Source Path Resolution
- `source_path` in summaries is a **relative path** from the repo root (e.g., `Test Content/Flight GSP - Hartford Receipt.pdf`)
- Extracted from the `Source:` line that `summarize.py` writes into each summary markdown file
- **Unresolved:** If original documents move or the product runs on a different machine, these paths break
- **Needs decision:** Should we store absolute paths? A configurable base directory? Or resolve at query time?

## Design Decisions

### Two-Column Payload + Score
- Qdrant payload stores: **summary**, **source_path**
- Embedding is stored internally by Qdrant (used for search, not in payload)
- Search output returns: **summary**, **path**, **score** (score is from RRF fusion ranking)
- Top-K beam search (default 5) returns the best matches ranked by score
