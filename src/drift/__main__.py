"""`python -m src.drift status|check` - the terminal face of the drift guard.

  status   provenance fingerprint + pin mismatches + cached oracle verdicts
           + tripwire counters (no model loads; seconds)
  check    the above, then RUN the oracles against the vision profile's
           llama-server (spawning it through the pool if needed) and the
           live Qdrant; exit 1 on any failure or pin mismatch. This is
           what `just check-drift` runs before `just eval-smoke`.
"""

from __future__ import annotations

import argparse
import json
import sys

from src.drift import oracles, pins, provenance, tripwire


def _print_status(prov: dict) -> list[dict]:
    print("provenance")
    for k, v in provenance.summary(prov).items():
        print(f"  {k:16} {v}")
    mismatches = pins.check_pins(prov)
    print(f"pins: {'all match' if not mismatches else str(len(mismatches)) + ' mismatch(es)'}")
    for m in mismatches:
        print(f"  {m['component']}: pinned {m['pinned']}, installed {m['installed']} - {m['note']}")
    cached = oracles.load_cached(prov["fingerprint"])
    if cached:
        print(f"oracles (cached {cached['ran_utc']}): {'OK' if cached['ok'] else 'FAILED'}")
        for r in cached["results"]:
            print(f"  {'✓' if r['ok'] else '✗'} {r['name']}: {r['detail']}")
    else:
        print("oracles: not yet run for this fingerprint (`python -m src.drift check`)")
    t = tripwire.summary()
    print(f"tripwire: {t['trips']} trip(s) / {t['checks']} checks this process; log {t['log']}")
    return mismatches


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.drift")
    ap.add_argument("command", choices=["status", "check"])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--force", action="store_true", help="re-run oracles even if cached")
    args = ap.parse_args(argv)

    prov = provenance.runtime_fingerprint()
    if args.command == "status":
        if args.json:
            print(json.dumps({"provenance": prov, "pins": pins.check_pins(prov),
                              "oracles": oracles.load_cached(prov["fingerprint"]),
                              "tripwire": tripwire.summary()}, indent=2))
            return 0
        _print_status(prov)
        return 0

    mismatches = _print_status(prov)
    base_url = None
    # This process is about to run the oracles itself; claim the fingerprint
    # so the pool's on-spawn idle hook does not start a second, concurrent run.
    oracles._scheduled.add(prov["fingerprint"])
    try:
        from src.inference.llama_server_pool import get_pool
        from src.inference.profiles import default_vision_profile

        prof = default_vision_profile()
        if prof:
            print(f"\nspawning/attaching llama-server for {prof!r} …")
            base_url = get_pool().get_url_for(prof)
    except Exception as e:  # noqa: BLE001
        print(f"  llama-server unavailable ({e}); server oracles will be skipped")
    rec = oracles.ensure_for_fingerprint(prov["fingerprint"], base_url, force=args.force)
    print(f"\noracles ({rec['ran_utc']}): {'OK' if rec['ok'] else 'FAILED'}")
    for r in rec["results"]:
        print(f"  {'✓' if r['ok'] else '✗'} {r['name']}: {r['detail']}")
    if args.json:
        print(json.dumps(rec, indent=2))
    return 0 if rec["ok"] and not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
