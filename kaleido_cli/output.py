"""Rich output helpers — tables, panels, JSON mode."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

console = Console()
err_console = Console(stderr=True)

# Module-level flag; toggled by the global --json option
_json_mode: bool = False


def set_json_mode(enabled: bool) -> None:
    global _json_mode
    _json_mode = enabled


def is_json_mode() -> bool:
    return _json_mode


# ---------------------------------------------------------------------------
# Raw output helpers
# ---------------------------------------------------------------------------


def print_json(data: Any) -> None:
    """Pretty-print any value as JSON."""
    if isinstance(data, (dict, list)):
        console.print_json(json.dumps(data))
    else:
        console.print_json(json.dumps(data, default=str))


def print_success(msg: str) -> None:
    console.print(f"[green]✓[/green] {msg}")


def print_error(msg: str) -> None:
    err_console.print(f"[red]✗[/red] {msg}")


def print_info(msg: str) -> None:
    console.print(f"[cyan]ℹ[/cyan] {msg}")


def print_warning(msg: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {msg}")


def print_panel(title: str, content: str, style: str = "blue") -> None:
    console.print(Panel(content, title=title, border_style=style))


# ---------------------------------------------------------------------------
# Table builder
# ---------------------------------------------------------------------------


def print_table(
    title: str,
    columns: list[str],
    rows: list[list[Any]],
    *,
    empty_msg: str = "No results.",
) -> None:
    if not rows:
        print_info(f"{title}: {empty_msg}")
        return

    table = Table(title=title, show_header=True, header_style="bold cyan")
    for col in columns:
        table.add_column(col, overflow="fold")
    for row in rows:
        table.add_row(*[str(v) if v is not None else "-" for v in row])
    console.print(table)


# ---------------------------------------------------------------------------
# Convenience: output a Pydantic model (JSON or table-friendly dict)
# ---------------------------------------------------------------------------


def output_model(data: Any, title: str | None = None) -> None:
    """Output a Pydantic model either as JSON or as a key/value panel."""
    if hasattr(data, "model_dump"):
        d = data.model_dump()
    elif hasattr(data, "__dict__"):
        d = vars(data)
    else:
        d = data

    if _json_mode:
        print_json(d)
        return

    lines = _flatten_dict(d)
    content = "\n".join(f"[bold]{k}[/bold]: {v}" for k, v in lines)
    console.print(Panel(content, title=title or "", border_style="blue"))


def _flatten_dict(d: dict, prefix: str = "") -> list[tuple[str, Any]]:
    result = []
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.extend(_flatten_dict(v, key))
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            for i, item in enumerate(v):
                result.extend(_flatten_dict(item, f"{key}[{i}]"))
        else:
            result.append((key, v))
    return result
