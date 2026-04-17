# Make the repo root importable. The notebook lives in notebooks/, so go up one.
import os
import sys
from pathlib import Path

REPO_ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Force the local provider regardless of what .env says.
os.environ["LLM_PROVIDER"] = "local"

from src.llm import get_model, active_model_name
print(f"Using: {active_model_name()}")

# Helper: send a raw prompt (+ optional images) and return the raw generated text.
# No JSON parsing, no schema — whatever the model produces is what you see.

def ask(prompt: str, images=None, max_tokens: int = 512, verbose: bool = False) -> str:
    """Send a prompt to local Gemma 3n and return the raw text response.

    - `prompt`: the user message. System prompt is empty here — add instructions inline
      if you want to mimic a structured-output call.
    - `images`: optional list of file paths (str/Path) or PIL.Image instances.
    - `max_tokens`: cap on generated tokens. 512 is plenty for chat-style replies.
    - `verbose`: if True, mlx-vlm prints per-token timing to stderr.
    """
    from mlx_vlm import generate
    from mlx_vlm.prompt_utils import apply_chat_template

    model, processor, config = get_model()

    # Normalise images: mlx-vlm's apply_chat_template wants a num_images count.
    imgs = images or []

    formatted = apply_chat_template(processor, config, prompt, num_images=len(imgs))
    formatted = formatted + "{"   # prefill — forces the continuation to start inside JSON
    out = generate(
        model,
        processor,
        formatted,
        imgs if imgs else None,
        max_tokens=max_tokens,
        verbose=verbose,
    )

    raw = getattr(out, "text", out) if not isinstance(out, str) else out
    raw = "{" + raw
    # mlx-vlm returns either a str or a GenerateResult — normalise to text.
    return raw


from src.stage1.summarize import SYSTEM_PROMPT as SUMMARY_PROMPT

# Few-shot prompt aligned with the actual FileSummary schema.
# Field names in the example MUST match the schema exactly — small models
# copy the structure they see, so `description` becomes a bug, `summary` is right.
newprompt = """You are a file analyzer. Given a file's content, output a JSON object describing what the file is and the details someone might use to find it later via keyword search.

The JSON MUST have exactly these keys (and only these keys):
- title (string, <=80 chars)
- summary (string, 3-7 sentences of natural prose)
- content_type (one of: "image", "pdf", "docx", "xlsx", "text", "code", "markdown", "other")
- keywords (list of 3-10 topical words)
- key_entities (list of named entities: people, organisations, places, products, branches — copied verbatim from the file)
- identifiers (list of exact tokens that uniquely distinguish this file: numeric IDs, dates in their ORIGINAL format, SKUs, version strings, exact prices with currency, URLs — copied verbatim)

EXAMPLE:
Input:
Filename: flight-receipt.pdf
Content type: pdf
Delta Airlines — Flight Receipt
Passenger: Jane Doe
Flight DL1492, Atlanta ATL -> Hartford BDL, 25 May 2022
Confirmation code: ABC123
Total charged: $247.50

Output:
{"title": "Delta flight DL1492 Atlanta to Hartford — Jane Doe", "summary": "Delta Airlines flight receipt for passenger Jane Doe. Flight DL1492 from Atlanta ATL to Hartford BDL on 25 May 2022. Confirmation code ABC123. Total charged: $247.50.", "content_type": "pdf", "keywords": ["flight", "receipt", "airline", "delta", "travel"], "key_entities": ["Delta Airlines", "Jane Doe", "Atlanta ATL", "Hartford BDL"], "identifiers": ["DL1492", "25 May 2022", "ABC123", "$247.50"]}

Now analyze the file below. Return ONLY the JSON object — no markdown fences, no code blocks, no commentary. Start with { and end with }.
"""

test_file_content = """Filename: local-test.md
Summarize this file.

Content type: markdown

---
# Local MLX Smoke File

Unique identifier: **LOCAL-SMOKE-9000**.
This file mentions the fictional **Obsidian Tribunal** as a topical anchor.
Date of test: 2026-04-16.
"""

# Combine system prompt + user message the way LocalAgent does internally
combined = newprompt + "\n\n" + test_file_content

reply = ask(combined, max_tokens=2000)
print(reply)