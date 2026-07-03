"""Output formatting for the interactive CLI using rich."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from src.pipeline import PipelineResult

console = Console()

_REPO_ROOT = Path(__file__).resolve().parents[2]


def file_link(rel_path: str) -> str:
    """Format a repo-relative path as a clickable rich link (file:// URL).

    The answer LLM may append a page-citation suffix to a path (per the
    `sources_used` format rule in src/answer.py:SYSTEM_PROMPT), e.g.:

        /path/to/textbook.pdf  [book pp. 254-258 / PDF pp. 269-273]

    The bracketed suffix MUST be rendered outside the rich [link] tag —
    otherwise Rich tries to parse the inner `[book pp...]` as nested
    markup, which raises MarkupError and crashes the answer display.
    Suffix is shown as dim text following the clickable link, both
    visually distinguished from the path and safely outside markup.
    """
    if not rel_path:
        return rel_path

    import re
    from rich.markup import escape

    # Split the path from any trailing `[...]` page-citation suffix.
    m = re.search(r"\s*(\[[^\]]*\])\s*$", rel_path)
    if m:
        suffix = m.group(1)
        bare = rel_path[: m.start()].rstrip()
    else:
        suffix = ""
        bare = rel_path

    abs_path = (_REPO_ROOT / bare).resolve()
    link = f"[link=file://{abs_path}]{escape(bare)}[/link]"
    if suffix:
        return f"{link} [dim]{escape(suffix)}[/dim]"
    return link


FALLBACK_SUGGESTIONS = [
    "How much was the flight to Hartford?",
    "What is Plato's education system for philosopher rulers?",
    "How much did the DS/ML club spend on hackathons?",
    "What events did the club organize in Fall 2024?",
    "Who traveled on the Breeze Airways flight?",
]


def _fast_tier_line() -> str:
    """Best-effort detection of the fast-tier model + device for the banner.

    Runs at REPL start, so we shield against torch import failures (e.g.
    torch not yet installed in a mid-setup state) and just omit the line.
    """
    try:
        from src.stage1_fast.device import detect_device
        cfg = detect_device()
        return (
            f"[dim]Fast tier:[/dim] [cyan]{cfg.model_id}[/cyan] "
            f"[dim]on {cfg.device} ({cfg.dtype}, batch {cfg.batch_size})[/dim]"
        )
    except Exception:  # pylint: disable=broad-except
        return "[dim]Fast tier:[/dim] [yellow](not available)[/yellow]"


def print_banner() -> None:
    from src.llm import active_model_name, active_provider

    from notspotlight.suggestions import load_suggestions

    qs = load_suggestions() or FALLBACK_SUGGESTIONS
    suggestions = "\n".join(f"  [dim italic]{s}[/dim italic]" for s in qs)
    provider = active_provider().name
    model = active_model_name()
    console.print(
        Panel(
            "[bold]NotAnotherSpotlight[/bold]  v0.1.0\n"
            f"[dim]Answer model:[/dim] [cyan]{model}[/cyan] [dim](via {provider})[/dim]\n"
            f"{_fast_tier_line()}\n"
            "Type your question and press Enter. Type [bold].help[/bold] for commands.\n\n"
            "[bold]Try asking:[/bold]\n"
            f"{suggestions}",
            border_style="blue",
        )
    )


def print_suggestions(questions: list[str]) -> None:
    """Render a fresh list of question hints (used by the .suggest command)."""
    body = "\n".join(f"  [dim italic]{q}[/dim italic]" for q in questions)
    console.print(
        Panel(
            f"[bold]Try asking:[/bold]\n{body}",
            border_style="blue",
        )
    )


def print_help() -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row(".help", "Show this help")
    table.add_row(".rewrite on/off", "Toggle Kimi query rewriting (default: off)")
    table.add_row(".fast on/off", "Toggle ColPali visual tier (default: off — saves ~30s startup)")
    table.add_row(".history on/off/clear", "Send prior Q&A to the rewriter (needs .rewrite on)")
    table.add_row(".top-k N", "Set number of results to retrieve")
    table.add_row(".suggest [refresh]", "Show question hints (add 'refresh' to regenerate)")
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
        table.add_column("Tier", width=8)
        table.add_column("Path")
        tier_color = {"summary": "green", "fast": "magenta", "both": "cyan"}
        for i, r in enumerate(result.retrieved, 1):
            color = tier_color.get(r.tier, "white")
            table.add_row(
                str(i),
                f"{r.score:.3f}",
                f"[{color}]{r.tier}[/{color}]",
                file_link(r.path),
            )
        console.print(table)
        console.print()

    # Answer
    console.print(Panel(Markdown(result.answer), title="Answer", border_style="green"))

    # Sources used
    if result.sources_used:
        console.print("[bold]Sources used:[/bold]")
        for p in result.sources_used:
            console.print(f"  [cyan]→[/cyan] {file_link(p)}")
    else:
        console.print("[dim]Sources used: (none)[/dim]")
    console.print()


def print_error(msg: str) -> None:
    """Print an error line to the console.

    Escapes Rich markup characters in `msg` so error messages that contain
    `[...]` brackets (paths with page suffixes, regex output, JSON snippets,
    even prior MarkupErrors) don't trigger a second markup parse failure
    inside the error path.
    """
    from rich.markup import escape
    console.print(f"[red bold]Error:[/red bold] {escape(msg)}")


def print_setting(key: str, value: str) -> None:
    console.print(f"[dim]{key}:[/dim] [bold]{value}[/bold]")
