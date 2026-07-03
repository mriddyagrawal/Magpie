"""FastAPI entry point for Magpie Cloud.

Run locally:
    cd server && uv run uvicorn magpie_server.main:app --reload

Run via just (from repo root):
    just cloud-serve

Production (fly.io / Render / Railway):
    Set INVITE_CODES, OPENROUTER_API_KEY env vars; bind 0.0.0.0; no --reload.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from magpie_server import __version__
from magpie_server.auth import require_invite
from magpie_server.settings import settings


app = FastAPI(
    title="Magpie Cloud",
    version=__version__,
    description="LLM orchestration backend for the Magpie desktop app.",
)

# CORS: the desktop app (Tauri) calls us from a `tauri://` origin. We allow
# all origins because the only authentication that matters is the bearer
# token — origin spoofing doesn't bypass invite-code validation. In
# production this stays wide open; auth carries the load.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# /health — unauthenticated. Used by the desktop app to detect "is the cloud
# up?" before showing the first-question UI, and by deploy tools to
# health-check the container.
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "auth_configured": bool(settings.valid_invite_codes()),
        "llm_configured": bool(settings.openrouter_api_key),
    }


# ---------------------------------------------------------------------------
# /whoami — authenticated; useful for debugging that the bearer-token path
# is wired correctly end-to-end. Returns the invite code that was accepted.
# (Not the user's; just the code — we don't have user records yet.)
# ---------------------------------------------------------------------------

@app.get("/whoami")
def whoami(invite: str = Depends(require_invite)) -> dict:
    return {"invite_code": invite}


# LLM endpoints. Auth dependency is on each route function (not at the
# router level) so individual routes can be unprotected later if needed
# (e.g. a future /llm/prompts/info that returns prompt versions only).
from magpie_server.llm_routes import router as llm_router  # noqa: E402
app.include_router(llm_router, prefix="/llm", tags=["llm"])
