"""NotAnotherSpotlight Stage 2 — RAG-style semantic search over local documents."""

__version__ = "0.1.0"

_LAZY_IMPORTS = {
    "ParsedSummary": "src.stage2.parser",
    "parse_summary_file": "src.stage2.parser",
    "load_all_summaries": "src.stage2.parser",
    "get_embedding_model": "src.stage2.embeddings",
    "get_qdrant_client": "src.stage2.db",
    "create_collection": "src.stage2.db",
    "upsert_summaries": "src.stage2.db",
    "search_summaries": "src.stage2.search",
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib
        module = importlib.import_module(_LAZY_IMPORTS[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_LAZY_IMPORTS.keys()) + ["__version__"]
