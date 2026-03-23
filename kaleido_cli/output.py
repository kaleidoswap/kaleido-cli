"""Rich output helpers — tables, panels, JSON mode."""

from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel

console = Console()
err_console = Console(stderr=True)

# Module-level flags; toggled by global --json / --agent options
_json_mode: bool = False
_agent_mode: bool = False


def set_json_mode(enabled: bool) -> None:
    global _json_mode
    _json_mode = enabled


def set_agent_mode(enabled: bool) -> None:
    global _agent_mode
    _agent_mode = enabled


def is_json_mode() -> bool:
    return _json_mode


def is_interactive() -> bool:
    """True when running in a human terminal (stdin+stdout are TTYs, not JSON/agent mode)."""
    return sys.stdin.isatty() and sys.stdout.isatty() and not _json_mode and not _agent_mode


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


def output_collection(
    title: str,
    items: list[Any],
    *,
    item_title: str | None = None,
    empty_msg: str = "No results.",
) -> None:
    """Output a list of items as individual panels."""
    if not items:
        print_info(f"{title}: {empty_msg}")
        return

    for index, item in enumerate(items, start=1):
        resolved_title = item_title.format(index=index) if item_title else f"{title} — {index}"
        output_model(item, title=resolved_title)


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
