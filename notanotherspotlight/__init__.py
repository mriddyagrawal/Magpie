"""NotAnotherSpotlight — RAG-style semantic search over local documents."""

__version__ = "0.1.0"

_LAZY_IMPORTS = {
    "ParsedSummary": "notanotherspotlight.parser",
    "parse_summary_file": "notanotherspotlight.parser",
    "load_all_summaries": "notanotherspotlight.parser",
    "get_embedding_model": "notanotherspotlight.embeddings",
    "get_qdrant_client": "notanotherspotlight.db",
    "create_collection": "notanotherspotlight.db",
    "upsert_summaries": "notanotherspotlight.db",
    "search_summaries": "notanotherspotlight.search",
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib
        module = importlib.import_module(_LAZY_IMPORTS[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_LAZY_IMPORTS.keys()) + ["__version__"]
