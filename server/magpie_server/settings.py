"""Server configuration loaded from environment.

Reads from `server/.env` in dev (gitignored) and from the hosting
provider's env vars in prod (fly.io secrets, etc.). Pydantic-settings
gives us typed, validated config — typos in env-var names fail at
startup instead of at request time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All server config. Override any field via env var of the same name."""

    model_config = SettingsConfigDict(
        # Look for `server/.env` first, then fall back to process env.
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding="utf-8",
        # Don't choke if the user has unrelated env vars set.
        extra="ignore",
        # Env vars are case-insensitive on Windows; keep parity.
        case_sensitive=False,
    )

    # ---- Bind / serve ------------------------------------------------------

    host: str = Field(default="127.0.0.1", description="Bind host. 0.0.0.0 in containers.")
    port: int = Field(default=8000, description="Server port.")

    # ---- Auth --------------------------------------------------------------
    #
    # Beta auth model: a comma-separated list of valid invite codes. Each beta
    # tester gets a unique code. To revoke a tester, drop their code from the
    # env var and restart the server. Simple, debuggable, no DB needed.
    #
    # Production auth (post-beta) will swap this for JWT or OAuth — see the
    # README for the migration path. Until then we stay simple.

    invite_codes: str = Field(
        default="",
        description=(
            "Comma-separated list of valid invite codes. Set via env: "
            "INVITE_CODES=alice-abc123,bob-xyz789,carol-qwe456 "
            "Empty list means 'no auth' — only safe for local dev."
        ),
    )

    # ---- LLM provider ------------------------------------------------------

    openrouter_api_key: Optional[str] = Field(
        default=None,
        description="OpenRouter API key. Required for LLM endpoints to work.",
    )

    # Default model — change without an app update by editing this env var.
    answer_model: str = Field(
        default="moonshotai/kimi-k2:free",
        description="Model used for /llm/answer.",
    )
    rewrite_model: str = Field(
        default="moonshotai/kimi-k2:free",
        description="Model used for /llm/rewrite.",
    )
    summarize_model: str = Field(
        default="moonshotai/kimi-k2:free",
        description="Model used for /llm/summarize.",
    )

    # ---- Helpers -----------------------------------------------------------

    def valid_invite_codes(self) -> set[str]:
        """Parsed set of currently-valid invite codes."""
        return {c.strip() for c in self.invite_codes.split(",") if c.strip()}


settings = Settings()
