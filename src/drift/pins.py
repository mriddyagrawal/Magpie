"""The upstream versions Magpie was validated against.

Single source of truth: the installers read these (`install_llama_server`
imports LLAMA_SERVER_TAG; a test pins the justfile's QDRANT_VERSION to
QDRANT_VERSION here), and the startup probe compares what is installed
against them. A mismatch is a WARNING carried in /status and the logs,
never a refusal: packaged builds bundle their binaries and cannot drift,
and a developer who deliberately runs a newer build should be told, not
blocked. The hard floor (the oldest build that works at all) lives
separately in `llama_server_binary.DEFAULT_MIN_VERSION`.

Models are deliberately NOT pinned here. Their identity (repo, quant,
projector variant) is owned by `inference.profiles` and the col-model
registry, and env overrides are a supported way to swap them; provenance
stamps the resolved files (and their hashes) into the fingerprint instead,
so a swapped model re-triggers the oracles rather than tripping a pin.

Bumping a pin is the start of an upgrade, not the end of one:
`just check-drift` (oracles + smoke) must pass on the new build before the
bump merges - see README "Drift guard".
"""

from __future__ import annotations

# llama.cpp release the current mirrored assumptions were verified against
# (image token math token-exact on 23 sizes, the GBNF grammar enforced by
# the sampler for the LFM2 family, chat-template image placement). Tag form
# for the installer.
LLAMA_SERVER_BUILD = 10502
LLAMA_SERVER_TAG = f"b{LLAMA_SERVER_BUILD}"
LLAMA_SERVER_COMMIT = "0adcc3bb5"

# Qdrant release the bundled binaries are downloaded from (`just
# download-qdrant`); the justfile carries the same literal and a test keeps
# the two equal.
QDRANT_VERSION = "v1.17.1"


def check_pins(provenance: dict) -> list[dict]:
    """Compare a provenance fingerprint (see `provenance.runtime_fingerprint`)
    against the pins. Returns one record per mismatch:

        {"component": "llama-server", "pinned": "b10502",
         "installed": "b10600", "note": "..."}

    Unknown/unreadable installed values are reported too - an installed
    binary whose version cannot be parsed is exactly the situation that
    reduced the old MIN_VERSION guard to advisory.
    """
    out: list[dict] = []

    ls = provenance.get("llama_server") or {}
    build = ls.get("build")
    if build != LLAMA_SERVER_BUILD:
        out.append({
            "component": "llama-server",
            "pinned": LLAMA_SERVER_TAG,
            "installed": f"b{build}" if isinstance(build, int) else (ls.get("raw") or "unknown"),
            "note": (
                "the image token estimator, grammar enforcement and image "
                "placement were verified on the pinned build; run "
                "`just check-drift` after any change"
            ),
        })

    qd = provenance.get("qdrant") or {}
    qv = qd.get("version")
    if qv is not None and f"v{qv.lstrip('v')}" != QDRANT_VERSION:
        out.append({
            "component": "qdrant",
            "pinned": QDRANT_VERSION,
            "installed": f"v{qv.lstrip('v')}",
            "note": "vector-store behaviour (payload caps, API shapes) validated on the pinned release",
        })
    return out
