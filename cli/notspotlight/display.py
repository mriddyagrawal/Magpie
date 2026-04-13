"""Output formatting for the interactive CLI using rich."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from src.pipeline import PipelineResult

console = Console()


SUGGESTIONS = [
    "How much was the flight to Hartford?",
    "What is Plato's education system for philosopher rulers?",
    "How much did the DS/ML club spend on hackathons?",
    "What events did the club organize in Fall 2024?",
    "Who traveled on the Breeze Airways flight?",
]


def print_banner() -> None:
    suggestions = "\n".join(f"  [dim italic]{s}[/dim italic]" for s in SUGGESTIONS)
    console.print(
        Panel(
            "[bold]NotAnotherSpotlight[/bold]  v0.1.0\n"
            "Type your question and press Enter. Type [bold].help[/bold] for commands.\n\n"
            "[bold]Try asking:[/bold]\n"
            f"{suggestions}",
            border_style="blue",
        )
    )


def print_help() -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row(".help", "Show this help")
    table.add_row(".rewrite on/off", "Toggle Kimi query rewriting (default: off)")
    table.add_row(".top-k N", "Set number of results to retrieve")
    table.add_row(".clear", "Clear the screen")
    table.add_row("exit / quit / Ctrl+D", "Exit")
    console.print(table)


def print_result(result: PipelineResult) -> None:
    """Display a full pipeline result: retrieved docs, answer, sources."""
    # Retrieved documents
    if result.retrieved:
        table = Table(title="Retrieved Documents", border_style="dim")
        table.add_column("#", style="dim", width=3)
        table.add_column("Score", width=7)
        table.add_column("Path")
        for i, r in enumerate(result.retrieved, 1):
            table.add_row(str(i), f"{r.score:.3f}", r.path)
        console.print(table)
        console.print()

    # Answer
    console.print(Panel(Markdown(result.answer), title="Answer", border_style="green"))

    # Sources used
    if result.sources_used:
        console.print("[bold]Sources used:[/bold]")
        for p in result.sources_used:
            console.print(f"  [cyan]→[/cyan] {p}")
    else:
        console.print("[dim]Sources used: (none)[/dim]")
    console.print()


def print_error(msg: str) -> None:
    console.print(f"[red bold]Error:[/red bold] {msg}")


def print_setting(key: str, value: str) -> None:
    console.print(f"[dim]{key}:[/dim] [bold]{value}[/bold]")
