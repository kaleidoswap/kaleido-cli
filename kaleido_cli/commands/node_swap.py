"""Low-level local node swap commands."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk.rln import (
    GetSwapRequest,
    GetSwapResponse,
    ListSwapsResponse,
    MakerExecuteRequest,
    MakerInitRequest,
    MakerInitResponse,
    TakerRequest,
)

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_interactive,
    is_json_mode,
    output_collection,
    output_model,
    print_error,
    print_info,
    print_json,
    print_success,
)
from kaleido_cli.utils.prompts import resolve_required_text

node_swap_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Low-level local RLN node swap flow: maker-init, taker whitelist, then maker-execute.",
)


@node_swap_app.command(
    "pubkey",
    epilog="  [cyan]kaleido node swap pubkey[/cyan]   Print the local node's taker public key.",
)
def node_pubkey() -> None:
    """Show the local node's taker public key used in swap operations."""
    asyncio.run(_node_pubkey())


async def _node_pubkey() -> None:
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


@node_swap_app.command(
    "init",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Initialize a local node swap:\n"
        "  [cyan]kaleido node swap init --qty-from 30 --to-asset rgb:abc... --qty-to 10[/cyan]"
    ),
)
def node_init(
    from_asset: Annotated[
        str | None,
        typer.Option("--from-asset", help="RGB asset ID the maker will send (None = BTC)."),
    ] = None,
    qty_from: Annotated[
        int | None, typer.Option("--qty-from", help="Amount the maker will send (raw units).")
    ] = None,
    to_asset: Annotated[
        str | None,
        typer.Option("--to-asset", help="RGB asset ID the maker will receive (None = BTC)."),
    ] = None,
    qty_to: Annotated[
        int | None, typer.Option("--qty-to", help="Amount the maker will receive (raw units).")
    ] = None,
    timeout_sec: Annotated[
        int, typer.Option("--timeout", help="Swap offer timeout in seconds.")
    ] = 100,
) -> None:
    """Initialize a low-level local node swap via maker-init."""
    resolved_qty_from: int
    if qty_from is not None:
        resolved_qty_from = qty_from
    elif is_interactive():
        resolved_qty_from = typer.prompt("Quantity from (raw units)", type=int)
    else:
        print_error("--qty-from is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_qty_to: int
    if qty_to is not None:
        resolved_qty_to = qty_to
    elif is_interactive():
        resolved_qty_to = typer.prompt("Quantity to (raw units)", type=int)
    else:
        print_error("--qty-to is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(_node_init(from_asset, resolved_qty_from, to_asset, resolved_qty_to, timeout_sec))


async def _node_init(
    from_asset: str | None,
    qty_from: int,
    to_asset: str | None,
    qty_to: int,
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
            print_success("Node swap initialized")
            output_model(resp, title="Node Swap Init")
            print_info("Next step: whitelist on the taker side, then execute on the maker side.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@node_swap_app.command(
    "whitelist",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Whitelist a swap on the local taker node:\n"
        "  [cyan]kaleido node swap whitelist --swapstring '<swapstring>'[/cyan]"
    ),
)
def node_whitelist(
    swapstring: Annotated[
        str | None,
        typer.Option("--swapstring", help="Swap string returned by node init or atomic init."),
    ] = None,
) -> None:
    """Whitelist a swap on the local taker node via /taker."""
    resolved_swapstring = resolve_required_text(swapstring, "Swap string", "--swapstring")
    asyncio.run(_node_whitelist(resolved_swapstring))


async def _node_whitelist(swapstring: str) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.whitelist_swap(TakerRequest(swapstring=swapstring))
        if is_json_mode():
            print_json({"ok": True, "swapstring": swapstring})
        else:
            print_success("Swap whitelisted on taker node")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@node_swap_app.command(
    "execute",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Execute a previously initialized local node swap:\n"
        "  [cyan]kaleido node swap execute --swapstring '<swapstring>' "
        "--payment-secret deadbeef... --taker-pubkey 03ab...[/cyan]"
    ),
)
def node_execute(
    swapstring: Annotated[
        str | None, typer.Option("--swapstring", help="Swap string returned by node init.")
    ] = None,
    payment_secret: Annotated[
        str | None, typer.Option("--payment-secret", help="Payment secret returned by node init.")
    ] = None,
    taker_pubkey: Annotated[
        str | None,
        typer.Option("--taker-pubkey", help="Taker node pubkey. Defaults to own node pubkey."),
    ] = None,
) -> None:
    """Execute a low-level local node swap via maker-execute."""
    resolved_swapstring = resolve_required_text(swapstring, "Swap string", "--swapstring")
    resolved_payment_secret = resolve_required_text(
        payment_secret, "Payment secret", "--payment-secret"
    )
    asyncio.run(_node_execute(resolved_swapstring, resolved_payment_secret, taker_pubkey))


async def _node_execute(
    swapstring: str,
    payment_secret: str,
    taker_pubkey_override: str | None,
) -> None:
    try:
        client = get_client(require_node=True)
        resolved_taker_pubkey = taker_pubkey_override or await client.rln.get_taker_pubkey()
        await client.rln.maker_execute(
            MakerExecuteRequest(
                swapstring=swapstring,
                payment_secret=payment_secret,
                taker_pubkey=resolved_taker_pubkey,
            )
        )
        if is_json_mode():
            print_json(
                {"ok": True, "swapstring": swapstring, "taker_pubkey": resolved_taker_pubkey}
            )
        else:
            print_success("Node swap executed successfully")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@node_swap_app.command(
    "status",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Check the taker-side swap status:\n"
        "  [cyan]kaleido node swap status <payment-hash> --taker[/cyan]\n\n"
        "  Check the maker-side swap status:\n"
        "  [cyan]kaleido node swap status <payment-hash> --maker[/cyan]"
    ),
)
def node_status(
    payment_hash: Annotated[str | None, typer.Argument(help="Swap payment hash.")] = None,
    taker: Annotated[bool, typer.Option("--taker", help="Look up the taker-side swap.")] = False,
    maker: Annotated[bool, typer.Option("--maker", help="Look up the maker-side swap.")] = False,
) -> None:
    """Check a local node swap by payment hash."""
    resolved_payment_hash = resolve_required_text(
        payment_hash, "Payment hash", "PAYMENT_HASH argument"
    )
    if not taker and not maker:
        taker = True
    elif taker == maker:
        print_error("Must specify at most one of --taker or --maker")
        raise typer.Exit(1)
    asyncio.run(_node_status(resolved_payment_hash, taker))


async def _node_status(payment_hash: str, taker: bool) -> None:
    try:
        client = get_client(require_node=True)
        resp: GetSwapResponse = await client.rln.get_swap(
            GetSwapRequest(payment_hash=payment_hash, taker=taker)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            side = "Taker" if taker else "Maker"
            output_model(resp, title=f"{side} Node Swap — {payment_hash[:16]}…")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@node_swap_app.command(
    "list",
    epilog=(
        "[bold]Examples[/bold]\n\n  List all node swaps:\n  [cyan]kaleido node swap list[/cyan]"
    ),
)
def node_list() -> None:
    """List swaps known to the local RLN node."""
    asyncio.run(_node_list())


async def _node_list() -> None:
    try:
        client = get_client(require_node=True)
        resp: ListSwapsResponse = await client.rln.list_swaps()
        if is_json_mode():
            print_json(resp.model_dump())
            return
        items = []
        for swap in resp.taker or []:
            items.append({**swap.model_dump(), "role": "taker"})
        for swap in resp.maker or []:
            items.append({**swap.model_dump(), "role": "maker"})
        output_collection("Node Swaps", items, item_title="Node Swap — {index}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
