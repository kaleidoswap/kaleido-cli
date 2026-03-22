"""Taker-side swap operations — pubkey retrieval and swap whitelisting."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk.rln import TakerRequest

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_interactive,
    is_json_mode,
    print_error,
    print_json,
    print_success,
)

taker_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Taker-side swap operations — identity and swap acceptance.",
)


@taker_app.command(
    "pubkey",
    epilog="  [cyan]kaleido taker pubkey[/cyan]   Print the node's taker public key.",
)
def taker_pubkey() -> None:
    """Show the node's taker public key (used in swap operations)."""
    asyncio.run(_taker_pubkey())


async def _taker_pubkey() -> None:
    try:
        client = get_client(require_node=True)
        pubkey = await client.rln.get_taker_pubkey()
        if is_json_mode():
            print_json({"pubkey": pubkey})
        else:
            print_success(f"Taker pubkey: {pubkey}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@taker_app.command(
    "whitelist",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Accept a swap offer from a maker:\n"
        "  [cyan]kaleido taker whitelist '30/rgb:abc.../10/rgb:def.../...'[/cyan]"
    ),
)
def taker_whitelist(
    swapstring: Annotated[
        str | None,
        typer.Argument(help="Swap string to accept on the taker side."),
    ] = None,
) -> None:
    """Whitelist (accept) a swap string from a maker on the taker side."""
    resolved: str
    if swapstring is not None:
        resolved = swapstring
    elif is_interactive():
        resolved = typer.prompt("Swapstring")
    else:
        print_error("SWAPSTRING argument is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(_taker_whitelist(resolved))


async def _taker_whitelist(swapstring: str) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.whitelist_swap(TakerRequest(swapstring=swapstring))
        print_success("Swap whitelisted — taker accepted this offer.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
