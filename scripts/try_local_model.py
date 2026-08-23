"""Smoke-test the active local model without touching Qdrant or the index.

  python -m scripts.try_local_model                 → text + structured-output calls
  python -m scripts.try_local_model IMAGE.png       → also a vision call

Spawns whichever profile `LLAMA_SERVER_TEXT_MODEL` selects, through the same
pool the real pipeline uses, and times each call separately so the one-off
model-load cost doesn't hide inside the first result. Use it to answer "is
this model wired up and does it hold a JSON schema" in one command, before
spending an hour on `tests.run_all_questions`.

Nothing here is a quality measurement — it is three prompts. See Plan #9 in
`Plans/Future Plans.md` for the real evaluation.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RECEIPT_LINE = "BLUE BOTTLE COFFEE  03/14/2026  TOTAL $18.40"

RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor": {"type": "string"},
        "total": {"type": "number"},
        "date": {"type": "string"},
    },
    "required": ["vendor", "total", "date"],
}


def _timed(label: str, started: float, result: str) -> None:
    print(f"\n  [{label}] {time.monotonic() - started:.1f}s")
    print(f"  {result.strip()}")


async def main_async(image: Path | None) -> int:
    from src.inference.local_llm import get_local_llm
    from src.inference.profiles import active_profile, short_model_name

    profile = active_profile()
    print(f"profile : {profile.name}")
    print(f"weights : {short_model_name(profile)} @ {profile.args.quant}")
    print(f"vision  : {profile.has_vision}")
    print("\nfirst call includes the model load — expect minutes on a cold cache.")

    llm = get_local_llm()

    started = time.monotonic()
    out = await llm.complete(
        [{"role": "user", "content": "Reply with exactly: MAGPIE OK"}],
        max_tokens=32,
    )
    _timed("text  (incl. model load)", started, out)

    # The one that matters: every real call site (summarize, rewrite, answer)
    # goes through a Pydantic schema. A model that chats fine but can't hold
    # a schema is useless to us.
    started = time.monotonic()
    out = await llm.complete(
        [{"role": "user", "content":
          f"Extract vendor, total and date as JSON from: '{RECEIPT_LINE}'"}],
        max_tokens=256,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "receipt", "schema": RECEIPT_SCHEMA},
        },
    )
    _timed("json", started, out)
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError as e:
        print(f"  PARSE FAILED: {e}")
        print("  (the pipeline's JSON-repair layer may still rescue this)")
    else:
        missing = [k for k in RECEIPT_SCHEMA["required"] if k not in parsed]
        print(f"  parsed: {parsed}")
        if missing:
            print(f"  MISSING REQUIRED FIELDS: {missing}")

    if image is None:
        print("\npass an image path to also test the vision path.")
        return 0

    if not profile.has_vision:
        print(f"\nskipping the image: profile {profile.name!r} has no projector.")
        return 0

    data = base64.b64encode(image.read_bytes()).decode()
    suffix = image.suffix.lower().lstrip(".") or "png"
    started = time.monotonic()
    out = await llm.complete(
        [{"role": "user", "content": [
            {"type": "text", "text": "What text is visible in this image? Quote it."},
            {"type": "image_url",
             "image_url": {"url": f"data:image/{suffix};base64,{data}"}},
        ]}],
        max_tokens=512,
    )
    _timed(f"vision ({image.name})", started, out)
    return 0


def main() -> int:
    image = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    if image is not None and not image.is_file():
        print(f"error: {image} is not a file", file=sys.stderr)
        return 1
    return asyncio.run(main_async(image))


if __name__ == "__main__":
    raise SystemExit(main())
