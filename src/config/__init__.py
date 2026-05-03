"""Magpie indexing-rules configuration.

Two-layer config system + cascade-discovered inline rule files. See
`Plans/Ingestion Rules/Implementation Plan.md` for the full design.
"""

from src.config.indexing_rules import (
    GlobalRules,
    IncludePath,
    IndexingRules,
    MagpieDefaults,
    RuleSet,
    UserRules,
    ensure_path_included,
    load_indexing_rules,
    load_magpie_defaults,
    load_user_rules,
    save_user_rules,
)

__all__ = [
    "GlobalRules",
    "IncludePath",
    "IndexingRules",
    "MagpieDefaults",
    "RuleSet",
    "UserRules",
    "ensure_path_included",
    "load_indexing_rules",
    "load_magpie_defaults",
    "load_user_rules",
    "save_user_rules",
]
