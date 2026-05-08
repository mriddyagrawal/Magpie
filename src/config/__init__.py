"""Magpie config layer.

Two parallel two-loader systems sharing `magpie_defaults.json`:

  - **Indexing rules** (`indexing_rules.py`): MagpieDefaults (bundled
    safety rails) + UserRules (`<APP_DATA_DIR>/indexing_rules.json`).
    Drives what the walker reads. See
    `Plans/Ingestion Rules/Implementation Plan.md`.

  - **App settings** (`settings.py`): AppDefaults (bundled defaults
    for provider / theme / etc.) + UserSettings
    (`<APP_DATA_DIR>/settings.json`). Drives the Settings UI and the
    answer-time provider choice. See
    `Plans/UI/Implementation Plan.md`.

  - **Secrets** (`secrets.py`): cloud API key in
    `<APP_DATA_DIR>/secrets.json` (mode 0600). Bootstraps from
    `OPENROUTER_API_KEY` in `.env` on first launch.
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
from src.config.secrets import (
    Secrets,
    load_secrets,
    save_secrets,
)
from src.config.settings import (
    AppDefaults,
    EffectiveSettings,
    UserSettings,
    effective_settings,
    load_app_defaults,
    load_user_settings,
    patch_user_settings,
    save_user_settings,
)

__all__ = [
    # Indexing rules
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
    # Settings
    "AppDefaults",
    "EffectiveSettings",
    "UserSettings",
    "effective_settings",
    "load_app_defaults",
    "load_user_settings",
    "patch_user_settings",
    "save_user_settings",
    # Secrets
    "Secrets",
    "load_secrets",
    "save_secrets",
]
