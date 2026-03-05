"""CLI configuration management commands."""

from __future__ import annotations

from typing import Annotated

import typer

from ..config import (
    CONFIG_FILE,
    CliConfig,
    load_config,
    save_config,
    set_config_key,
    _KEY_ALIASES,
)
from ..output import (
    is_json_mode,
    print_error,
    print_info,
    print_json,
    print_success,
    print_table,
)

config_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help=(
        "Manage CLI configuration stored in [green]~/.kaleido/config.json[/green].\n\n"
        "[bold]Config keys[/bold]\n\n"
        "  [green]node-url[/green]   URL of your RGB Lightning Node  (default: http://localhost:3001)\n"
        "  [green]api-url[/green]    Kaleidoswap maker API URL       (default: https://api.kaleidoswap.com)\n"
        "  [green]network[/green]    Bitcoin network                 (default: signet)\n"
        "  [green]spawn-dir[/green]  Directory for spawned nodes     (default: ~/.kaleido/spawn)\n"
    ),
)


@config_app.command("show")
def config_show() -> None:
    """Display current CLI configuration."""
    config = load_config()
    if is_json_mode():
        print_json(config.to_dict())
        return
    rows = [
        ["api-url", config.api_url],
        ["node-url", config.node_url],
        ["network", config.network],
        ["spawn-dir", config.spawn_dir or "(default: ~/.kaleido/spawn)"],
    ]
    print_table(f"Config ({CONFIG_FILE})", ["Key", "Value"], rows)


@config_app.command(
    "set",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  [cyan]kaleido config set node-url http://localhost:3001[/cyan]\n"
        "  [cyan]kaleido config set api-url https://api.kaleidoswap.com[/cyan]\n"
        "  [cyan]kaleido config set network regtest[/cyan]\n"
        "  [cyan]kaleido config set spawn-dir ~/kaleido-nodes[/cyan]"
    ),
)
def config_set(
    key: Annotated[
        str,
        typer.Argument(help=f"Config key to update. Valid keys: {list(_KEY_ALIASES)}"),
    ],
    value: Annotated[str, typer.Argument(help="New value to set.")],
) -> None:
    """Set a configuration value."""
    try:
        set_config_key(key, value)
        print_success(f"Set {key} = {value}")
    except KeyError as e:
        print_error(str(e))
        raise typer.Exit(1)


@config_app.command(
    "reset",
    epilog=(
        "  [cyan]kaleido config reset[/cyan]        Interactive confirmation\n"
        "  [cyan]kaleido config reset --yes[/cyan]   Skip confirmation"
    ),
)
def config_reset(
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")
    ] = False,
) -> None:
    """Reset all configuration to defaults."""
    if not yes:
        confirmed = typer.confirm("Reset all config to defaults?")
        if not confirmed:
            print_info("Aborted.")
            raise typer.Exit(0)
    save_config(CliConfig())
    print_success("Config reset to defaults.")


@config_app.command(
    "path",
    epilog="  [cyan]kaleido config path[/cyan]   Print the path; useful for scripts: $(kaleido config path)",
)
def config_path() -> None:
    """Print the path to the config file."""
    print_info(str(CONFIG_FILE))
