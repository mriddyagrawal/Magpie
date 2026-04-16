"""Interactive REPL for NotAnotherSpotlight."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# The workspace root has `package = false` (it isn't packaged, it's just a
# workspace root), so the `src/*` modules aren't reachable via the normal
# dependency path when `ns` runs as an installed console script. Prepend the
# repo root to sys.path so `from src.pipeline import ...` works. `__file__`
# resolves to cli/notspotlight/repl.py under uv's editable workspace install,
# so parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console

from notspotlight.display import (
    console,
    file_link,
    print_banner,
    print_error,
    print_help,
    print_result,
    print_setting,
)

HISTORY_FILE = Path.home() / ".notspotlight_history"

# Session state
_rewrite = False
_top_k = 5
_history_enabled = False
_history: list[tuple[str, str]] = []  # (question, answer) pairs from this session


def _handle_dot_command(cmd: str) -> bool:
    """Handle dot-commands. Returns True if the input was a command."""
    global _rewrite, _top_k, _history_enabled, _history

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
        case ".clear":
            console.clear()
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

    # Step 3: Qdrant search
    t0 = time.monotonic()
    with console.status("[bold blue]  ◦ Searching Qdrant (dense + BM25 hybrid)...", spinner="dots"):
        retrieved = await asyncio.to_thread(run_search, sq, _top_k)
    _step("Qdrant searched", t0)
    _detail("results", f"{len(retrieved)} documents")
    for i, r in enumerate(retrieved[:3], 1):
        _detail(f"  #{i}", f"[{r.score:.3f}] {file_link(r.path)}")
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
        ans: Answer = await answer_question(agent, question, paths, history=answer_history)
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


def _cmd_sync(source_dir: str | None, concurrency: int) -> int:
    """Summarize new/changed files and ingest them into Qdrant."""
    from src.llm import active_model_name, active_provider
    from src.pipeline import DEFAULT_SOURCE_DIR, sync_files_sync

    target = source_dir or DEFAULT_SOURCE_DIR
    console.print(
        f"\n[bold blue]Syncing[/bold blue] [dim]{target}[/dim] "
        f"[dim](concurrency={concurrency})[/dim] "
        f"[dim]using[/dim] [cyan]{active_model_name()}[/cyan] "
        f"[dim](via {active_provider().name})[/dim]\n"
    )
    try:
        t0 = time.monotonic()
        sync_files_sync(source_dir, concurrency=concurrency)
        elapsed = time.monotonic() - t0
        console.print(f"\n[green]✓ Sync complete[/green] [dim]({elapsed:.1f}s)[/dim]\n")
        return 0
    except Exception as e:
        print_error(f"sync failed: {type(e).__name__}: {e}")
        return 1


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

    session: PromptSession = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
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
        description="NotAnotherSpotlight — interactive RAG search over your local files.",
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
        default=6,
        metavar="N",
        help=(
            "Parallel LLM calls during --sync (default: 6). "
            "Drop to 1 or 2 for rate-limited providers (e.g. Gemma free tier on OpenRouter)."
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
        # argparse gives us "" when --sync was passed with no argument.
        sys.exit(_cmd_sync(source_dir=args.sync or None, concurrency=args.concurrency))

    global _history_enabled, _rewrite
    if args.history:
        _history_enabled = True
    if args.rewrite:
        _rewrite = True

    _run_repl()


if __name__ == "__main__":
    main()
