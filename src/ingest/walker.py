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
    USEFUL_DOTFILE_NAMES as _USEFUL_DOTFILE_NAMES,
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
    get_agent,
    manifest: Manifest,
    *,
    force: bool = False,
    inflight: dict[str, asyncio.Event] | None = None,
    inflight_lock: asyncio.Lock | None = None,
):
    """Dispatch to the matching worker. Each returns (outcome, optional_note).

    `get_agent` is a zero-arg callable that lazily builds the LLM agent — only
    called from the T3 branch so non-LLM tiers don't pay the construction cost.
    Pass `None` if T3 is impossible (test fixtures, T4-only paths).

    `inflight` + `inflight_lock` are the per-walk content-hash dedup map.
    Currently consumed only by T3 (the most expensive tier — Phase A);
    other tiers ignore them. See `tier3.run_async` for the protocol.
    """
    if tier == "T1":
        return await asyncio.to_thread(tier1.run, path, source_rel), None
    if tier == "T2":
        return await asyncio.to_thread(tier2.run, path, source_rel), None
    if tier == "T0":
        return await asyncio.to_thread(tier0.run, path, source_rel), None
    if tier == "T3":
        if get_agent is None:
            raise RuntimeError("T3 requested but no LLM agent thunk was provided")
        agent = get_agent()
        outcome = await tier3.run_async(
            path, source_rel, agent,
            inflight=inflight, inflight_lock=inflight_lock,
        )
        return outcome, None
    if tier == "T4":
        # T4 has its own size-skip check inside index_file; thread `force`
        # through so --force / --rebuild actually re-encode existing pages.
        outcome = await asyncio.to_thread(
            tier4.run, path, source_rel, manifest, force=force
        )
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

# Data-flavored extensions that default to SKIPPED. Real-world corpora often
# carry hundreds-to-thousands of these (config dumps, dataset exports, schema
# files, old .dat blobs) that bloat the index without typically being what
# the user actually queries. Re-enable per-run with `--include-data`.
#
# `.dat` isn't in `_CONSIDERED_EXTS` — opting in via `--include-data` adds
# it to the considered set so the router peeks it as text (most `.dat` files
# in user corpora are CSV-ish or fixed-width text dumps; binary `.dat` will
# fail the peek's UTF-8 check and route to skip).
_DATA_EXTS_DEFAULT_OFF = {".json", ".csv", ".dat"}


# `_USEFUL_DOTFILE_NAMES` is imported from src.router so the router's `peek`
# / `decide` see the same set as the walker's filter. Single source of truth
# lives in router because router is the deeper module (walker imports from
# router; the reverse would be a circular dependency).
#
# Deliberately NOT included in that allowlist:
#   .env, .npmrc, .netrc, .pgpass, .git-credentials  → secrets
#   .gitignore                                        → meta-only, not content
#   .DS_Store, .ipynb_checkpoints                     → OS / app cruft


# Extensions of files we consider "documents" (as opposed to images). Used by
# the asset-library-folder heuristic: a folder with many images and zero docs
# is treated as an asset library and its images are skipped wholesale.
_DOCUMENT_EXTS = {
    ".txt", ".md", ".markdown", ".log",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".swift", ".kt",
    ".sh", ".sql",
    ".json", ".yaml", ".yml", ".toml",
    ".csv",
    ".pdf", ".docx", ".xlsx", ".xlsm",
    ".pptx", ".html", ".htm", ".ipynb",
}
_IMAGE_EXTS_FOR_FILTER = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# Threshold for the sibling-density rule. A folder is treated as an asset
# library if it has at least this many images AND zero document files. Chosen
# by observation: real working folders with "a few reference pics next to
# notes" have <5 images; dedicated asset libraries (course media, stock photo
# folders, scraped galleries) commonly have 20–500+. 15 is comfortably above
# the "a few reference pics" ceiling and below the "real asset library" floor.
_ASSET_LIBRARY_MIN_IMAGES = 15


