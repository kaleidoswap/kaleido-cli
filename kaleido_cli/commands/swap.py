"""Atomic swap commands — quote, history, status."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk import (
    ConfirmSwapRequest,
    Layer,
    OrderHistoryResponse,
    PairQuoteRequest,
    PairQuoteResponse,
    SwapLegInput,
    SwapOrderStatusRequest,
    SwapOrderStatusResponse,
    SwapRequest,
    SwapResponse,
    SwapStatusRequest,
    SwapStatusResponse,
    TradingPairsResponse,
)
from kaleido_sdk.rln import (
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
    output_model,
    print_error,
    print_json,
    print_success,
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
    resolved_pair: str
    if pair is not None:
        resolved_pair = pair
    elif is_interactive():
        resolved_pair = typer.prompt("Trading pair (e.g. BTC/USDT)")
    else:
        print_error("PAIR argument is required in non-interactive mode.")
        raise typer.Exit(1)

    if from_amount is None and to_amount is None:
        if is_interactive():
            choice = typer.prompt("Quote by [S]end amount or [R]eceive amount?", default="S")
            if choice.strip().upper().startswith("R"):
                to_amount = typer.prompt("Amount to receive (raw units)", type=int)
            else:
                from_amount = typer.prompt("Amount to send (raw units)", type=int)
        else:
            print_error("Provide --from-amount or --to-amount in non-interactive mode.")
            raise typer.Exit(1)
    elif from_amount is not None and to_amount is not None:
        print_error("Provide exactly one of --from-amount or --to-amount.")
        raise typer.Exit(1)

    asyncio.run(_swap_quote(resolved_pair, from_amount, to_amount, from_layer, to_layer))


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
    access_token: Annotated[
        str,
        typer.Option("--access-token", help="Optional access token returned for the swap order."),
    ] = "",
) -> None:
    """Check the status of a swap order."""
    asyncio.run(_swap_status(order_id, access_token))


async def _swap_status(order_id: str, access_token: str) -> None:
    try:
        client = get_client()
        resp: SwapOrderStatusResponse = await client.maker.get_swap_order_status(
            SwapOrderStatusRequest(order_id=order_id, access_token=access_token)
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


@swap_app.command(
    "execute",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Execute a swap from a previously obtained RFQ:\n"
        "  [cyan]kaleido swap execute BTC/USDT --from-amount 100000[/cyan]\n\n"
        "  With explicit layers:\n"
        "  [cyan]kaleido swap execute BTC/USDT --from-amount 100000 --from-layer BTC_LN --to-layer RGB_LN[/cyan]\n\n"
        "[dim]Requires a connected node. Gets a quote, creates a swap order, and executes it in one command.[/dim]"
    ),
)
def swap_execute(
    pair: Annotated[
        str | None,
        typer.Argument(help="Trading pair in BASE/QUOTE format, e.g. BTC/USDT."),
    ] = None,
    from_amount: Annotated[
        int | None,
        typer.Option("--from-amount", help="Amount to send (raw units). Provide this OR --to-amount."),
    ] = None,
    to_amount: Annotated[
        int | None,
        typer.Option("--to-amount", help="Amount to receive (raw units). Provide this OR --from-amount."),
    ] = None,
    from_layer: Annotated[
        str,
        typer.Option("--from-layer", help="Source layer: BTC_LN, RGB_LN, BTC_ONCHAIN."),
    ] = "BTC_LN",
    to_layer: Annotated[
        str,
        typer.Option("--to-layer", help="Destination layer: BTC_LN, RGB_LN, BTC_ONCHAIN."),
    ] = "RGB_LN",
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt and execute immediately."),
    ] = False,
) -> None:
    """Execute a full swap via the Kaleidoswap market API (quote → order → execute)."""
    resolved_pair: str
    if pair is not None:
        resolved_pair = pair
    elif is_interactive():
        resolved_pair = typer.prompt("Trading pair (e.g. BTC/USDT)")
    else:
        print_error("PAIR argument is required in non-interactive mode.")
        raise typer.Exit(1)

    if from_amount is None and to_amount is None:
        if is_interactive():
            choice = typer.prompt("Quote by [S]end amount or [R]eceive amount?", default="S")
            if choice.strip().upper().startswith("R"):
                to_amount = typer.prompt("Amount to receive (raw units)", type=int)
            else:
                from_amount = typer.prompt("Amount to send (raw units)", type=int)
        else:
            print_error("Provide --from-amount or --to-amount.")
            raise typer.Exit(1)
    elif from_amount is not None and to_amount is not None:
        print_error("Provide exactly one of --from-amount or --to-amount.")
        raise typer.Exit(1)

    asyncio.run(
        _swap_execute(resolved_pair, from_amount, to_amount, from_layer, to_layer, yes)
    )


async def _swap_execute(
    pair: str,
    from_amount: int | None,
    to_amount: int | None,
    from_layer: str,
    to_layer: str,
    yes: bool,
) -> None:
    from kaleido_sdk import CreateSwapOrderRequest

    try:
        client = get_client(require_node=True)

        # Step 1: get quote
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
                asset_id=matched.quote.ticker,
                layer=Layer(to_layer),
                amount=to_amount,
            ),
        )
        quote: PairQuoteResponse = await client.maker.get_quote(body)
        output_model(quote, title=f"Quote — {pair.upper()}")

        # Step 2: confirm
        if not yes and is_interactive():
            confirmed = typer.confirm("Proceed with this swap?")
            if not confirmed:
                print_error("Swap cancelled.")
                raise typer.Exit(0)
        elif not yes:
            print_error("Pass --yes to execute in non-interactive mode.")
            raise typer.Exit(1)

        # Step 3: create order
        taker_pubkey = await client.rln.get_taker_pubkey()
        order_resp = await client.maker.create_swap_order(
            CreateSwapOrderRequest(rfq_id=quote.rfq_id, taker_pubkey=taker_pubkey)
        )
        print_success(f"Order created: {order_resp.id}")

        # Step 4: init swap
        init_resp: SwapResponse = await client.maker.init_swap(
            SwapRequest(rfq_id=quote.rfq_id, order_id=order_resp.id)
        )
        print_success(f"Swap initialised — payment hash: {init_resp.payment_hash}")

        # Step 5: execute swap
        confirm_resp = await client.maker.execute_swap(
            ConfirmSwapRequest(payment_hash=init_resp.payment_hash)
        )

        if is_json_mode():
            print_json(confirm_resp.model_dump())
        else:
            output_model(confirm_resp, title="Swap Executed")
    except typer.Exit:
        raise
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@swap_app.command(
    "atomic-status",
    epilog="  [cyan]kaleido swap atomic-status --payment-hash <hash>[/cyan]",
)
def swap_atomic_status(
    payment_hash: Annotated[
        str | None,
        typer.Option("--payment-hash", "-p", help="Payment hash of the atomic swap."),
    ] = None,
) -> None:
    """Check the status of an atomic swap by payment hash."""
    resolved_hash: str
    if payment_hash is not None:
        resolved_hash = payment_hash
    elif is_interactive():
        resolved_hash = typer.prompt("Payment hash")
    else:
        print_error("--payment-hash is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(_swap_atomic_status(resolved_hash))


async def _swap_atomic_status(payment_hash: str) -> None:
    try:
        client = get_client()
        resp: SwapStatusResponse = await client.maker.get_atomic_swap_status(
            SwapStatusRequest(payment_hash=payment_hash)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title=f"Atomic Swap Status — {payment_hash[:16]}…")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@swap_app.command(
    "run",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Interactive swap (send 30 USDT, receive 10 BTC):\n"
        "  [cyan]kaleido swap run --from-asset rgb:CJkb4... --qty-from 30 --to-asset rgb:icfqn... --qty-to 10[/cyan]\n\n"
        "  BTC→RGB (from_asset is None):\n"
        "  [cyan]kaleido swap run --qty-from 30 --to-asset rgb:abc... --qty-to 10[/cyan]\n\n"
        "[dim]Low-level node swap: maker-init \u2192 taker whitelist \u2192 maker-execute.[/dim]\n"
        "[dim]Both maker and taker must be running on the same node (test/dev setup).[/dim]"
    ),
)
def swap_run(
    from_asset: Annotated[
        str | None,
        typer.Option("--from-asset", help="RGB asset ID the maker will send (None = BTC)."),
    ] = None,
    qty_from: Annotated[
        int | None,
        typer.Option("--qty-from", help="Amount the maker will send (raw units)."),
    ] = None,
    to_asset: Annotated[
        str | None,
        typer.Option("--to-asset", help="RGB asset ID the maker will receive (None = BTC)."),
    ] = None,
    qty_to: Annotated[
        int | None,
        typer.Option("--qty-to", help="Amount the maker will receive (raw units)."),
    ] = None,
    timeout_sec: Annotated[
        int,
        typer.Option("--timeout", help="Swap offer timeout in seconds."),
    ] = 100,
    taker_pubkey: Annotated[
        str | None,
        typer.Option("--taker-pubkey", help="Pubkey of the taker node. Defaults to own node's pubkey."),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """
    Interactive node-level swap: maker-init → taker whitelist → maker-execute.

    Useful for local testing and p2p swaps without the market API.
    """
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

    asyncio.run(_swap_run(from_asset, qty_from, to_asset, qty_to, timeout_sec, taker_pubkey, yes))


async def _swap_run(
    from_asset: str | None,
    qty_from: int,
    to_asset: str | None,
    qty_to: int,
    timeout_sec: int,
    taker_pubkey_override: str | None,
    yes: bool,
) -> None:
    try:
        client = get_client(require_node=True)

        # Step 1: maker-init
        init_resp: MakerInitResponse = await client.rln.maker_init(
            MakerInitRequest(
                qty_from=qty_from,
                qty_to=qty_to,
                from_asset=from_asset,
                to_asset=to_asset,
                timeout_sec=timeout_sec,
            )
        )

        print_success(f"Maker init done — swapstring: {init_resp.swapstring}")
        print_success(f"  payment_hash : {init_resp.payment_hash}")
        print_success(f"  payment_secret: {init_resp.payment_secret}")

        if not yes and is_interactive():
            confirmed = typer.confirm("Whitelist this swap on the taker side and execute?")
            if not confirmed:
                print_error("Swap cancelled after maker-init.")
                raise typer.Exit(0)

        # Step 2: taker whitelist
        await client.rln.whitelist_swap(TakerRequest(swapstring=init_resp.swapstring))
        print_success("Taker whitelisted the swap.")

        # Step 3: get taker pubkey (for maker-execute)
        resolved_taker_pubkey = taker_pubkey_override or await client.rln.get_taker_pubkey()

        # Step 4: maker-execute
        await client.rln.maker_execute(
            MakerExecuteRequest(
                swapstring=init_resp.swapstring,
                payment_secret=init_resp.payment_secret,
                taker_pubkey=resolved_taker_pubkey,
            )
        )

        print_success("Swap executed successfully!")
    except typer.Exit:
        raise
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)

