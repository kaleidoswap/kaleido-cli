"""Atomic swap commands — quote, history, status."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk import (
    Layer,
    OrderHistoryResponse,
    PairQuoteRequest,
    PairQuoteResponse,
    SwapLegInput,
    SwapOrderStatusRequest,
    SwapOrderStatusResponse,
    TradingPairsResponse,
)
from kaleido_sdk.rln import ListSwapsResponse

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_interactive,
    is_json_mode,
    output_model,
    print_error,
    print_json,
    print_table,
)

swap_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Execute and track atomic RGB+Lightning swaps.",
)


@swap_app.command(
    "quote",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  How much BTC (LN) to send to receive 500 USDT (RGB LN):\n"
        "  [cyan]kaleido swap quote BTC/USDT --to-amount 500[/cyan]\n\n"
        "  Send 100 000 msat, see how much USDT you get:\n"
        "  [cyan]kaleido swap quote BTC/USDT --from-amount 100000[/cyan]\n\n"
        "[bold]Available layers[/bold]: [green]BTC_LN[/green]  [green]RGB_LN[/green]  [green]BTC_ONCHAIN[/green]"
    ),
)
def swap_quote(
    pair: Annotated[
        str | None,
        typer.Argument(
            help="Trading pair in [green]BASE/QUOTE[/green] format, e.g. [green]BTC/USDT[/green]."
        ),
    ] = None,
    from_amount: Annotated[
        int | None,
        typer.Option(
            "--from-amount",
            help="Amount to send (raw units). Provide this OR --to-amount.",
        ),
    ] = None,
    to_amount: Annotated[
        int | None,
        typer.Option(
            "--to-amount",
            help="Amount to receive (raw units). Provide this OR --from-amount.",
        ),
    ] = None,
    from_layer: Annotated[
        str,
        typer.Option("--from-layer", help="Source layer: BTC_LN, RGB_LN, BTC_ONCHAIN."),
    ] = "BTC_LN",
    to_layer: Annotated[
        str,
        typer.Option("--to-layer", help="Destination layer: BTC_LN, RGB_LN, BTC_ONCHAIN."),
    ] = "RGB_LN",
) -> None:
    """Get a swap quote (alias for 'kaleido market quote')."""
    wizard = is_interactive()

    if pair is None:
        if wizard:
            pair = typer.prompt("Trading pair (e.g. BTC/USDT)")
        else:
            print_error("PAIR argument is required in non-interactive mode.")
            raise typer.Exit(1)

    if from_amount is None and to_amount is None:
        if wizard:
            choice = typer.prompt("Quote by [S]end amount or [R]eceive amount?", default="S")
            if choice.strip().upper().startswith("R"):
                to_amount = typer.prompt("Amount to receive (raw units)", type=int)
            else:
                from_amount = typer.prompt("Amount to send (raw units)", type=int)
        else:
            print_error("Provide --from-amount or --to-amount in non-interactive mode.")
            raise typer.Exit(1)

    asyncio.run(_swap_quote(pair, from_amount, to_amount, from_layer, to_layer))


async def _swap_quote(
    pair: str,
    from_amount: int | None,
    to_amount: int | None,
    from_layer: str,
    to_layer: str,
) -> None:
    try:
        client = get_client()
        pairs: TradingPairsResponse = await client.maker.list_pairs()
        matched = next(
            (p for p in (pairs.pairs or []) if f"{p.base.ticker}/{p.quote.ticker}" == pair.upper()),
            None,
        )
        if not matched:
            print_error(f"Pair {pair!r} not found.")
            raise typer.Exit(1)

        body = PairQuoteRequest(
            from_asset=SwapLegInput(
                asset_id=matched.base.ticker,
                layer=Layer(from_layer),
                amount=from_amount,
            ),
            to_asset=SwapLegInput(
                asset_id=matched.quote.ticker, layer=Layer(to_layer), amount=to_amount
            ),
        )
        quote: PairQuoteResponse = await client.maker.get_quote(body)

        if is_json_mode():
            print_json(quote.model_dump())
        else:
            output_model(quote, title=f"Quote — {pair.upper()}")
    except typer.Exit:
        raise
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@swap_app.command(
    "history",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  All history:\n"
        "  [cyan]kaleido swap history[/cyan]\n\n"
        "  Only failed swaps:\n"
        "  [cyan]kaleido swap history --status FAILED[/cyan]\n\n"
        "  Limit to most recent 5:\n"
        "  [cyan]kaleido swap history --limit 5[/cyan]\n\n"
        "[bold]Status values[/bold]: [green]PENDING[/green]  [green]FILLED[/green]  [green]FAILED[/green]  [green]EXPIRED[/green]"
    ),
)
def swap_history(
    status: Annotated[
        str | None,
        typer.Option("--status", help="Filter by status: PENDING, FILLED, FAILED, EXPIRED."),
    ] = None,
    limit: Annotated[
        int, typer.Option("--limit", help="Maximum number of results to return.")
    ] = 20,
) -> None:
    """Show swap order history."""
    asyncio.run(_swap_history(status, limit))


async def _swap_history(status: str | None, limit: int) -> None:
    try:
        client = get_client()
        resp: OrderHistoryResponse = await client.maker.get_order_history(
            status=status, limit=limit
        )
        if is_json_mode():
            print_json(resp.model_dump())
            return
        rows = [
            [
                o.id[:16] + "…" if o.id else "-",
                o.status,
                o.from_asset,
                o.to_asset,
                o.created_at,
            ]
            for o in (resp.data or [])
        ]
        print_table("Swap History", ["Order ID", "Status", "From", "To", "Created At"], rows)
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@swap_app.command(
    "status",
    epilog="  [cyan]kaleido swap status <order-id>[/cyan]   Use 'kaleido swap history' to find order IDs.",
)
def swap_status(
    order_id: Annotated[str, typer.Argument(help="Full swap order ID to look up.")],
) -> None:
    """Check the status of a swap order."""
    asyncio.run(_swap_status(order_id))


async def _swap_status(order_id: str) -> None:
    try:
        client = get_client()
        resp: SwapOrderStatusResponse = await client.maker.get_swap_order_status(
            SwapOrderStatusRequest(order_id=order_id)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title=f"Swap Order — {order_id[:16]}…")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@swap_app.command("node-swaps")
def swap_node_list() -> None:
    """List swaps known to the local RLN node."""
    asyncio.run(_swap_node_list())


async def _swap_node_list() -> None:
    try:
        client = get_client(require_node=True)
        resp: ListSwapsResponse = await client.rln.list_swaps()
        if is_json_mode():
            print_json(resp.model_dump())
            return
        rows = []
        for swap in resp.taker or []:
            rows.append(
                [
                    swap.payment_hash[:16] + "…" if swap.payment_hash else "-",
                    "taker",
                    swap.status,
                ]
            )
        for swap in resp.maker or []:
            rows.append(
                [
                    swap.payment_hash[:16] + "…" if swap.payment_hash else "-",
                    "maker",
                    swap.status,
                ]
            )
        print_table("Node Swaps", ["Payment Hash", "Role", "Status"], rows)
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