def _asset_library_folders(paths: list[Path]) -> set[Path]:
    """Return the set of folders that look like asset libraries.

    A folder qualifies if, among its own immediate children, there are at
    least `_ASSET_LIBRARY_MIN_IMAGES` image files AND zero document files.
    Subfolder contents are NOT counted — the check is strictly per-folder, so
    `sem6/` won't be flagged just because it contains `sem6/assets/`.

    This is a structural replacement for naming-based path patterns (like
    `mediasources-4ed/`): instead of encoding every possible asset-folder
    name into `.nasignore`, we detect the *shape* — image-dominated folders
    with no documents — regardless of what the user named them.
    """
    # Group files by their immediate parent directory.
    from collections import defaultdict
    by_folder_images: dict[Path, int] = defaultdict(int)
    by_folder_docs: dict[Path, int] = defaultdict(int)
    for p in paths:
        ext = p.suffix.lower()
        parent = p.parent
        if ext in _IMAGE_EXTS_FOR_FILTER:
            by_folder_images[parent] += 1
        elif ext in _DOCUMENT_EXTS:
            by_folder_docs[parent] += 1

    return {
        folder
        for folder, n_images in by_folder_images.items()
        if n_images >= _ASSET_LIBRARY_MIN_IMAGES and by_folder_docs.get(folder, 0) == 0
    }


def _include_dotfiles_for(
    dirpath: Path,
    *,
    walk_root: Path,
    cache: dict[Path, bool],
) -> bool:
    """Whether `dirpath` opts in to indexing dotfiles / dot-folders.

    Reads `.nasconfig.yaml` walking up from `dirpath` toward (but not past)
    `walk_root`'s parent. Caches per-directory results so a deep walk of
    one tree doesn't reload nasconfig for every leaf folder.
    """
    if dirpath in cache:
        return cache[dirpath]
    try:
        cfg = load_nasconfig(dirpath, stop_at=walk_root.parent)
    except Exception:  # pylint: disable=broad-except
        cfg = {}
    flag = bool(cfg.get("include_dotfiles", False))
    cache[dirpath] = flag
    return flag


