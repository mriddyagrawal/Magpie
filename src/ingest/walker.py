"""Router-driven batch ingest walker.

Entry point: `python -m src.ingest <path>`.

For each file under `<path>` the walker:
  1. Checks the manifest. If size is unchanged (and not --force), skips.
  2. Calls `router.peek()` + `router.decide()` to pick the tier.
  3. Dispatches to the right tier worker in `src/ingest/`.
  4. Writes a summary markdown (or records skip) into the manifest.
  5. Records the full router verdict as audit trail via `manifest.mark_routed`.

Stage 2 ingest (`python -m src.stage2 ingest`) then picks up the markdowns
and embeds them into Qdrant — unchanged.

This replaces `src/stage1/summarize.py`'s dispatch. The legacy walker is
still available at `python -m src.stage1.summarize` for comparison during
benchmarking; it routes every file through T3.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.content import SummarizeError
from src.ingest.common import source_rel_path
from src.ingest.ignore import IgnoreRules
from src.ingest import tier0, tier1, tier2, tier3, tier4
from src.manifest import REPO_ROOT, Manifest
from src.router import (
    PeekResult,
    RouteDecision,
    Tier,
    decide,
    load_nasconfig,
    peek,
)


# ---------------------------------------------------------------------------
# Tier dispatch
# ---------------------------------------------------------------------------

def _choose_primary_tier(decision: RouteDecision) -> Tier | None:
    """Pick which single tier to run this pass. MVP: one primary tier per file.

    Priority: T3 > T2 > T4 > T1 > T0.
    Additional tiers in `decision.routes` are deferred — logged and left for
    a later pass. T4 falls back to T3 when not yet wired (see below).
    """
    if not decision.routes:
        return None
    for t in ("T3", "T2", "T4", "T1", "T0"):
        if t in decision.routes:
            return t  # type: ignore[return-value]
    return None


async def _run_tier(
    tier: Tier,
    path: Path,
    source_rel: str,
    agent,
    manifest: Manifest,
):
    """Dispatch to the matching worker. Each returns (outcome, optional_note)."""
    if tier == "T1":
        return await asyncio.to_thread(tier1.run, path, source_rel), None
    if tier == "T2":
        return await asyncio.to_thread(tier2.run, path, source_rel), None
    if tier == "T0":
        return await asyncio.to_thread(tier0.run, path, source_rel), None
    if tier == "T3":
        if agent is None:
            raise RuntimeError("T3 requested but no LLM agent was provided")
        outcome = await tier3.run_async(path, source_rel, agent)
        return outcome, None
    if tier == "T4":
        outcome = await asyncio.to_thread(tier4.run, path, source_rel, manifest)
        return outcome, None
    raise ValueError(f"unknown tier: {tier}")


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

# Extensions the router knows how to peek. Anything else is silently skipped.
_CONSIDERED_EXTS = {
    ".txt", ".md", ".markdown", ".log",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".swift", ".kt",
    ".sh", ".sql",
    ".json", ".yaml", ".yml", ".toml",
    ".csv",
    ".pdf", ".docx", ".xlsx", ".xlsm",
    ".pptx", ".html", ".htm", ".ipynb",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
}


def find_candidates(
    root: Path,
    *,
    ignore_rules: IgnoreRules | None = None,
) -> tuple[list[Path], int]:
    """Walk `root` and return (accepted, ignored_count).

    `ignore_rules` applies cascading `.gitignore` / `.nasignore` + built-in
    defaults (`node_modules/`, `__pycache__/`, `.git/`, etc.). If omitted,
    rules are built from `root` on the fly.
    """
    rules = ignore_rules if ignore_rules is not None else IgnoreRules.from_root(root)
    accepted: list[Path] = []
    ignored = 0
    for p in root.rglob("*"):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in _CONSIDERED_EXTS:
            continue
        if rules.is_ignored(p):
            ignored += 1
            continue
        accepted.append(p)
    return sorted(accepted), ignored


# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------

def _gpu_available() -> bool:
    """Return True if CUDA or MPS is usable. Defensive against missing torch."""
    try:
        import torch  # deferred
    except ImportError:
        return False
    try:
        if torch.cuda.is_available():
            return True
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return True
    except Exception:  # pylint: disable=broad-except
        pass
    return False


# ---------------------------------------------------------------------------
# Walker core
# ---------------------------------------------------------------------------

async def ingest_one(
    path: Path,
    manifest: Manifest,
    agent,
    *,
    gpu_available: bool,
    t4_budget_used_mb: float,
    force: bool = False,
) -> tuple[RouteDecision, float]:
    """Ingest a single file. Returns (decision, added_t4_mb)."""
    source_rel = source_rel_path(path)
    size = path.stat().st_size

    existing = manifest.get(source_rel)
    if not force and existing is not None and existing.size == size and existing.summary_file:
        return (
            RouteDecision(
                routes=list(existing.routes) or [],
                visual_score=existing.visual_score,
                sensitivity_score=existing.sensitivity_score,
                t4_cost_mb=existing.t4_cost_mb,
                t4_cost_s=existing.t4_cost_s,
                criticality=existing.criticality,
                criticality_source=existing.criticality_source,
                skip_reason="unchanged",
                notes=["manifest hit, size match"],
            ),
            0.0,
        )

    peek_result = peek(path)
    nasconfig = load_nasconfig(path)
    decision = decide(
        peek_result,
        nasconfig=nasconfig,
        gpu_available=gpu_available,
        t4_budget_used_mb=t4_budget_used_mb,
    )

    if decision.skipped:
        manifest.mark_routed(
            source_rel, size,
            routes=decision.routes,
            visual_score=decision.visual_score,
            sensitivity_score=decision.sensitivity_score,
            t4_cost_mb=decision.t4_cost_mb,
            t4_cost_s=decision.t4_cost_s,
            criticality=decision.criticality,
            criticality_source=decision.criticality_source,
            skip_reason=decision.skip_reason,
        )
        return decision, 0.0

    primary = _choose_primary_tier(decision)
    if primary is None:
        manifest.mark_routed(
            source_rel, size,
            routes=decision.routes,
            visual_score=decision.visual_score,
            sensitivity_score=decision.sensitivity_score,
            t4_cost_mb=decision.t4_cost_mb,
            t4_cost_s=decision.t4_cost_s,
            criticality=decision.criticality,
            criticality_source=decision.criticality_source,
            skip_reason="no_tier_selected",
        )
        return decision, 0.0

    old_summary_rel = existing.summary_file if existing else None
    outcome, note = await _run_tier(primary, path, source_rel, agent, manifest)
    if note:
        decision = RouteDecision(
            routes=decision.routes,
            visual_score=decision.visual_score,
            sensitivity_score=decision.sensitivity_score,
            t4_cost_mb=decision.t4_cost_mb,
            t4_cost_s=decision.t4_cost_s,
            criticality=decision.criticality,
            criticality_source=decision.criticality_source,
            skip_reason=decision.skip_reason,
            notes=list(decision.notes) + [note],
        )

    # T4 manages its own manifest state (fast_indexed_at) inside the worker.
    # Other tiers produce a summary markdown we need to register.
    if outcome.summary_file_rel is not None:
        manifest.mark_summarized(source_rel, size, outcome.summary_file_rel)
    manifest.mark_routed(
        source_rel, size,
        routes=decision.routes,
        visual_score=decision.visual_score,
        sensitivity_score=decision.sensitivity_score,
        t4_cost_mb=decision.t4_cost_mb,
        t4_cost_s=decision.t4_cost_s,
        criticality=decision.criticality,
        criticality_source=decision.criticality_source,
        skip_reason=None,
    )

    # Retire old summary if the digest changed.
    if old_summary_rel and old_summary_rel != outcome.summary_file_rel:
        _delete_if_exists(old_summary_rel)

    added_t4 = decision.t4_cost_mb if "T4" in decision.routes else 0.0
    return decision, added_t4


def _delete_if_exists(rel_path: str) -> None:
    p = REPO_ROOT / rel_path
    if p.is_absolute() and p.exists():
        p.unlink()


def _format_decision_line(path: Path, decision: RouteDecision, source_rel: str) -> str:
    """One-line per-file summary for `--verbose` mode."""
    if decision.skipped:
        return f"  SKIP  {source_rel:<60}  ({decision.skip_reason})"
    primary = _choose_primary_tier(decision) or "-"
    route_str = "+".join(decision.routes) if decision.routes else "-"
    badge = f"[{primary}]" if route_str == primary else f"[{route_str}]"
    detail = (
        f"visual={decision.visual_score} sens={decision.sensitivity_score} "
        f"crit={decision.criticality}"
    )
    if decision.t4_cost_mb > 0:
        detail += f" t4_mb={decision.t4_cost_mb:.1f} t4_s={decision.t4_cost_s:.0f}"
    return f"  {badge:<10}  {source_rel:<60}  ({detail})"


async def run_batch(
    root: Path,
    *,
    force: bool = False,
    concurrency: int = 4,
    verbose: bool = False,
) -> None:
    from tqdm import tqdm

    load_dotenv()
    manifest = Manifest()

    ignore_rules = IgnoreRules.from_root(root)
    files, ignored_count = find_candidates(root, ignore_rules=ignore_rules)
    if not files and ignored_count == 0:
        print(f"no indexable files found under {root}")
        return
    if not files:
        print(
            f"no indexable files under {root} after ignore rules "
            f"({ignored_count} filtered out)"
        )
        return

    # Manifest prune for files that vanished under this root. When the walked
    # root lives under REPO_ROOT we scope the prune to repo-relative prefixes;
    # otherwise the manifest key is the absolute path and we scope on that.
    try:
        root_rel = str(root.resolve().relative_to(REPO_ROOT)) + os.sep
    except ValueError:
        root_rel = str(root.resolve()) + os.sep
    existing_rels = {source_rel_path(p) for p in files}
    pruned = 0
    for rel in list(manifest.paths()):
        if rel.startswith(root_rel) and rel not in existing_rels:
            entry = manifest.drop(rel)
            if entry and entry.summary_file:
                _delete_if_exists(entry.summary_file)
                pruned += 1

    # Defer LLM agent construction until we actually need it (many corpora will
    # be entirely T1/T2/T0 and shouldn't require an API key).
    agent = None

    def get_agent():
        nonlocal agent
        if agent is None:
            from src.stage1.summarize import build_agent as _build
            agent = _build()
        return agent

    gpu = _gpu_available()
    t4_used_mb = 0.0
    sem = asyncio.Semaphore(concurrency)
    manifest_lock = asyncio.Lock()
    stats: dict[str, int] = {
        "T0": 0, "T1": 0, "T2": 0, "T3": 0, "T4": 0,
        "skipped": 0, "unchanged": 0, "errors": 0,
    }

    bar = tqdm(total=len(files), desc="indexing", unit="file")

    async def worker(path: Path):
        nonlocal t4_used_mb
        rel = source_rel_path(path)
        try:
            async with sem:
                bar.set_postfix_str(path.name[:40])
                # Acquire LLM agent lazily per decision.
                decision_for_agent_check = decide(
                    peek(path),
                    nasconfig=load_nasconfig(path),
                    gpu_available=gpu,
                    t4_budget_used_mb=t4_used_mb,
                )
                chosen = _choose_primary_tier(decision_for_agent_check)
                need_agent = chosen in ("T3", "T4")
                a = get_agent() if need_agent else None

                async with manifest_lock:
                    current_budget = t4_used_mb
                decision, added = await ingest_one(
                    path, manifest, a,
                    gpu_available=gpu,
                    t4_budget_used_mb=current_budget,
                    force=force,
                )
                async with manifest_lock:
                    t4_used_mb += added

                if decision.skipped:
                    if decision.skip_reason == "unchanged":
                        stats["unchanged"] += 1
                    else:
                        stats["skipped"] += 1
                else:
                    primary = _choose_primary_tier(decision)
                    if primary:
                        stats[primary] += 1

                if verbose:
                    tqdm.write(_format_decision_line(path, decision, rel))
        except SummarizeError as e:
            stats["errors"] += 1
            tqdm.write(f"  skip: {rel}: {e}")
        except Exception as e:  # pylint: disable=broad-except
            stats["errors"] += 1
            tqdm.write(f"  error: {rel}: {type(e).__name__}: {e}")
        finally:
            bar.update(1)

    try:
        await asyncio.gather(*(worker(p) for p in files))
    finally:
        bar.close()
        manifest.save()

    total = len(files)
    print(
        f"\ndone: {total} considered — "
        f"T0={stats['T0']} T1={stats['T1']} T2={stats['T2']} T3={stats['T3']} "
        f"T4={stats['T4']} unchanged={stats['unchanged']} skipped={stats['skipped']} "
        f"errors={stats['errors']} pruned={pruned} ignored={ignored_count} "
        f"gpu={'yes' if gpu else 'no'} t4_used_mb={t4_used_mb:.1f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="nas-ingest",
        description=(
            "Router-driven ingest — walks a directory, writes summaries, "
            "and pushes them to Qdrant in one command. "
            "See Plans/Indexing Tiers.md."
        ),
    )
    parser.add_argument("path", help="Directory to walk.")
    parser.add_argument("--force", action="store_true",
                        help="Re-ingest every file regardless of manifest state.")
    parser.add_argument("--concurrency", type=int, default=4,
                        help="Max concurrent files (default: 4).")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print per-file routing decision (tier + scores + criticality).")
    parser.add_argument(
        "--no-push",
        action="store_true",
        help=(
            "Skip the Stage 2 Qdrant push at the end. Leaves new summaries in "
            "Test Summaries/ with `ingested_at=None`; run `python -m src.stage2 "
            "ingest` later to push them manually."
        ),
    )
    args = parser.parse_args()

    root = Path(args.path)
    if not root.exists():
        sys.exit(f"error: no such path: {root}")
    if not root.is_dir():
        sys.exit(f"error: ingest walker expects a directory, got: {root}")
    asyncio.run(run_batch(
        root,
        force=args.force,
        concurrency=args.concurrency,
        verbose=args.verbose,
    ))

    # Stage 2 push: read the manifest, embed new/changed rows, upsert into
    # Qdrant. This is the step users most often forgot to run — folding it in
    # here means a single invocation makes the corpus searchable.
    if args.no_push:
        print(
            "\nstage 2 push skipped (--no-push). "
            "Run `python -m src.stage2 ingest` to make new summaries searchable."
        )
        return
    print("\npushing new summaries to Qdrant...")
    try:
        from src.stage2.__main__ import ingest_from_manifest
        stats = ingest_from_manifest(force=False)
        print(
            f"qdrant: upserted {stats['upserted']} points, "
            f"{stats['orphans_deleted']} orphans cleaned, "
            f"{stats['total_points']} total manifest rows"
        )
    except RuntimeError as e:
        # Empty manifest is fine (everything was unchanged/skipped); anything
        # else likely means missing Qdrant creds — tell the user and bail soft.
        print(f"stage 2 push skipped: {e}", file=sys.stderr)
    except Exception as e:  # pylint: disable=broad-except
        print(
            f"stage 2 push failed: {type(e).__name__}: {e}\n"
            f"run `python -m src.stage2 ingest` manually to retry.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
