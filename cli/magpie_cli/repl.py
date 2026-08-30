"""Interactive REPL for Magpie."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# The workspace root has `package = false` (it isn't packaged, it's just a
# workspace root), so the `src/*` modules aren't reachable via the normal
# dependency path when `ns` runs as an installed console script. Prepend the
# repo root to sys.path so `from src.pipeline import ...` works. `__file__`
# resolves to cli/magpie_cli/repl.py under uv's editable workspace install,
# so parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from rich.console import Console

from magpie_cli.display import (
    console,
    file_link,
    print_banner,
    print_error,
    print_help,
    print_result,
    print_setting,
    print_suggestions,
)

HISTORY_FILE = Path.home() / ".magpie_history"

# Dot-command menu shown when user starts their input with "."
DOT_COMMANDS: list[tuple[str, str]] = [
    (".help", "Show help"),
    (".rewrite", "Toggle Kimi query rewriting (on/off)"),
    (".fast", "Toggle ColPali visual tier (on/off) — off saves ~30s startup"),
    (".history", "Toggle conversation history (on/off/clear)"),
    (".top-k", "Set number of results to retrieve"),
    (".suggest", "Show question hints (add 'refresh' to regenerate)"),
    (".clear", "Clear the screen"),
]


class DotCommandCompleter(Completer):
    """Suggests dot-commands only when the user's input starts with a dot.

    Keeps the completion dropdown from shadowing normal question typing —
    the dropdown only appears once the user has typed the leading `.`.
    """

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("."):
            return
        for cmd, meta in DOT_COMMANDS:
            if cmd.startswith(text):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display_meta=meta,
                )

# Session state
_rewrite = False
_top_k = 5
_history_enabled = False
_history: list[tuple[str, str]] = []  # (question, answer) pairs from this session
_rerank = False  # Cross-encoder reranker; opt-in (see backlog B4 / src/stage2/rerank.py)
_fast = False    # ColPali visual tier; opt-in. Off saves the ~30s first-query
                 # weight load + ~1s/query encode. Visual-document searches
                 # (scanned PDFs, image-heavy decks) need this on.


def _handle_dot_command(cmd: str) -> bool:
    """Handle dot-commands. Returns True if the input was a command."""
    global _rewrite, _top_k, _history_enabled, _history, _rerank, _fast

    parts = cmd.strip().split()
    if not parts or not parts[0].startswith("."):
        return False

    match parts[0]:
        case ".help":
            print_help()
        case ".rewrite":
            if len(parts) < 2:
                print_setting("rewrite", "on" if _rewrite else "off")
            elif parts[1] in ("on", "true", "1"):
                _rewrite = True
                print_setting("rewrite", "on")
            elif parts[1] in ("off", "false", "0"):
                _rewrite = False
                print_setting("rewrite", "off")
            else:
                print_error("usage: .rewrite on/off")
        case ".history":
            if len(parts) < 2:
                state = "on" if _history_enabled else "off"
                print_setting("history", f"{state} ({len(_history)} turns stored)")
            elif parts[1] in ("on", "true", "1"):
                _history_enabled = True
                print_setting("history", "on")
            elif parts[1] in ("off", "false", "0"):
                _history_enabled = False
                print_setting("history", "off")
            elif parts[1] == "clear":
                _history.clear()
                print_setting("history", "cleared")
            else:
                print_error("usage: .history on/off/clear")
        case ".top-k":
            if len(parts) < 2:
                print_setting("top-k", str(_top_k))
            else:
                try:
                    _top_k = max(1, int(parts[1]))
                    print_setting("top-k", str(_top_k))
                except ValueError:
                    print_error("usage: .top-k N (integer)")
        case ".rerank":
            if len(parts) < 2:
                print_setting("rerank", "on" if _rerank else "off")
            elif parts[1] in ("on", "true", "1"):
                _rerank = True
                print_setting(
                    "rerank",
                    "on (cross-encoder; first query downloads ~80MB model)",
                )
            elif parts[1] in ("off", "false", "0"):
                _rerank = False
                print_setting("rerank", "off")
            else:
                print_error("usage: .rerank on/off")
        case ".fast":
            if len(parts) < 2:
                print_setting("fast", "on" if _fast else "off")
            elif parts[1] in ("on", "true", "1"):
                _fast = True
                print_setting(
                    "fast",
                    "on (ColPali visual tier; first query loads ~500MB model)",
                )
            elif parts[1] in ("off", "false", "0"):
                _fast = False
                print_setting("fast", "off")
            else:
                print_error("usage: .fast on/off")
        case ".clear":
            console.clear()
        case ".suggest":
            import asyncio

            from magpie_cli.suggestions import force_regenerate, load_suggestions

            if len(parts) > 1 and parts[1] in ("refresh", "new", "regen"):
                with console.status("[bold blue]  ◦ Regenerating suggestions...", spinner="dots"):
                    qs = asyncio.run(force_regenerate())
                if not qs:
                    print_error("could not generate suggestions (empty library or LLM failure)")
                    return True
            else:
                qs = load_suggestions()
                if not qs:
                    print_error(
                        "no suggestions cached yet — run `ns --sync` first, "
                        "or `.suggest refresh` to force-generate now"
                    )
                    return True
            print_suggestions(qs)
        case _:
            print_error(f"unknown command: {parts[0]}  (type .help)")
    return True


def _step(label: str, t0: float) -> None:
    """Print a completed step with elapsed time."""
    elapsed = time.monotonic() - t0
    console.print(f"  [green]✓[/green] {label} [dim]({elapsed:.1f}s)[/dim]")


def _detail(key: str, value: str) -> None:
    """Print an indented detail line."""
    console.print(f"    [dim]{key}:[/dim] {value}")


async def _run_query_async(question: str) -> None:
    """Async body of _run_query. All LLM calls happen in one event loop so
    httpx client cleanup never sees a closed loop."""
    import asyncio

    from src.answer import Answer, answer_question, build_answer_agent
    from src.pipeline import PipelineResult
    from src.stage2.search import (
        SearchQuery,
        raw_query,
        rewrite_query_async,
        run_search,
    )

    t_total = time.monotonic()
    console.print()

    # Step 1: Query construction
    if _rewrite:
        t0 = time.monotonic()
        history_arg = _history if _history_enabled and _history else None
        with console.status("[bold blue]  ◦ Rewriting query via Kimi...", spinner="dots"):
            sq: SearchQuery = await rewrite_query_async(question, history=history_arg)
        _step("Query rewritten", t0)
        _detail("dense query", sq.query)
        _detail("keywords", ", ".join(sq.keywords) if sq.keywords else "(none)")
        if history_arg:
            _detail("history", f"{len(history_arg)} prior turn(s) sent")
    else:
        sq = raw_query(question)
        console.print("  [green]✓[/green] Using raw query [dim](rewrite off)[/dim]")
        _detail("query", sq.query[:80])

    # Step 2: Embed query
    t0 = time.monotonic()
    with console.status("[bold blue]  ◦ Embedding query (MiniLM + BM25)...", spinner="dots"):
        from src.stage2.embeddings import embed_dense_query, embed_sparse_query
        dense_text = sq.query + " " + " ".join(sq.keywords)
        dense_vec = await asyncio.to_thread(embed_dense_query, dense_text)
        sparse_idx, sparse_val = await asyncio.to_thread(embed_sparse_query, dense_text)
    _step("Query embedded", t0)
    _detail("dense vector", f"{len(dense_vec)} dims")
    _detail("sparse terms", f"{len(sparse_idx)} active terms")

    # Step 3: Qdrant search. Passing the raw question lets the adaptive
    # classifier widen top_k for enumeration queries (see B1 in backlog).
    # If `.rerank on`, fan out to top_k*10 candidates and rerank with a
    # cross-encoder (see B4).
    t0 = time.monotonic()
    if _rerank:
        search_label = "Searching Qdrant + cross-encoder rerank"
    elif _fast:
        search_label = "Searching Qdrant (text + ColPali visual)"
    else:
        search_label = "Searching Qdrant (text only — fast)"
    with console.status(f"[bold blue]  ◦ {search_label}...", spinner="dots"):
        retrieved = await asyncio.to_thread(
            run_search,
            sq,
            _top_k,
            question=question,
            rerank=_rerank,
            skip_fast=not _fast,
        )
    _step("Qdrant searched", t0)
    tier_counts: dict[str, int] = {}
    for r in retrieved:
        tier_counts[r.tier] = tier_counts.get(r.tier, 0) + 1
    tier_breakdown = ", ".join(f"{v} {k}" for k, v in sorted(tier_counts.items()))
    _detail("results", f"{len(retrieved)} documents ({tier_breakdown})")
    tier_color = {"summary": "green", "fast": "magenta", "both": "cyan"}
    for i, r in enumerate(retrieved[:3], 1):
        color = tier_color.get(r.tier, "white")
        _detail(
            f"  #{i}",
            f"[{r.score:.3f}] [bold {color}]{r.tier}[/bold {color}] {file_link(r.path)}",
        )
    if len(retrieved) > 3:
        _detail("", f"...and {len(retrieved) - 3} more")

    if not retrieved:
        console.print("\n[yellow]No matching documents found.[/yellow]\n")
        return

    # Step 4: Read source documents + generate answer
    paths = list(dict.fromkeys(r.path for r in retrieved if r.path))
    answer_history = _history if _history_enabled and _history else None
    t0 = time.monotonic()
    with console.status("[bold blue]  ◦ Reading source files and asking Kimi...", spinner="dots"):
        agent = build_answer_agent()
        ans: Answer = await answer_question(agent, question, paths, history=answer_history, search_query=sq)
    _step("Answer generated", t0)
    _detail("sources cited", f"{len(ans.sources_used)} files")
    if answer_history:
        _detail("history", f"{len(answer_history)} prior turn(s) sent to answerer")
    for p in ans.sources_used:
        _detail("", f"[cyan]→[/cyan] {file_link(p)}")

    # Total time
    elapsed = time.monotonic() - t_total
    console.print(f"\n  [bold]Total: {elapsed:.1f}s[/bold]\n")

    result = PipelineResult(
        question=question,
        search_query=sq,
        retrieved=retrieved,
        answer=ans.answer,
        sources_used=ans.sources_used,
    )
    print_result(result)

    # Record this turn for future history-aware rewrites.
    _history.append((question, ans.answer))


def _run_query(question: str) -> None:
    """Sync entry point. Runs the full query in a single event loop so
    httpx client cleanup fires while the loop is still alive."""
    import asyncio
    try:
        asyncio.run(_run_query_async(question))
    except Exception as e:
        print_error(str(e))


def _cmd_sync(
    source_dir: str | None,
    concurrency: int,
    do_fast: bool = True,
    do_summary: bool = True,
    force_ingest: bool = False,
) -> int:
    """Run the two-tier sync: fast tier (ColPali) + summary tier (LLM)."""
    from src.llm import active_model_name, active_provider
    from src.pipeline import DEFAULT_SOURCE_DIR, sync_files_sync

    target = source_dir or DEFAULT_SOURCE_DIR
    tiers = []
    if do_fast:
        tiers.append("fast")
    if do_summary:
        tiers.append("summary")
    tiers_label = " + ".join(tiers) if tiers else "(nothing)"

    console.print(
        f"\n[bold blue]Syncing[/bold blue] [dim]{target}[/dim] "
        f"[dim](tiers: {tiers_label}, concurrency={concurrency})[/dim]"
    )
    if do_summary:
        console.print(
            f"[dim]Summary model:[/dim] [cyan]{active_model_name()}[/cyan] "
            f"[dim](via {active_provider().name})[/dim]"
        )
    if do_fast:
        try:
            from src.stage1_fast.device import detect_device
            cfg = detect_device()
            console.print(
                f"[dim]Fast tier:[/dim] [cyan]{cfg.model_id}[/cyan] "
                f"[dim](on {cfg.device}, {cfg.dtype})[/dim]"
            )
        except Exception as e:  # pylint: disable=broad-except
            console.print(f"[yellow]fast-tier model unavailable: {e}[/yellow]")
            do_fast = False
    console.print()

    try:
        t0 = time.monotonic()
        sync_files_sync(
            source_dir,
            concurrency=concurrency,
            do_fast=do_fast,
            do_summary=do_summary,
            force_ingest=force_ingest,
        )
        elapsed = time.monotonic() - t0
        console.print(f"\n[green]✓ Sync complete[/green] [dim]({elapsed:.1f}s)[/dim]\n")
    except Exception as e:
        print_error(f"sync failed: {type(e).__name__}: {e}")
        return 1

    # Best-effort: refresh REPL question hints if the library changed.
    import asyncio

    from magpie_cli.suggestions import regenerate_if_stale
    from src.manifest import Manifest

    try:
        with console.status("[bold blue]Refreshing question hints...", spinner="dots"):
            asyncio.run(regenerate_if_stale(len(Manifest().entries)))
    except Exception as e:
        console.print(f"[yellow]suggestion refresh skipped: {type(e).__name__}: {e}[/yellow]")
    return 0


def _cmd_reset(assume_yes: bool) -> int:
    """Wipe all summaries, the manifest, and the Qdrant collection."""
    from src.pipeline import reset

    console.print(
        "\n[yellow bold]This will delete:[/yellow bold]\n"
        "  • every file in Test Summaries/\n"
        "  • Test Summaries/_manifest.json\n"
        "  • the 'summaries' Qdrant collection\n"
    )
    if not assume_yes:
        try:
            confirm = input("Type 'yes' to continue: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Aborted.[/dim]")
            return 1
        if confirm != "yes":
            console.print("[dim]Aborted.[/dim]")
            return 1

    try:
        stats = reset()
    except Exception as e:
        print_error(f"reset failed: {type(e).__name__}: {e}")
        return 1

    console.print(
        f"\n[green]✓ Reset complete[/green]\n"
        f"  [dim]summaries deleted:[/dim] {stats['summaries_deleted']}\n"
        f"  [dim]manifest removed:[/dim] {stats['manifest_removed']}\n"
        f"  [dim]Qdrant collection dropped:[/dim] {stats['collection_dropped']}"
    )
    if stats.get("qdrant_error"):
        console.print(f"  [yellow]qdrant warning:[/yellow] {stats['qdrant_error']}")
    console.print()
    return 0


def _run_repl() -> None:
    print_banner()

    # Background-prewarm everything the first query is likely to need.
    # The user reads the banner and types — call it ~3 sec of natural
    # latency we can hide work behind. We load:
    #
    #   - FastEmbed dense + sparse encoders   (~1-2 sec total, always needed)
    #   - Qdrant client + TLS handshake       (~100-300 ms, always needed)
    #   - Kimi answer agent                   (~100 ms module setup)
    #   - Kimi rewrite agent  (only if `_rewrite` is on at startup)
    #   - Cross-encoder       (only if `_rerank` is on at startup; ~3 sec)
    #
    # Each step is independent and skipped on failure — the actual code
    # paths revalidate when called, so a failed prewarm just means the
    # query takes a hair longer.
    import threading

    def _prewarm() -> None:
        # Catch SystemExit too — get_qdrant_client() calls sys.exit() if env
        # is missing, and BaseException is the only superclass that covers
        # both Exception and SystemExit. The prewarm is best-effort; we
        # never want a failure here to crash anything visible.
        try:
            from src.stage2.embeddings import get_dense_model, get_sparse_model
            get_dense_model()
            get_sparse_model()
        except BaseException:  # pylint: disable=broad-except
            pass
        try:
            from src.stage2.db import get_qdrant_client
            client = get_qdrant_client()
            try:
                client.get_collections()  # force TLS/auth round-trip now
            except BaseException:  # pylint: disable=broad-except
                pass
        except BaseException:  # pylint: disable=broad-except
            pass
        try:
            from src.answer import build_answer_agent
            build_answer_agent()
        except BaseException:  # pylint: disable=broad-except
            pass

        # Opt-in components. Only prewarm if the user already has them
        # toggled on at startup — otherwise they pay no startup cost.
        if _rewrite:
            try:
                from src.stage2.search import _build_rewrite_agent
                _build_rewrite_agent()
            except BaseException:  # pylint: disable=broad-except
                pass
        if _rerank:
            try:
                from src.stage2.rerank import _load_model
                _load_model()  # ~3 sec — worth hiding behind typing
            except BaseException:  # pylint: disable=broad-except
                pass

    threading.Thread(target=_prewarm, daemon=True).start()

    session: PromptSession = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        completer=DotCommandCompleter(),
        complete_while_typing=True,
    )

    while True:
        try:
            text = session.prompt("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not text:
            continue

        if text.lower() in ("exit", "quit"):
            console.print("[dim]Goodbye.[/dim]")
            break

        if _handle_dot_command(text):
            continue

        _run_query(text)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="ns",
        description="Magpie — interactive RAG search over your local files.",
    )
    parser.add_argument(
        "--sync",
        nargs="?",
        const="",
        metavar="DIR",
        help=(
            "Summarize + ingest new/changed files (and prune deleted ones). "
            "Optional DIR overrides the default (Test Content/). Exits when done."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Parallel LLM calls during --sync (default: 1). "
            "Raise for cloud providers with ample rate limits; keep at 1 for "
            "LLM_PROVIDER=local (single-GPU inference) or rate-limited cloud tiers."
        ),
    )
    parser.add_argument(
        "--fast-only",
        action="store_true",
        help=(
            "During --sync, run ONLY the ColPali fast tier (no LLM summaries). "
            "Best for instant onboarding; no API cost."
        ),
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help=(
            "During --sync, run ONLY the LLM summary tier (skip ColPali). "
            "Use when no GPU is available or for debugging the legacy path."
        ),
    )
    parser.add_argument(
        "--reingest",
        action="store_true",
        help=(
            "Force re-push of all summaries to Qdrant. Use after switching "
            "Qdrant clusters, changing credentials, or if the collection was "
            "dropped. Clears all `ingested_at` markers in the manifest and "
            "recreates the `summaries` collection from scratch."
        ),
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all summaries, the manifest, and the Qdrant collection. Prompts to confirm.",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip the confirmation prompt on --reset.",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help=(
            "Start the REPL with conversation history enabled. Prior Q&A turns "
            "are sent to the query rewriter so follow-up questions can resolve "
            "references like 'its prerequisites'. Requires rewrite mode to take "
            "effect (toggle with .rewrite on)."
        ),
    )
    parser.add_argument(
        "--rewrite",
        action="store_true",
        help="Start the REPL with Kimi query rewriting enabled.",
    )
    args = parser.parse_args()

    if args.reset:
        sys.exit(_cmd_reset(assume_yes=args.yes))

    if args.sync is not None:
        if args.fast_only and args.summary_only:
            print_error("--fast-only and --summary-only are mutually exclusive")
            sys.exit(2)
        # argparse gives us "" when --sync was passed with no argument.
        sys.exit(_cmd_sync(
            source_dir=args.sync or None,
            concurrency=args.concurrency,
            do_fast=not args.summary_only,
            do_summary=not args.fast_only,
            force_ingest=args.reingest,
        ))

    global _history_enabled, _rewrite
    if args.history:
        _history_enabled = True
    if args.rewrite:
        _rewrite = True

    _run_repl()


if __name__ == "__main__":
    main()
