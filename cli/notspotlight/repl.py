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


def _handle_dot_command(cmd: str) -> bool:
    """Handle dot-commands. Returns True if the input was a command."""
    global _rewrite, _top_k

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


def _run_query(question: str) -> None:
    """Run the pipeline step-by-step with live internal tooling output."""
    from src.answer import Answer, answer_question_sync, build_answer_agent
    from src.pipeline import PipelineResult
    from src.stage2.search import SearchQuery, raw_query, rewrite_query, run_search

    try:
        t_total = time.monotonic()
        console.print()

        # Step 1: Query construction
        if _rewrite:
            t0 = time.monotonic()
            with console.status("[bold blue]  ◦ Rewriting query via Kimi...", spinner="dots"):
                sq: SearchQuery = rewrite_query(question)
            _step("Query rewritten", t0)
            _detail("dense query", sq.query)
            _detail("keywords", ", ".join(sq.keywords) if sq.keywords else "(none)")
        else:
            sq = raw_query(question)
            console.print("  [green]✓[/green] Using raw query [dim](rewrite off)[/dim]")
            _detail("query", sq.query[:80])

        # Step 2: Embed query
        t0 = time.monotonic()
        with console.status("[bold blue]  ◦ Embedding query (MiniLM + BM25)...", spinner="dots"):
            from src.stage2.embeddings import embed_dense_query, embed_sparse_query
            dense_text = sq.query + " " + " ".join(sq.keywords)
            dense_vec = embed_dense_query(dense_text)
            sparse_idx, sparse_val = embed_sparse_query(dense_text)
        _step("Query embedded", t0)
        _detail("dense vector", f"{len(dense_vec)} dims")
        _detail("sparse terms", f"{len(sparse_idx)} active terms")

        # Step 3: Qdrant search
        t0 = time.monotonic()
        with console.status("[bold blue]  ◦ Searching Qdrant (dense + BM25 hybrid)...", spinner="dots"):
            retrieved = run_search(sq, _top_k)
        _step("Qdrant searched", t0)
        _detail("results", f"{len(retrieved)} documents")
        for i, r in enumerate(retrieved[:3], 1):
            _detail(f"  #{i}", f"[{r.score:.3f}] {r.path}")
        if len(retrieved) > 3:
            _detail("", f"...and {len(retrieved) - 3} more")

        if not retrieved:
            console.print("\n[yellow]No matching documents found.[/yellow]\n")
            return

        # Step 4: Read source documents + generate answer
        paths = [r.path for r in retrieved if r.path]
        t0 = time.monotonic()
        with console.status("[bold blue]  ◦ Reading source files and asking Kimi...", spinner="dots"):
            agent = build_answer_agent()
            ans: Answer = answer_question_sync(agent, question, paths)
        _step("Answer generated", t0)
        _detail("sources cited", f"{len(ans.sources_used)} files")
        for p in ans.sources_used:
            _detail("", f"[cyan]→[/cyan] {p}")

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

    except Exception as e:
        print_error(str(e))


def _cmd_sync(source_dir: str | None) -> int:
    """Summarize new/changed files and ingest them into Qdrant."""
    from src.pipeline import DEFAULT_SOURCE_DIR, sync_files_sync

    target = source_dir or DEFAULT_SOURCE_DIR
    console.print(f"\n[bold blue]Syncing[/bold blue] [dim]{target}[/dim] ...\n")
    try:
        t0 = time.monotonic()
        sync_files_sync(source_dir)
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
        "--reset",
        action="store_true",
        help="Delete all summaries, the manifest, and the Qdrant collection. Prompts to confirm.",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip the confirmation prompt on --reset.",
    )
    args = parser.parse_args()

    if args.reset:
        sys.exit(_cmd_reset(assume_yes=args.yes))

    if args.sync is not None:
        # argparse gives us "" when --sync was passed with no argument.
        sys.exit(_cmd_sync(source_dir=args.sync or None))

    _run_repl()


if __name__ == "__main__":
    main()
