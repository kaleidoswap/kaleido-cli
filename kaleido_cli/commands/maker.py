"""Maker/Taker node-level swap operations — pubkey, whitelist, maker-init, maker-execute."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk.rln import (
    MakerExecuteRequest,
    MakerInitRequest,
    MakerInitResponse,
)

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_interactive,
    is_json_mode,
    output_model,
    print_error,
    print_json,
    print_success,
)

maker_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Maker-side swap operations — initialise and execute HTLC-based atomic swaps.",
)


@maker_app.command(
    "init",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Offer to send 30 USDT and receive 10 EURS:\n"
        "  [cyan]kaleido maker init --qty-from 30 --from-asset rgb:abc... --qty-to 10 --to-asset rgb:def...[/cyan]\n\n"
        "  BTC → RGB (maker sends BTC, receives an RGB asset):\n"
        "  [cyan]kaleido maker init --qty-from 100000 --qty-to 50 --to-asset rgb:abc...[/cyan]"
    ),
)
def maker_init(
    qty_from: Annotated[
        int | None,
        typer.Option("--qty-from", help="Amount the maker will send (raw units)."),
    ] = None,
    qty_to: Annotated[
        int | None,
        typer.Option("--qty-to", help="Amount the maker will receive (raw units)."),
    ] = None,
    from_asset: Annotated[
        str | None,
        typer.Option("--from-asset", help="RGB asset ID to send. Omit for BTC."),
    ] = None,
    to_asset: Annotated[
        str | None,
        typer.Option("--to-asset", help="RGB asset ID to receive. Omit for BTC."),
    ] = None,
    timeout_sec: Annotated[
        int,
        typer.Option("--timeout", help="Swap offer timeout in seconds."),
    ] = 100,
) -> None:
    """Initialize a maker swap offer and print the swapstring."""
    if qty_from is None:
        if is_interactive():
            qty_from = typer.prompt("Quantity from (raw units)", type=int)
        else:
            print_error("--qty-from is required in non-interactive mode.")
            raise typer.Exit(1)
    if qty_to is None:
        if is_interactive():
            qty_to = typer.prompt("Quantity to (raw units)", type=int)
        else:
            print_error("--qty-to is required in non-interactive mode.")
            raise typer.Exit(1)

    asyncio.run(_maker_init(qty_from, qty_to, from_asset, to_asset, timeout_sec))


async def _maker_init(
    qty_from: int,
    qty_to: int,
    from_asset: str | None,
    to_asset: str | None,
    timeout_sec: int,
) -> None:
    try:
        client = get_client(require_node=True)
        resp: MakerInitResponse = await client.rln.maker_init(
            MakerInitRequest(
                qty_from=qty_from,
                qty_to=qty_to,
                from_asset=from_asset,
                to_asset=to_asset,
                timeout_sec=timeout_sec,
            )
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title="Maker Init")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@maker_app.command(
    "execute",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Execute a maker swap (after taker has whitelisted):\n"
        "  [cyan]kaleido maker execute --swapstring '30/rgb:...' --payment-secret abc123 --taker-pubkey 03...[/cyan]"
    ),
)
def maker_execute(
    swapstring: Annotated[
        str | None,
        typer.Option("--swapstring", help="Swap string from maker-init."),
    ] = None,
    payment_secret: Annotated[
        str | None,
        typer.Option("--payment-secret", help="Payment secret from maker-init."),
    ] = None,
    taker_pubkey: Annotated[
        str | None,
        typer.Option("--taker-pubkey", help="Public key of the taker node."),
    ] = None,
) -> None:
    """Execute a maker swap (finalise the HTLC after taker acceptance)."""
    if swapstring is None:
        if is_interactive():
            swapstring = typer.prompt("Swapstring")
        else:
            print_error("--swapstring is required in non-interactive mode.")
            raise typer.Exit(1)
    if payment_secret is None:
        if is_interactive():
            payment_secret = typer.prompt("Payment secret")
        else:
            print_error("--payment-secret is required in non-interactive mode.")
            raise typer.Exit(1)
    if taker_pubkey is None:
        if is_interactive():
            taker_pubkey = typer.prompt("Taker pubkey")
        else:
            print_error("--taker-pubkey is required in non-interactive mode.")
            raise typer.Exit(1)

    asyncio.run(_maker_execute(swapstring, payment_secret, taker_pubkey))


async def _maker_execute(swapstring: str, payment_secret: str, taker_pubkey: str) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.maker_execute(
            MakerExecuteRequest(
                swapstring=swapstring,
                payment_secret=payment_secret,
                taker_pubkey=taker_pubkey,
            )
        )
        print_success("Maker execute completed successfully.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
