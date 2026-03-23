"""Atomic swap and swap-order commands."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk import (
    ConfirmSwapRequest,
    ConfirmSwapResponse,
    CreateSwapOrderRequest,
    CreateSwapOrderResponse,
    Layer,
    OrderHistoryResponse,
    PairQuoteRequest,
    PairQuoteResponse,
    ReceiverAddress,
    ReceiverAddressFormat,
    SwapLegInput,
    SwapOrderRateDecisionRequest,
    SwapOrderRateDecisionResponse,
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
    print_info,
    print_json,
    print_success,
    print_table,
)

swap_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Execute and track atomic RGB+Lightning swaps.",
)


def _resolve_pair(pair: str | None) -> str:
    if pair is not None:
        return pair
    if is_interactive():
        return typer.prompt("Trading pair (e.g. BTC/USDT)")
    print_error("PAIR argument is required in non-interactive mode.")
    raise typer.Exit(1)


def _resolve_amount_pair(
    from_amount: int | None,
    to_amount: int | None,
    *,
    prompt_prefix: str,
    default_choice: str,
) -> tuple[int | None, int | None]:
    if from_amount is None and to_amount is None:
        if is_interactive():
            choice = typer.prompt(
                f"{prompt_prefix} by [S]end amount or [R]eceive amount?",
                default=default_choice,
            )
            if choice.strip().upper().startswith("R"):
                return None, typer.prompt("Amount to receive (raw units)", type=int)
            return typer.prompt("Amount to send (raw units)", type=int), None
        print_error("Provide --from-amount or --to-amount in non-interactive mode.")
        raise typer.Exit(1)
    if from_amount is not None and to_amount is not None:
        print_error("Provide exactly one of --from-amount or --to-amount.")
        raise typer.Exit(1)
    return from_amount, to_amount


def _resolve_required_text(value: str | None, prompt: str, option_name: str) -> str:
    if value is not None:
        return value
    if is_interactive():
        return typer.prompt(prompt)
    print_error(f"{option_name} is required in non-interactive mode.")
    raise typer.Exit(1)


def _resolve_accept_reject(accept: bool, reject: bool, prompt: str) -> bool:
    if is_interactive() and not accept and not reject:
        return typer.confirm(prompt, default=False)
    if accept == reject:
        print_error("Must specify exactly one of --accept or --reject")
        raise typer.Exit(1)
    return accept


async def _fetch_quote(
    pair: str,
    from_amount: int | None,
    to_amount: int | None,
    from_layer: str,
    to_layer: str,
) -> PairQuoteResponse:
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
            asset_id=matched.quote.ticker,
            layer=Layer(to_layer),
            amount=to_amount,
        ),
    )
    return await client.maker.get_quote(body)


@swap_app.command(
    "quote",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  How much BTC to send to receive 5 USDT over RGB Lightning:\n"
        "  [cyan]kaleido swap quote BTC/USDT --to-amount 5000000[/cyan]\n\n"
        "  Send 100 000 raw units and see how much USDT you get:\n"
        "  [cyan]kaleido swap quote BTC/USDT --from-amount 100000[/cyan]"
    ),
)
def swap_quote(
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
        typer.Option("--from-layer", help="Source layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN."),
    ] = "BTC_LN",
    to_layer: Annotated[
        str,
        typer.Option("--to-layer", help="Destination layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN."),
    ] = "RGB_LN",
) -> None:
    """Get a swap quote."""
    resolved_pair = _resolve_pair(pair)
    resolved_from_amount, resolved_to_amount = _resolve_amount_pair(
        from_amount,
        to_amount,
        prompt_prefix="Quote",
        default_choice="S",
    )
    asyncio.run(
        _swap_quote(
            resolved_pair,
            resolved_from_amount,
            resolved_to_amount,
            from_layer,
            to_layer,
        )
    )


async def _swap_quote(
    pair: str,
    from_amount: int | None,
    to_amount: int | None,
    from_layer: str,
    to_layer: str,
) -> None:
    try:
        quote = await _fetch_quote(pair, from_amount, to_amount, from_layer, to_layer)
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
    "create-order",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Swap sats for 5 USDT over RGB Lightning:\n"
        "  [cyan]kaleido swap create-order BTC/USDT --to-amount 5000000 "
        "--receiver-address lnbcrt... --receiver-format BOLT11[/cyan]\n\n"
        "  Swap onchain BTC into an RGB invoice:\n"
        "  [cyan]kaleido swap create-order BTC/USDT --to-amount 5000000 "
        "--from-layer BTC_L1 --to-layer RGB_L1 --receiver-address rgb:... "
        "--receiver-format RGB_INVOICE[/cyan]"
    ),
)
def swap_create_order(
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
        typer.Option("--from-layer", help="Source layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN."),
    ] = "BTC_LN",
    to_layer: Annotated[
        str,
        typer.Option("--to-layer", help="Destination layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN."),
    ] = "RGB_LN",
    receiver_address: Annotated[
        str | None,
        typer.Option("--receiver-address", help="Destination address/invoice for receiving the payout."),
    ] = None,
    receiver_format: Annotated[
        str | None,
        typer.Option("--receiver-format", help="Receiver format, e.g. BOLT11 or RGB_INVOICE."),
    ] = None,
    min_onchain_conf: Annotated[
        int,
        typer.Option("--min-onchain-conf", help="Minimum confirmations for onchain deposits."),
    ] = 1,
    refund_address: Annotated[
        str | None,
        typer.Option("--refund-address", help="Optional refund address for onchain deposits."),
    ] = None,
    email: Annotated[
        str | None,
        typer.Option("--email", help="Optional email for order notifications."),
    ] = None,
) -> None:
    """Create a swap order from a live quote."""
    resolved_pair = _resolve_pair(pair)
    resolved_from_amount, resolved_to_amount = _resolve_amount_pair(
        from_amount,
        to_amount,
        prompt_prefix="Order",
        default_choice="R",
    )
    resolved_receiver_address = _resolve_required_text(
        receiver_address,
        "Receiver address / invoice",
        "--receiver-address",
    )
    resolved_receiver_format = _resolve_required_text(
        receiver_format,
        "Receiver format (e.g. BOLT11, RGB_INVOICE, BTC_ADDRESS)",
        "--receiver-format",
    )
    asyncio.run(
        _swap_create_order(
            resolved_pair,
            resolved_from_amount,
            resolved_to_amount,
            from_layer,
            to_layer,
            resolved_receiver_address,
            resolved_receiver_format,
            min_onchain_conf,
            refund_address,
            email,
        )
    )


async def _swap_create_order(
    pair: str,
    from_amount: int | None,
    to_amount: int | None,
    from_layer: str,
    to_layer: str,
    receiver_address: str,
    receiver_format: str,
    min_onchain_conf: int,
    refund_address: str | None,
    email: str | None,
) -> None:
    try:
        client = get_client()
        quote = await _fetch_quote(pair, from_amount, to_amount, from_layer, to_layer)
        body = CreateSwapOrderRequest(
            rfq_id=quote.rfq_id,
            from_asset=quote.from_asset,
            to_asset=quote.to_asset,
            receiver_address=ReceiverAddress(
                address=receiver_address,
                format=ReceiverAddressFormat(receiver_format),
            ),
            min_onchain_conf=min_onchain_conf,
            refund_address=refund_address,
            email=email,
        )
        resp: CreateSwapOrderResponse = await client.maker.create_swap_order(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"Swap order created: {resp.id}")
            output_model(resp, title="Swap Order")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@swap_app.command(
    "order-decide",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Accept a requoted swap order:\n"
        "  [cyan]kaleido swap order-decide <order-id> --accept[/cyan]\n\n"
        "  Reject the new rate and request refund:\n"
        "  [cyan]kaleido swap order-decide <order-id> --reject[/cyan]"
    ),
)
def swap_order_decide(
    order_id: Annotated[str | None, typer.Argument(help="Swap order ID.")] = None,
    accept: Annotated[bool, typer.Option("--accept", help="Accept the new quoted rate.")] = False,
    reject: Annotated[
        bool,
        typer.Option("--reject", help="Reject the new quoted rate and request refund."),
    ] = False,
    access_token: Annotated[
        str,
        typer.Option("--access-token", help="Optional access token returned for the swap order."),
    ] = "",
) -> None:
    """Submit a rate decision for a pending swap order."""
    resolved_order_id = _resolve_required_text(order_id, "Swap order ID", "ORDER_ID argument")
    accept_new_rate = _resolve_accept_reject(accept, reject, "Accept the new quoted rate?")
    asyncio.run(_swap_order_decide(resolved_order_id, accept_new_rate, access_token))


async def _swap_order_decide(order_id: str, accept: bool, access_token: str) -> None:
    try:
        client = get_client()
        body = SwapOrderRateDecisionRequest(
            order_id=order_id,
            access_token=access_token,
            accept_new_rate=accept,
        )
        resp: SwapOrderRateDecisionResponse = await client.maker.submit_rate_decision(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            action = "accepted" if accept else "rejected"
            print_success(f"Swap order {order_id} {action}")
            output_model(resp, title="Swap Rate Decision")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@swap_app.command(
    "init-atomic",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Initialize an atomic swap from a live quote:\n"
        "  [cyan]kaleido swap init-atomic BTC/USDT --to-amount 5000000[/cyan]"
    ),
)
def swap_init_atomic(
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
        typer.Option("--from-layer", help="Source layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN."),
    ] = "BTC_LN",
    to_layer: Annotated[
        str,
        typer.Option("--to-layer", help="Destination layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN."),
    ] = "RGB_LN",
) -> None:
    """Initialize an atomic swap using a live quote."""
    resolved_pair = _resolve_pair(pair)
    resolved_from_amount, resolved_to_amount = _resolve_amount_pair(
        from_amount,
        to_amount,
        prompt_prefix="Atomic swap",
        default_choice="R",
    )
    asyncio.run(
        _swap_init_atomic(
            resolved_pair,
            resolved_from_amount,
            resolved_to_amount,
            from_layer,
            to_layer,
        )
    )


async def _swap_init_atomic(
    pair: str,
    from_amount: int | None,
    to_amount: int | None,
    from_layer: str,
    to_layer: str,
) -> None:
    try:
        client = get_client()
        quote = await _fetch_quote(pair, from_amount, to_amount, from_layer, to_layer)
        body = SwapRequest(
            rfq_id=quote.rfq_id,
            from_asset=quote.from_asset.asset_id,
            from_amount=quote.from_asset.amount,
            to_asset=quote.to_asset.asset_id,
            to_amount=quote.to_asset.amount,
        )
        resp: SwapResponse = await client.maker.init_swap(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"Atomic swap initialized: {resp.payment_hash}")
            output_model(resp, title="Atomic Swap Init")
            print_info("Next step: whitelist the swap on the taker node.")
            print_info(f"Run: kaleido swap whitelist-atomic --swapstring '{resp.swapstring}'")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@swap_app.command(
    "whitelist-atomic",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Whitelist an initialized atomic swap:\n"
        "  [cyan]kaleido swap whitelist-atomic --swapstring '<swapstring>'[/cyan]"
    ),
)
def swap_whitelist_atomic(
    swapstring: Annotated[
        str | None,
        typer.Option("--swapstring", help="Swap string returned by init-atomic."),
    ] = None,
) -> None:
    """Whitelist an initialized atomic swap on the local taker node."""
    resolved_swapstring = _resolve_required_text(swapstring, "Swap string", "--swapstring")
    asyncio.run(_swap_whitelist_atomic(resolved_swapstring))


async def _swap_whitelist_atomic(swapstring: str) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.whitelist_swap(swapstring)
        if is_json_mode():
            print_json({"ok": True, "swapstring": swapstring})
        else:
            print_success("Atomic swap whitelisted on taker node")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@swap_app.command(
    "execute-atomic",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Execute a previously initialized atomic swap:\n"
        "  [cyan]kaleido swap execute-atomic --swapstring '<swapstring>' "
        "--taker-pubkey 03ab... --payment-hash deadbeef...[/cyan]"
    ),
)
def swap_execute_atomic(
    swapstring: Annotated[
        str | None,
        typer.Option("--swapstring", help="Swap string returned by init-atomic."),
    ] = None,
    taker_pubkey: Annotated[
        str | None,
        typer.Option("--taker-pubkey", help="Taker node pubkey."),
    ] = None,
    payment_hash: Annotated[
        str | None,
        typer.Option("--payment-hash", help="Payment hash returned by init-atomic."),
    ] = None,
) -> None:
    """Execute a previously initialized atomic swap."""
    resolved_swapstring = _resolve_required_text(swapstring, "Swap string", "--swapstring")
    resolved_taker_pubkey = _resolve_required_text(
        taker_pubkey,
        "Taker pubkey",
        "--taker-pubkey",
    )
    resolved_payment_hash = _resolve_required_text(
        payment_hash,
        "Payment hash",
        "--payment-hash",
    )
    asyncio.run(
        _swap_execute_atomic(
            resolved_swapstring,
            resolved_taker_pubkey,
            resolved_payment_hash,
        )
    )


async def _swap_execute_atomic(
    swapstring: str,
    taker_pubkey: str,
    payment_hash: str,
) -> None:
    try:
        client = get_client()
        body = ConfirmSwapRequest(
            swapstring=swapstring,
            taker_pubkey=taker_pubkey,
            payment_hash=payment_hash,
        )
        resp: ConfirmSwapResponse = await client.maker.execute_swap(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success("Atomic swap execution submitted")
            output_model(resp, title="Atomic Swap Execute")
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


@swap_app.command(
    "atomic-status",
    epilog="  [cyan]kaleido swap atomic-status <payment-hash>[/cyan]",
)
def swap_atomic_status(
    payment_hash: Annotated[str, typer.Argument(help="Atomic swap payment hash.")],
) -> None:
    """Check the status of an atomic swap by payment hash."""
    asyncio.run(_swap_atomic_status(payment_hash))


async def _swap_atomic_status(payment_hash: str) -> None:
    try:
        client = get_client()
        resp: SwapStatusResponse = await client.maker.get_atomic_swap_status(
            SwapStatusRequest(payment_hash=payment_hash)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title=f"Atomic Swap — {payment_hash[:16]}…")
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
        "  [cyan]kaleido swap history --limit 5[/cyan]"
    ),
)
def swap_history(
    status: Annotated[
        str | None,
        typer.Option("--status", help="Filter by status: OPEN, PENDING_PAYMENT, PAID, EXECUTING, FILLED, FAILED, EXPIRED."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum number of results to return."),
    ] = 20,
) -> None:
    """Show swap order history."""
    asyncio.run(_swap_history(status, limit))


async def _swap_history(status: str | None, limit: int) -> None:
    try:
        client = get_client()
        resp: OrderHistoryResponse = await client.maker.get_order_history(
            status=status,
            limit=limit,
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
    "run",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Run a low-level node swap in test/dev setups:\n"
        "  [cyan]kaleido swap run --qty-from 30 --to-asset rgb:abc... --qty-to 10[/cyan]\n\n"
        "[dim]Low-level node swap: maker-init -> taker whitelist -> maker-execute.[/dim]"
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
        typer.Option("--taker-pubkey", help="Pubkey of the taker node. Defaults to own node pubkey."),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Run a low-level node swap: maker-init -> taker whitelist -> maker-execute."""
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

    asyncio.run(
        _swap_run(
            from_asset,
            resolved_qty_from,
            to_asset,
            resolved_qty_to,
            timeout_sec,
            taker_pubkey,
            yes,
        )
    )


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
        print_success(f"payment_hash: {init_resp.payment_hash}")
        print_success(f"payment_secret: {init_resp.payment_secret}")

        if not yes and is_interactive():
            confirmed = typer.confirm("Whitelist this swap on the taker side and execute?")
            if not confirmed:
                print_error("Swap cancelled after maker-init.")
                raise typer.Exit(0)

        await client.rln.whitelist_swap(TakerRequest(swapstring=init_resp.swapstring))
        print_success("Taker whitelisted the swap.")

        resolved_taker_pubkey = taker_pubkey_override or await client.rln.get_taker_pubkey()
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
