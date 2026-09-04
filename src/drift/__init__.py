"""Drift guard: pin, stamp, and check the upstream pieces Magpie depends on.

Magpie runs on binaries and models it does not own — llama.cpp, Qdrant, the
GGUF weights, the ColQwen/ColSmol encoders, a lockfile of Python packages —
and it mirrors some of their internal behaviour in its own code (the image
token budget copies llama.cpp's LFM2 tiling math; structured output assumes
llama-server honours `json_schema`; the vector store assumes a fixed
embedding width). When any of those move underneath us the failures are
SILENT: a wrong token estimate becomes an HTTP 400 three weeks later in an
eval, an ignored grammar becomes prose the parser has to repair, a changed
embedding width becomes an empty search.

This package makes that drift visible:

  pins        the versions we validated against (single source of truth
              for installers and the startup check)
  provenance  a fingerprint of what is actually installed and loaded
  oracles     executable checks of every mirrored assumption, run once per
              fingerprint against the real binary and cached
  tripwire    production self-check: every LLM response's reported
              prompt_tokens compared with what we predicted

None of it is load-bearing for answering a question: every entry point
swallows its own failures, warns, and moves on. A drift guard that takes
the app down would be worse than the drift.
"""
