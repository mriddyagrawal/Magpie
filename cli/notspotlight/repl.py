"""Interactive REPL for NotAnotherSpotlight."""

from __future__ import annotations

import sys
import time
from pathlib import Path

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


def main() -> None:
    load_dotenv()

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


if __name__ == "__main__":
    main()
