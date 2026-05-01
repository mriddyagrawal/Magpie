"""Magpie Cloud — server-side LLM orchestration.

This package holds the prompts and LLM-call logic that we deliberately
keep OFF user machines. The desktop app (Tauri + src/) calls into the
endpoints exposed here for any LLM work; everything else (file
indexing, embedding, vector search, file reading) stays local on the
user's device.

Why this exists: see ../../IO/IO - Repo Structure.md — the prompts
are the actual product IP and shouldn't ship in any binary that gets
distributed publicly.
"""

__version__ = "0.1.0"