def find_candidates(
    root: Path,
    *,
    ignore_rules: IgnoreRules | None = None,
    include_data: bool = False,
) -> tuple[list[Path], int, int]:
    """Walk `root` and return (accepted, ignored_count, asset_library_skipped).

    `ignore_rules` applies cascading `.gitignore` / `.nasignore` + built-in
    defaults (`node_modules/`, `__pycache__/`, `.git/`, etc.). If omitted,
    rules are built from `root` on the fly.

    Three filter layers run in order:

    1. **Dot-folder prune** during traversal — dot-folders (`.config/`,
       `.codex/`, `.antigravity/`, `.cache/`, etc.) are pruned in-place
       so their contents are never even listed. App caches and IDE state
       at home-directory scale explode the candidate list otherwise.
    2. **Leaf-dotfile filter** — leaf-name dotfiles default to skipped,
       except the small `_USEFUL_DOTFILE_NAMES` allowlist (`.bashrc`,
       `.vimrc`, `.gitconfig`, etc.) which actually carry user content.
    3. **Asset-library folder rule** — folders dominated by images with
       zero documents are treated as asset libraries and their images
       are dropped wholesale (post-walk, structural).

    Both layers (1) and (2) are **disabled** for a subtree when its
    nearest-ancestor `.nasconfig.yaml` says `include_dotfiles: true`. The
    built-in default ignore patterns (secrets, `node_modules/`, etc.)
    still apply — opting in to dotfiles doesn't disable safety rails.

    `os.walk` (not `Path.rglob`) is used so step 1 can mutate the
    children list in-place during traversal — `rglob` doesn't expose
    a prune hook.
    """
    rules = ignore_rules if ignore_rules is not None else IgnoreRules.from_root(root)
    pre_accepted: list[Path] = []
    ignored = 0
    nasconfig_cache: dict[Path, bool] = {}

    # Build the active extension whitelist for this run. `--include-data`
    # adds `.dat` (which the router will peek as text), and stops the
    # data-skip filter from dropping `.json` / `.csv` later.
    considered_exts = set(_CONSIDERED_EXTS)
    if include_data:
        considered_exts |= _DATA_EXTS_DEFAULT_OFF

    for dirpath, dirnames, filenames in os.walk(root):
        dirpath_p = Path(dirpath)
        include_dot = _include_dotfiles_for(
            dirpath_p, walk_root=root.resolve(), cache=nasconfig_cache,
        )

        # Prune dot-folders during traversal — unless the user opted in. Note
        # we do NOT count these in `ignored`: they're a category-skip, not a
        # per-file ignore-rule hit.
        if not include_dot:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

        # Prune directories matching built-in default-ignore patterns
        # (node_modules, Program Files, target, etc.). Without this, we'd
        # descend into a 50k-file npm package just to filter every file
        # individually — minutes-to-hours of pointless `os.stat` calls on
        # large corpora.
        dirnames[:] = [
            d for d in dirnames
            if not rules.is_default_ignored_dir(dirpath_p / d)
        ]

        for fname in filenames:
            # Leaf dotfile filter — allowlisted ones survive (.bashrc et al.),
            # and `include_dotfiles: true` lets all of them through.
            if fname.startswith("."):
                if not include_dot and fname not in _USEFUL_DOTFILE_NAMES:
                    continue
            p = dirpath_p / fname
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext not in considered_exts:
                # Useful dotfiles (and any dotfile under `include_dotfiles: true`
                # that has no extension) bypass the considered-ext check.
                if fname not in _USEFUL_DOTFILE_NAMES and not (
                    include_dot and fname.startswith(".")
                ):
                    continue
            # Data-extension default-skip: `--include-data` re-adds .json/.csv/.dat
            # to `considered_exts` above, so this block only fires when the user
            # has NOT opted in.
            if not include_data and ext in _DATA_EXTS_DEFAULT_OFF:
                continue
            if rules.is_ignored(p):
                ignored += 1
                continue
            pre_accepted.append(p)

    asset_folders = _asset_library_folders(pre_accepted)
    accepted: list[Path] = []
    asset_skipped = 0
    for p in pre_accepted:
        if p.parent in asset_folders and p.suffix.lower() in _IMAGE_EXTS_FOR_FILTER:
            asset_skipped += 1
            continue
        accepted.append(p)

    return sorted(accepted), ignored, asset_skipped


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
    get_agent,
    *,
    gpu_available: bool,
    t4_budget_used_mb: float,
    force: bool = False,
    inflight: dict[str, asyncio.Event] | None = None,
    inflight_lock: asyncio.Lock | None = None,
) -> tuple[RouteDecision, float, "TierOutcome | None"]:
    """Ingest a single file. Returns (decision, added_t4_mb, outcome).

    `outcome` is None for skipped/no-tier paths and the early "unchanged"
    return; populated otherwise. Walker workers read `outcome.deduped` for
    stats and `outcome.content_hash` to record on the manifest.
    """
    from src.ingest.common import TierOutcome  # local import for return-type ref
    source_rel = source_rel_path(path)
    size = path.stat().st_size

    existing = manifest.get(source_rel)
    # File is "done" if it's been processed by SOME tier — either the
    # summary tier (T0-T3 → summary_file set) OR the fast tier
    # (T4 → fast_indexed_at set). Image files routed to T4-only have
    # no summary_file, so the original `existing.summary_file` check
    # was always False for them, causing them to be re-routed every
    # ingest run (the inner index_file would short-circuit but the
    # walker's stats line would misleadingly report T4=N for files
    # that did zero work).
    already_done = existing is not None and (
        bool(existing.summary_file) or existing.fast_indexed_at is not None
    )
    if not force and existing is not None and existing.size == size and already_done:
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
            None,
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
        return decision, 0.0, None

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
        return decision, 0.0, None

    old_summary_rel = existing.summary_file if existing else None
    outcome, note = await _run_tier(
        primary, path, source_rel, get_agent, manifest, force=force,
        inflight=inflight, inflight_lock=inflight_lock,
    )
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
    if outcome.content_hash is not None:
        manifest.mark_content_hash(source_rel, outcome.content_hash)
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

    # Retire old summary if the digest changed AND no other manifest
    # row still points at it. With content-hash dedup, multiple paths
    # can share one summary file: only the LAST holder gets to delete it
    # when the content changes.
    if old_summary_rel and old_summary_rel != outcome.summary_file_rel:
        still_in_use = any(
            e.summary_file == old_summary_rel
            for rel, e in manifest.entries.items()
            if rel != source_rel
        )
        if not still_in_use:
            _delete_if_exists(old_summary_rel)

    added_t4 = decision.t4_cost_mb if "T4" in decision.routes else 0.0
    return decision, added_t4, outcome


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


