"""Generate and cache plausible user questions from the indexed documents.

CLI-only UX layer: after each `sync`, a random sample of summary `.md` files
is sent to the active LLM to produce N example questions the user could
realistically ask about their own library. Results are cached at
`Test Summaries/_suggestions.json` and shown in the REPL banner.

Regeneration is triggered only when the manifest size changes, so adding
or removing files forces a refresh; repeated `--sync` calls on an unchanged
library cost nothing. Generation failures are swallowed: the old cache is
preserved and the sync itself never breaks.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from src.llm import build_agent as _build_chat_agent
from src.manifest import REPO_ROOT

SUGGESTIONS_PATH = REPO_ROOT / "Test Summaries" / "_suggestions.json"
SUMMARIES_DIR = REPO_ROOT / "Test Summaries"
SAMPLE_SIZE = 15
N_QUESTIONS = 5
MAX_CHARS_PER_SUMMARY = 400


class Suggestions(BaseModel):
    questions: list[str] = Field(
        description=(
            f"Exactly {N_QUESTIONS} short, concrete retrieval-style prompts a "
            "user would type to pull a specific piece of information out of "
            "their files. Imperative or short-question form, not analytical."
        )
    )


SYSTEM_PROMPT = (
    "You are a UX assistant for a local file-search product. Given a sample "
    "of file summaries from a user's library, generate example prompts the "
    f"user might type to FETCH a specific piece of information. Produce "
    f"exactly {N_QUESTIONS} diverse prompts covering different files.\n\n"
    "Each prompt must be:\n"
    "- SHORT (under ~12 words) and conversational, like a search query or DM\n"
    "- CONCRETE — ask for a specific artifact: a code excerpt, an email "
    "address, a phone number, a date, a total, a contact, a quote, a table "
    "value, a step-by-step procedure\n"
    "- Often imperative ('give me…', 'find the…', 'what's the…') not "
    "analytical ('analyze…', 'summarize…', 'compare…')\n"
    "- Anchored to one concrete detail copied from the summary (a name, "
    "course code, merchant, topic) so it targets a specific file\n\n"
    "Good examples:\n"
    "- 'give me the code excerpt for hydrogen atom excitation'\n"
    "- 'email for PAL student support'\n"
    "- 'how much was the United Airlines flight?'\n"
    "- 'what date is the CSC 105 final?'\n"
    "- 'total on the Target receipt'\n\n"
    "Bad examples (too abstract / analytical / long):\n"
    "- 'What are the main themes across the physics assignments?'\n"
    "- 'How does the author argue for X in the Plato reading?'\n"
    "- 'Explain the methodology used in the simulation code'\n\n"
    "Output RAW JSON only — no markdown fences, no commentary."
)


def _sample_summary_blobs(n: int) -> list[str]:
    if not SUMMARIES_DIR.is_dir():
        return []
    md_files = [p for p in SUMMARIES_DIR.glob("*.md") if p.is_file()]
    if not md_files:
        return []
    sampled = random.sample(md_files, k=min(n, len(md_files)))
    blobs: list[str] = []
    for p in sampled:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        blobs.append(text[:MAX_CHARS_PER_SUMMARY])
    return blobs


def _read_cache() -> dict | None:
    if not SUGGESTIONS_PATH.exists():
        return None
    try:
        return json.loads(SUGGESTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_suggestions() -> list[str] | None:
    """Return the cached question list, or None if no valid cache exists."""
    data = _read_cache()
    if not data:
        return None
    qs = data.get("questions")
    if isinstance(qs, list) and all(isinstance(q, str) for q in qs):
        return qs or None
    return None


def _cached_manifest_size() -> int | None:
    data = _read_cache()
    if not data:
        return None
    size = data.get("manifest_size")
    return size if isinstance(size, int) else None


def _save(questions: list[str], manifest_size: int) -> None:
    SUGGESTIONS_PATH.parent.mkdir(exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifest_size": manifest_size,
        "questions": questions,
    }
    SUGGESTIONS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


async def _generate(blobs: list[str]) -> list[str]:
    # fallback=None so local-provider parse failures raise; caller catches.
    agent = _build_chat_agent(SYSTEM_PROMPT, Suggestions, None)
    joined = "\n\n---\n\n".join(blobs)
    message: list = [
        f"Here are {len(blobs)} summaries from the user's indexed library:\n\n"
        f"{joined}\n\n"
        f"Generate {N_QUESTIONS} example questions the user could ask."
    ]
    result = await agent.run(message)
    return [q.strip() for q in result.questions if q.strip()][:N_QUESTIONS]


async def regenerate_if_stale(manifest_size: int) -> list[str] | None:
    """Regenerate suggestions when the manifest size differs from the cache.

    Returns the (new or existing) questions list, or None if no suggestions
    could be produced (empty library, LLM failure, etc.). Never raises —
    suggestion generation is best-effort and must not break the sync pipeline.
    """
    if manifest_size == 0:
        return None
    if _cached_manifest_size() == manifest_size:
        return load_suggestions()

    blobs = _sample_summary_blobs(SAMPLE_SIZE)
    if not blobs:
        return None
    try:
        questions = await _generate(blobs)
    except Exception:
        return load_suggestions()
    if not questions:
        return load_suggestions()
    _save(questions, manifest_size)
    return questions


async def force_regenerate() -> list[str] | None:
    """Regenerate regardless of cache state. For the `.suggest` dot-command."""
    from src.manifest import Manifest

    blobs = _sample_summary_blobs(SAMPLE_SIZE)
    if not blobs:
        return None
    try:
        questions = await _generate(blobs)
    except Exception:
        return None
    if not questions:
        return None
    _save(questions, len(Manifest().entries))
    return questions
