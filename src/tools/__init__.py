"""Top-level helpers for build / install / packaging tasks.

Modules in this package are typically invoked via `python -m src.tools.<x>`
from the justfile rather than imported by application code. They lean
on stdlib so they work on any platform Magpie runs on (no bash, no
curl, no unzip required).
"""