# How many files to ingest before checkpointing (manifest save + intermediate
# Qdrant flush). Aligned so summarization-on-disk and Qdrant index never drift
# more than CHUNK_SIZE files apart. If the run dies mid-walk, you lose at most
# CHUNK_SIZE files of Qdrant indexing — the manifest auto-recovers from disk
# via `bootstrap_manifest_from_existing`, so summarization work is preserved.
CHUNK_SIZE = 100


async def run_batch(
    root: Path,
    *,
    force: bool = False,
    concurrency: int = 4,
    verbose: bool = False,
    include_data: bool = False,
    push_to_qdrant: bool = False,
    chunk_size: int = CHUNK_SIZE,
    progress_callback=None,
    stop_event=None,
) -> None:
    from tqdm import tqdm

    load_dotenv()
    manifest = Manifest()

    # Pre-walk phase: scan for .gitignore/.nasignore + enumerate candidate
    # files. On large corpora (~10 GB+) this can take a minute or two before
    # the indexing bar appears — print progress so the user knows it isn't
    # hung. Both walks now prune default-ignored directories (node_modules/,
    # Program Files/, etc.) so this scales much better than it used to.
    import time
    print(f"scanning {root} for ignore rules and candidate files...", flush=True)
    t0 = time.monotonic()
    ignore_rules = IgnoreRules.from_root(root)
    t_ignore = time.monotonic() - t0
    files, ignored_count, asset_lib_skipped = find_candidates(
        root, ignore_rules=ignore_rules, include_data=include_data,
    )
    t_total = time.monotonic() - t0
    print(
        f"  scan done in {t_total:.1f}s "
        f"(ignore-rules: {t_ignore:.1f}s, candidates: {t_total - t_ignore:.1f}s)\n"
        f"  found {len(files)} files to consider, {ignored_count} ignored, "
        f"{asset_lib_skipped} dropped by asset-library rule",
        flush=True,
    )
    if not files and ignored_count == 0 and asset_lib_skipped == 0:
        print(f"no indexable files found under {root}")
        return
    if not files:
        print(
            f"no indexable files under {root} after filters "
            f"({ignored_count} ignored, {asset_lib_skipped} in asset-library folders)"
        )
        return

    if progress_callback:
        progress_callback(0, len(files), None)
    if asset_lib_skipped:
        print(
            f"skipped {asset_lib_skipped} images in {root} "
            f"(asset-library folders: ≥{_ASSET_LIBRARY_MIN_IMAGES} images + 0 docs)"
        )

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
    # Phase A content-hash dedup: per-walk map from `<digest>` to an Event.
    # First worker to claim a digest runs the tier; peers await the event
    # and reuse the on-disk summary. Cross-walk dedup (digest already on
    # disk from a prior walk) is handled inside `tier3.run_async` via an
    # `out_path.exists()` check before the LLM call.
    inflight_hashes: dict[str, asyncio.Event] = {}
    inflight_lock = asyncio.Lock()
    stats: dict[str, int] = {
        "T0": 0, "T1": 0, "T2": 0, "T3": 0, "T4": 0,
        "skipped": 0, "unchanged": 0, "errors": 0, "deduped": 0,
    }

    # Periodic-save baseline so a Ctrl-C never loses more than ~30s of
    # already-completed work. Without this, manifest is written only when
    # asyncio.gather() returns — interruption mid-walker discards every
    # mark_summarized / mark_routed / mark_fast_indexed update from the
    # in-flight run, even though the on-disk artifacts (summary markdowns,
    # fast_tier vectors) are already there.
    last_save_t = time.monotonic()
    SAVE_INTERVAL_S = 30.0

    bar = tqdm(total=len(files), desc="indexing", unit="file")

    async def worker(path: Path):
        nonlocal t4_used_mb, last_save_t
        if stop_event is not None and stop_event.is_set():
            bar.update(1)
            stats["skipped"] += 1
            if progress_callback:
                progress_callback(bar.n, len(files), None)
            return
        rel = source_rel_path(path)
        if progress_callback:
            progress_callback(bar.n, len(files), path.name)
        try:
            async with sem:
                bar.set_postfix_str(path.name[:40])
                async with manifest_lock:
                    current_budget = t4_used_mb
                decision, added, outcome = await ingest_one(
                    path, manifest, get_agent,
                    gpu_available=gpu,
                    t4_budget_used_mb=current_budget,
                    force=force,
                    inflight=inflight_hashes,
                    inflight_lock=inflight_lock,
                )
                async with manifest_lock:
                    t4_used_mb += added
                    # Persist progress at most every SAVE_INTERVAL_S seconds.
                    # Lock held to avoid two workers racing the file write.
                    now = time.monotonic()
                    if now - last_save_t >= SAVE_INTERVAL_S:
                        manifest.save()
                        last_save_t = now

                if decision.skipped:
                    if decision.skip_reason == "unchanged":
                        stats["unchanged"] += 1
                    else:
                        stats["skipped"] += 1
                else:
                    primary = _choose_primary_tier(decision)
                    if primary:
                        stats[primary] += 1
                    if outcome is not None and outcome.deduped:
                        stats["deduped"] += 1

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
            if progress_callback:
                progress_callback(bar.n, len(files), None)

    def _flush_chunk(chunk_idx: int) -> None:
        """Save the manifest, then push new entries to Qdrant (no orphan sweep).

        Runs between chunks, when no workers are active — no lock needed.
        Wraps the Qdrant push in a broad except so a transient cluster
        failure doesn't kill the walk; the next flush (or the end-of-walk
        push in `main()`) will catch up.
        """
        manifest.save()
        if not push_to_qdrant:
            return
        try:
            from src.stage2.__main__ import ingest_from_manifest
            ingest_from_manifest(skip_orphan_cleanup=True)
        except RuntimeError:
            # "manifest is empty" or similar — nothing to push yet, fine.
            pass
        except Exception as e:  # pylint: disable=broad-except
            tqdm.write(
                f"  warn: chunk {chunk_idx} qdrant flush failed "
                f"({type(e).__name__}: {e}); will retry at end of walk"
            )

    try:
        for i in range(0, len(files), chunk_size):
            chunk = files[i : i + chunk_size]
            await asyncio.gather(*(worker(p) for p in chunk))
            _flush_chunk(i // chunk_size)
    finally:
        bar.close()
        manifest.save()  # final unconditional save

    total = len(files)
    print(
        f"\ndone: {total} considered — "
        f"T0={stats['T0']} T1={stats['T1']} T2={stats['T2']} T3={stats['T3']} "
        f"T4={stats['T4']} unchanged={stats['unchanged']} skipped={stats['skipped']} "
        f"errors={stats['errors']} pruned={pruned} ignored={ignored_count} "
        f"deduped={stats['deduped']} "
        f"gpu={'yes' if gpu else 'no'} t4_used_mb={t4_used_mb:.1f}"
    )


def _rebuild_clean_slate(root: Path) -> None:
    """Drop both Qdrant collections + clear manifest entries under `root`.

    Used by `--rebuild`. After this returns, the subsequent `run_batch` call
    will see an empty slate for files under this root and re-encode everything
    fresh — no zombies from earlier policy versions.
    """
    # 1. Drop summaries collection (Stage 2 will recreate on next push).
    try:
        from src.stage2.db import COLLECTION_NAME, get_qdrant_client
        client = get_qdrant_client()
        if client.collection_exists(COLLECTION_NAME):
            client.delete_collection(COLLECTION_NAME)
            print(f"  dropped Qdrant collection: {COLLECTION_NAME}")
    except SystemExit:
        # Missing creds — log and continue; user may be running --no-push.
        print("  warn: could not connect to Qdrant — skipping summary-collection drop",
              file=sys.stderr)
    except Exception as e:  # pylint: disable=broad-except
        print(f"  warn: drop summaries collection failed: {e}", file=sys.stderr)

    # 2. Drop fast_tier (multivector ColPali) collection.
    try:
        from src.stage2.fast_db import ensure_fast_collection
        ensure_fast_collection(recreate=True)
        print("  dropped + recreated Qdrant collection: fast_tier")
    except SystemExit:
        pass
    except Exception as e:  # pylint: disable=broad-except
        print(f"  warn: drop fast_tier collection failed: {e}", file=sys.stderr)

    # 3. Clear manifest entries under `root` and remove their summary files.
    try:
        root_rel_under_repo = str(root.resolve().relative_to(REPO_ROOT)) + os.sep
    except ValueError:
        root_rel_under_repo = str(root.resolve()) + os.sep
    manifest = Manifest()
    dropped = 0
    for rel in list(manifest.paths()):
        if rel.startswith(root_rel_under_repo):
            entry = manifest.drop(rel)
            if entry and entry.summary_file:
                _delete_if_exists(entry.summary_file)
            dropped += 1
    manifest.save()
    print(f"  cleared {dropped} manifest entries under {root}")


def _fast_tier_orphan_cleanup(manifest: Manifest) -> int:
    """Drop fast_tier points whose source path no longer exists in the manifest.

    Mirrors Stage 2's summary-collection orphan cleanup. Necessary so that
    files dropped by the asset-library rule (or any other manifest removal)
    don't leave zombie ColPali patches on disk forever.
    """
    try:
        from src.stage2.fast_db import delete_path, get_indexed_paths
    except ImportError:
        return 0
    try:
        manifest_paths = set(manifest.paths())
        indexed = get_indexed_paths()
    except Exception as e:  # pylint: disable=broad-except
        print(f"  warn: fast_tier orphan check failed: {e}", file=sys.stderr)
        return 0

    orphans = indexed - manifest_paths
    deleted = 0
    for p in orphans:
        try:
            delete_path(p)
            deleted += 1
        except Exception as e:  # pylint: disable=broad-except
            print(f"  warn: fast_tier delete {p} failed: {e}", file=sys.stderr)
    return deleted


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

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--force",
        action="store_true",
        help=(
            "Re-encode every file under this root, including T4 ColPali pages. "
            "Use after a router-policy change to refresh existing entries. "
            "Other roots' data is untouched."
        ),
    )
    mode.add_argument(
        "--rebuild",
        action="store_true",
        help=(
            "DROP both Qdrant collections + clear all manifest entries under "
            "this root, then re-ingest from scratch. Use for a wholesale reset "
            "or recovery from a corrupted index."
        ),
    )

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
    parser.add_argument(
        "--include-data",
        action="store_true",
        help=(
            "Index data-flavored files (.json, .csv, .dat) that are skipped "
            "by default. Real-world corpora often have hundreds of these "
            "(config dumps, dataset exports) that bloat the index without "
            "being what users typically query. Use this when you do want "
            "them — e.g. you're searching across structured datasets."
        ),
    )
    parser.add_argument(
        "--per-child",
        action="store_true",
        help=(
            "Iterate immediate subdirectories of <path> and ingest each "
            "sequentially as its own batch. Useful for huge roots (multi-TB) "
            "where a single walk feels stuck — you see per-subdir progress "
            "lines, can Ctrl-C cleanly between chunks, and each scan is "
            "smaller. Stage 2 push still runs once at the end."
        ),
    )
    parser.add_argument(
        "--list-children",
        action="store_true",
        help=(
            "Print one ingest command per immediate subdirectory of <path> "
            "and exit. Use this to preview / cherry-pick before running "
            "(e.g. `... --list-children | head -20`). No filesystem walk."
        ),
    )
    args = parser.parse_args()

    root = Path(args.path)
    if not root.exists():
        sys.exit(f"error: no such path: {root}")
    if not root.is_dir():
        sys.exit(f"error: ingest walker expects a directory, got: {root}")

    # --list-children: just print would-be commands and exit. Cheap preview.
    if args.list_children:
        # Apply parent's ignore rules so the preview matches what `--per-child`
        # would actually run. Without this, $RECYCLE.BIN/, movies/, etc. show
        # up in the list even though they'd be filtered out at run time.
        parent_rules = IgnoreRules.from_root(root)
        all_children = sorted(p for p in root.iterdir() if p.is_dir())
        children = [
            c for c in all_children
            if not c.name.startswith(".") and not parent_rules.is_ignored(c)
        ]
        if not children:
            print(f"# {root} has no subdirectories (or all are ignored)")
            return
        flag_str = ""
        if args.force:
            flag_str += " --force"
        if args.rebuild:
            flag_str += " --rebuild"
        if args.verbose:
            flag_str += " -v"
        if args.no_push:
            flag_str += " --no-push"
        if args.include_data:
            flag_str += " --include-data"
        if args.concurrency != 4:
            flag_str += f" --concurrency {args.concurrency}"
        for c in children:
            print(f"uv run python -m src.ingest {c}{flag_str}")
        return

    # --rebuild: nuke everything under this root, then proceed with --force.
    if args.rebuild:
        print(f"=== REBUILD mode: clearing all state for {root} ===")
        _rebuild_clean_slate(root)
        print("=== rebuild done; starting fresh ingest ===\n")

    # `--force` and `--rebuild` both re-encode every file. After a rebuild
    # there's nothing to skip anyway, but force=True ensures the per-tier
    # skip checks (T4 in particular) honor the intent.
    force = args.force or args.rebuild

    if args.per_child:
        import time
        # Apply parent's ignore rules ($RECYCLE.BIN/, movies/, etc. from
        # DEFAULT_IGNORE_PATTERNS + /mnt/hardisk/.nasignore) BEFORE iterating
        # — otherwise we'd recurse into ignored subdirs because run_batch's
        # own IgnoreRules is rooted at that subdir and can't see rules from
        # the parent. Hidden dotfile dirs are also skipped to mirror the
        # walker's normal prune behavior.
        parent_rules = IgnoreRules.from_root(root)
        all_children = sorted(p for p in root.iterdir() if p.is_dir())
        top_files = sorted(p for p in root.iterdir() if p.is_file())
        children: list[Path] = []
        filtered: list[tuple[str, str]] = []
        for c in all_children:
            if c.name.startswith("."):
                filtered.append((c.name, "hidden"))
                continue
            if parent_rules.is_ignored(c):
                filtered.append((c.name, "ignore-rule"))
                continue
            children.append(c)
        if filtered:
            print(
                f"=== per-child filter: {len(filtered)} subdir(s) skipped at {root} ==="
            )
            for name, reason in filtered:
                print(f"  [skip-{reason}] {name}")
        if not children:
            print(f"warn: {root} has no eligible subdirectories — falling back to single-pass ingest")
            asyncio.run(run_batch(
                root, force=force, concurrency=args.concurrency,
                verbose=args.verbose, include_data=args.include_data,
            ))
        else:
            print(f"=== per-child mode: {len(children)} subdirectories under {root} ===")
            if top_files:
                print(
                    f"note: {len(top_files)} top-level file(s) in {root} will NOT "
                    "be ingested in --per-child mode (only subdirectories are "
                    "iterated). Run a single-pass ingest on the parent to pick "
                    "those up, or move them into a subdirectory."
                )
            t_start = time.monotonic()
            for i, c in enumerate(children, 1):
                print(f"\n=== [{i}/{len(children)}] {c} ===")
                asyncio.run(run_batch(
                    c, force=force, concurrency=args.concurrency,
                    verbose=args.verbose, include_data=args.include_data,
                ))
            print(
                f"\n=== per-child done: {len(children)} subdirectories in "
                f"{time.monotonic() - t_start:.1f}s ==="
            )
    else:
        asyncio.run(run_batch(
            root,
            force=force,
            concurrency=args.concurrency,
            verbose=args.verbose,
            include_data=args.include_data,
            push_to_qdrant=not args.no_push,
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
        stats = ingest_from_manifest(force=False, verbose=args.verbose)
        print(
            f"qdrant summaries: upserted {stats['upserted']} points, "
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

    # Fast-tier orphan cleanup: drop ColPali points for files that no longer
    # exist in the manifest. Without this, asset-library skips and `--rebuild`
    # leave zombie multi-vectors on disk indefinitely. Mirrors the
    # summary-collection orphan cleanup in `ingest_from_manifest`.
    try:
        deleted = _fast_tier_orphan_cleanup(Manifest())
        if deleted:
            print(f"qdrant fast_tier: dropped {deleted} orphaned source paths")
    except Exception as e:  # pylint: disable=broad-except
        print(f"fast_tier orphan cleanup failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
