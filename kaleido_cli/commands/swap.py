"""Swap order, maker atomic swap, and local node swap commands."""

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
    parse_raw_amount,
)
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
from kaleido_cli.utils.pairs import pair_assets, resolve_quote_layers, resolve_trading_pair

swap_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Swap operations grouped by scope: maker order, maker atomic, and local node.",
)
order_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Maker swap-order flow via the Kaleidoswap server.",
)
atomic_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Atomic swap flow against the Kaleidoswap maker server, using your local node as taker.",
)
node_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Local RLN node swap flow: maker-init, taker whitelist, then maker-execute.",
)

swap_app.add_typer(order_app, name="order")
swap_app.add_typer(atomic_app, name="atomic")
swap_app.add_typer(node_app, name="node")


def _resolve_pair(pair: str | None) -> str:
    if pair is not None:
        return pair
    if is_interactive():
        return typer.prompt("Trading pair (e.g. BTC/USDT)")
    print_error("PAIR argument is required in non-interactive mode.")
    raise typer.Exit(1)


def _resolve_amount_pair(
    from_amount: str | None,
    to_amount: str | None,
    *,
    prompt_prefix: str,
    default_choice: str,
    pair: str,
) -> tuple[str | None, str | None]:
    base_ticker, _, quote_ticker = pair.partition("/")
    send_label = base_ticker or "base asset"
    receive_label = quote_ticker or "quote asset"
    if from_amount is None and to_amount is None:
        if is_interactive():
            choice = typer.prompt(
                f"{prompt_prefix} by [S]end amount or [R]eceive amount?",
                default=default_choice,
            )
            if choice.strip().upper().startswith("R"):
                return None, typer.prompt(f"Amount to receive ({receive_label}, display units)")
            return typer.prompt(f"Amount to send ({send_label}, display units)"), None
        print_error("Provide --from-amount or --to-amount in non-interactive mode.")
        raise typer.Exit(1)
    if from_amount is not None and to_amount is not None:
        print_error("Provide exactly one of --from-amount or --to-amount.")
        raise typer.Exit(1)
    return from_amount, to_amount


def _display_amount_to_raw(
    value: str,
    *,
    precision: int | None,
    asset_label: str,
    option_name: str,
) -> int:
    normalized = value.strip()
    if not normalized:
        print_error(f"{option_name} cannot be empty.")
        raise typer.Exit(1)
    try:
        return parse_raw_amount(normalized, precision or 0)
    except ValueError as exc:
        print_error(f"{option_name} for {asset_label}: {exc}")
        raise typer.Exit(1)


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


def _confirm_quote_or_exit(quote: PairQuoteResponse, *, title: str, yes: bool) -> None:
    """Show a quote and require explicit acceptance before continuing."""
    if is_json_mode():
        if not yes:
            print_error("--yes is required in non-interactive mode to accept the quoted price.")
            raise typer.Exit(1)
        return

    output_model(quote, title=title)

    if is_interactive():
        if yes:
            return
        if not typer.confirm("Proceed with this quote?", default=True):
            print_error("Swap cancelled before initialization.")
            raise typer.Exit(0)
        return

    if not yes:
        print_error("--yes is required in non-interactive mode to accept the quoted price.")
        raise typer.Exit(1)


async def _fetch_quote(
    pair: str,
    from_amount: str | None,
    to_amount: str | None,
    from_layer: str,
    to_layer: str,
) -> PairQuoteResponse:
    client = get_client()
    pairs: TradingPairsResponse = await client.maker.list_pairs()
    resolved_pair = resolve_trading_pair(pairs.pairs, pair)
    if not resolved_pair:
        print_error(f"Pair {pair!r} not found.")
        raise typer.Exit(1)
    matched_pair, is_reversed = resolved_pair
    from_asset, to_asset = pair_assets(matched_pair, is_reversed)

    resolved_from_amount = (
        _display_amount_to_raw(
            from_amount,
            precision=from_asset.precision,
            asset_label=from_asset.ticker,
            option_name="--from-amount",
        )
        if from_amount is not None
        else None
    )
    resolved_to_amount = (
        _display_amount_to_raw(
            to_amount,
            precision=to_asset.precision,
            asset_label=to_asset.ticker,
            option_name="--to-amount",
        )
        if to_amount is not None
        else None
    )

    body = PairQuoteRequest(
        from_asset=SwapLegInput(
            asset_id=from_asset.ticker,
            layer=Layer(from_layer),
            amount=resolved_from_amount,
        ),
        to_asset=SwapLegInput(
            asset_id=to_asset.ticker,
            layer=Layer(to_layer),
            amount=resolved_to_amount,
        ),
    )
    return await client.maker.get_quote(body)


@order_app.command(
    "create",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Swap sats for 5 USDT over RGB Lightning:\n"
        "  [cyan]kaleido swap order create BTC/USDT --to-amount 5 "
        "--receiver-address lnbcrt... --receiver-format BOLT11[/cyan]\n\n"
        "  Swap onchain BTC into an RGB invoice:\n"
        "  [cyan]kaleido swap order create BTC/USDT --to-amount 5 "
        "--from-layer BTC_L1 --to-layer RGB_L1 --receiver-address rgb:... "
        "--receiver-format RGB_INVOICE[/cyan]"
    ),
)
def order_create(
    pair: Annotated[
        str | None, typer.Argument(help="Trading pair in BASE/QUOTE format, e.g. BTC/USDT.")
    ] = None,
    from_amount: Annotated[
        str | None,
        typer.Option(
            "--from-amount",
            help="Amount to send in display units. Provide this OR --to-amount.",
        ),
    ] = None,
    to_amount: Annotated[
        str | None,
        typer.Option(
            "--to-amount",
            help="Amount to receive in display units. Provide this OR --from-amount.",
        ),
    ] = None,
    from_layer: Annotated[
        str | None,
        typer.Option(
            "--from-layer",
            help="Source layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN. Defaults from the requested pair direction.",
        ),
    ] = None,
    to_layer: Annotated[
        str | None,
        typer.Option(
            "--to-layer",
            help="Destination layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN. Defaults from the requested pair direction.",
        ),
    ] = None,
    receiver_address: Annotated[
        str | None,
        typer.Option(
            "--receiver-address", help="Destination address/invoice for receiving the payout."
        ),
    ] = None,
    receiver_format: Annotated[
        str | None,
        typer.Option("--receiver-format", help="Receiver format, e.g. BOLT11 or RGB_INVOICE."),
    ] = None,
    min_onchain_conf: Annotated[
        int, typer.Option("--min-onchain-conf", help="Minimum confirmations for onchain deposits.")
    ] = 1,
    refund_address: Annotated[
        str | None,
        typer.Option("--refund-address", help="Optional refund address for onchain deposits."),
    ] = None,
    email: Annotated[
        str | None, typer.Option("--email", help="Optional email for order notifications.")
    ] = None,
) -> None:
    """Create a maker swap order from a live quote."""
    resolved_pair = _resolve_pair(pair)
    resolved_from_amount, resolved_to_amount = _resolve_amount_pair(
        from_amount, to_amount, prompt_prefix="Order", default_choice="R", pair=resolved_pair
    )
    resolved_from_layer, resolved_to_layer = resolve_quote_layers(
        resolved_pair, from_layer, to_layer
    )
    resolved_receiver_address = _resolve_required_text(
        receiver_address, "Receiver address / invoice", "--receiver-address"
    )
    resolved_receiver_format = _resolve_required_text(
        receiver_format,
        "Receiver format (e.g. BOLT11, RGB_INVOICE, BTC_ADDRESS)",
        "--receiver-format",
    )
    asyncio.run(
        _order_create(
            resolved_pair,
            resolved_from_amount,
            resolved_to_amount,
            resolved_from_layer,
            resolved_to_layer,
            resolved_receiver_address,
            resolved_receiver_format,
            min_onchain_conf,
            refund_address,
            email,
        )
    )


async def _order_create(
    pair: str,
    from_amount: str | None,
    to_amount: str | None,
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


@order_app.command(
    "decide",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Accept a requoted swap order:\n"
        "  [cyan]kaleido swap order decide <order-id> --accept[/cyan]\n\n"
        "  Reject the new rate and request refund:\n"
        "  [cyan]kaleido swap order decide <order-id> --reject[/cyan]"
    ),
)
def order_decide(
    order_id: Annotated[str | None, typer.Argument(help="Swap order ID.")] = None,
    accept: Annotated[bool, typer.Option("--accept", help="Accept the new quoted rate.")] = False,
    reject: Annotated[
        bool, typer.Option("--reject", help="Reject the new quoted rate and request refund.")
    ] = False,
    access_token: Annotated[
        str,
        typer.Option("--access-token", help="Optional access token returned for the swap order."),
    ] = "",
) -> None:
    """Submit a rate decision for a pending maker swap order."""
    resolved_order_id = _resolve_required_text(order_id, "Swap order ID", "ORDER_ID argument")
    accept_new_rate = _resolve_accept_reject(accept, reject, "Accept the new quoted rate?")
    asyncio.run(_order_decide(resolved_order_id, accept_new_rate, access_token))


async def _order_decide(order_id: str, accept: bool, access_token: str) -> None:
    try:
        client = get_client()
        body = SwapOrderRateDecisionRequest(
            order_id=order_id, access_token=access_token, accept_new_rate=accept
        )
        resp: SwapOrderRateDecisionResponse = await client.maker.submit_rate_decision(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"Swap order {order_id} {'accepted' if accept else 'rejected'}")
            output_model(resp, title="Swap Rate Decision")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@order_app.command(
    "status",
    epilog="  [cyan]kaleido swap order status <order-id>[/cyan]   Use 'kaleido swap order history' to find order IDs.",
)
def order_status(
    order_id: Annotated[str, typer.Argument(help="Full swap order ID to look up.")],
    access_token: Annotated[
        str,
        typer.Option("--access-token", help="Optional access token returned for the swap order."),
    ] = "",
) -> None:
    """Check the status of a maker swap order."""
    asyncio.run(_order_status(order_id, access_token))


async def _order_status(order_id: str, access_token: str) -> None:
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


@order_app.command(
    "history",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  All history:\n"
        "  [cyan]kaleido swap order history[/cyan]\n\n"
        "  Only failed swaps:\n"
        "  [cyan]kaleido swap order history --status FAILED[/cyan]\n\n"
        "  Limit to most recent 5:\n"
        "  [cyan]kaleido swap order history --limit 5[/cyan]\n\n"
        "[bold]Status values[/bold]: [green]OPEN[/green]  [green]PENDING_PAYMENT[/green]  "
        "[green]PAID[/green]  [green]EXECUTING[/green]  [green]FILLED[/green]  "
        "[green]CANCELLED[/green]  [green]EXPIRED[/green]  [green]FAILED[/green]  "
        "[green]PENDING_RATE_DECISION[/green]"
    ),
)
def order_history(
    status: Annotated[
        str | None,
        typer.Option(
            "--status",
            help="Filter by status: OPEN, PENDING_PAYMENT, PAID, EXECUTING, FILLED, CANCELLED, EXPIRED, FAILED, PENDING_RATE_DECISION.",
        ),
    ] = None,
    limit: Annotated[
        int, typer.Option("--limit", help="Maximum number of results to return.")
    ] = 20,
) -> None:
    """Show maker swap-order history."""
    asyncio.run(_order_history(status, limit))


async def _order_history(status: str | None, limit: int) -> None:
    try:
        client = get_client()
        resp: OrderHistoryResponse = await client.maker.get_order_history(
            status=status, limit=limit
        )
        if is_json_mode():
            print_json(resp.model_dump())
            return
        output_collection(
            "Swap History",
            [o.model_dump() for o in (resp.data or [])],
            item_title="Swap Order — {index}",
        )
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@atomic_app.command(
    "init",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Initialize an atomic swap from a live quote:\n"
        "  [cyan]kaleido swap atomic init BTC/USDT --to-amount 5[/cyan]\n\n"
        "[dim]After init, you can whitelist explicitly, or let execute do it for you:[/dim]\n"
        "[cyan]kaleido swap node whitelist --swapstring '<swapstring>'[/cyan]\n"
        "[cyan]kaleido swap atomic execute --swapstring '<swapstring>' "
        "--taker-pubkey <pubkey> --payment-hash <payment-hash>[/cyan]\n"
        "[cyan]kaleido swap atomic execute --auto-whitelist --swapstring '<swapstring>' "
        "--taker-pubkey <pubkey> --payment-hash <payment-hash>[/cyan]"
    ),
)
def atomic_init(
    pair: Annotated[
        str | None, typer.Argument(help="Trading pair in BASE/QUOTE format, e.g. BTC/USDT.")
    ] = None,
    from_amount: Annotated[
        str | None,
        typer.Option(
            "--from-amount",
            help="Amount to send in display units. Provide this OR --to-amount.",
        ),
    ] = None,
    to_amount: Annotated[
        str | None,
        typer.Option(
            "--to-amount",
            help="Amount to receive in display units. Provide this OR --from-amount.",
        ),
    ] = None,
    from_layer: Annotated[
        str | None,
        typer.Option(
            "--from-layer",
            help="Source layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN. Defaults from the requested pair direction.",
        ),
    ] = None,
    to_layer: Annotated[
        str | None,
        typer.Option(
            "--to-layer",
            help="Destination layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN. Defaults from the requested pair direction.",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Accept the displayed quote without prompting. Required in non-interactive mode.",
        ),
    ] = False,
) -> None:
    """Initialize an atomic swap against the maker server using a live quote."""
    resolved_pair = _resolve_pair(pair)
    resolved_from_amount, resolved_to_amount = _resolve_amount_pair(
        from_amount,
        to_amount,
        prompt_prefix="Atomic swap",
        default_choice="R",
        pair=resolved_pair,
    )
    resolved_from_layer, resolved_to_layer = resolve_quote_layers(
        resolved_pair, from_layer, to_layer
    )
    asyncio.run(
        _atomic_init(
            resolved_pair,
            resolved_from_amount,
            resolved_to_amount,
            resolved_from_layer,
            resolved_to_layer,
            yes,
        )
    )


async def _atomic_init(
    pair: str,
    from_amount: str | None,
    to_amount: str | None,
    from_layer: str,
    to_layer: str,
    yes: bool,
) -> None:
    try:
        client = get_client()
        quote = await _fetch_quote(pair, from_amount, to_amount, from_layer, to_layer)
        _confirm_quote_or_exit(quote, title=f"Quote — {pair.upper()}", yes=yes)
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
            print_info("Next step: choose one of these two flows.")
            print_info(
                "Flow 1 (manual): whitelist first on your local taker node, then execute against the maker server."
            )
            print_info(f"  kaleido swap node whitelist --swapstring '{resp.swapstring}'")
            print_info(
                f"  kaleido swap atomic execute --swapstring '{resp.swapstring}' "
                f"--taker-pubkey <pubkey> --payment-hash {resp.payment_hash}"
            )
            print_info(
                "Flow 2 (automatic): let atomic execute whitelist on your local node first, then execute against the maker server."
            )
            print_info(
                f"  kaleido swap atomic execute --auto-whitelist --swapstring '{resp.swapstring}' "
                f"--taker-pubkey <pubkey> --payment-hash {resp.payment_hash}"
            )
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@atomic_app.command(
    "execute",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Execute a previously initialized atomic swap:\n"
        "  [cyan]kaleido swap atomic execute --swapstring '<swapstring>' "
        "--taker-pubkey 03ab... --payment-hash deadbeef...[/cyan]\n\n"
        "  Auto-whitelist before executing:\n"
        "  [cyan]kaleido swap atomic execute --auto-whitelist --swapstring '<swapstring>' "
        "--taker-pubkey 03ab... --payment-hash deadbeef...[/cyan]\n\n"
        "[dim]Use the taker node pubkey from 'kaleido node taker pubkey' or your node's pubkey.[/dim]"
    ),
)
def atomic_execute(
    swapstring: Annotated[
        str | None, typer.Option("--swapstring", help="Swap string returned by atomic init.")
    ] = None,
    taker_pubkey: Annotated[
        str | None, typer.Option("--taker-pubkey", help="Taker node pubkey.")
    ] = None,
    payment_hash: Annotated[
        str | None, typer.Option("--payment-hash", help="Payment hash returned by atomic init.")
    ] = None,
    auto_whitelist: Annotated[
        bool,
        typer.Option(
            "--auto-whitelist",
            help="Whitelist the swap on the local taker node before executing it.",
        ),
    ] = False,
) -> None:
    """Execute an atomic swap against the maker server."""
    resolved_swapstring = _resolve_required_text(swapstring, "Swap string", "--swapstring")
    resolved_taker_pubkey = _resolve_required_text(taker_pubkey, "Taker pubkey", "--taker-pubkey")
    resolved_payment_hash = _resolve_required_text(payment_hash, "Payment hash", "--payment-hash")
    if is_interactive() and not auto_whitelist:
        auto_whitelist = typer.confirm(
            "Auto-whitelist on the local taker node before executing?",
            default=False,
        )
    asyncio.run(
        _atomic_execute(
            resolved_swapstring, resolved_taker_pubkey, resolved_payment_hash, auto_whitelist
        )
    )


async def _atomic_execute(
    swapstring: str,
    taker_pubkey: str,
    payment_hash: str,
    auto_whitelist: bool,
) -> None:
    try:
        client = get_client(require_node=auto_whitelist)
        if auto_whitelist:
            await client.rln.whitelist_swap(TakerRequest(swapstring=swapstring))
        resp: ConfirmSwapResponse = await client.maker.execute_swap(
            ConfirmSwapRequest(
                swapstring=swapstring,
                taker_pubkey=taker_pubkey,
                payment_hash=payment_hash,
            )
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            if auto_whitelist:
                print_success("Atomic swap whitelisted on taker node")
            print_success("Atomic swap execution submitted")
            output_model(resp, title="Atomic Swap Execute")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@atomic_app.command(
    "status",
    epilog="  [cyan]kaleido swap atomic status <payment-hash>[/cyan]",
)
def atomic_status(
    payment_hash: Annotated[str, typer.Argument(help="Atomic swap payment hash.")],
) -> None:
    """Check the status of an atomic swap against the maker server."""
    asyncio.run(_atomic_status(payment_hash))


async def _atomic_status(payment_hash: str) -> None:
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


@atomic_app.command(
    "run",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Run an atomic swap in one command using your local taker node:\n"
        "  [cyan]kaleido swap atomic run BTC/USDT --to-amount 5[/cyan]\n\n"
        "  Non-interactive flow with an explicit taker pubkey:\n"
        "  [cyan]kaleido swap atomic run BTC/USDT --from-amount 0.001 --from-layer BTC_LN "
        "--to-layer RGB_LN --taker-pubkey 03ab... --yes[/cyan]\n\n"
        "[dim]This wrapper automates atomic init, local taker whitelist, and atomic execute.[/dim]"
    ),
)
def atomic_run(
    pair: Annotated[
        str | None, typer.Argument(help="Trading pair in BASE/QUOTE format, e.g. BTC/USDT.")
    ] = None,
    from_amount: Annotated[
        str | None,
        typer.Option(
            "--from-amount",
            help="Amount to send in display units. Provide this OR --to-amount.",
        ),
    ] = None,
    to_amount: Annotated[
        str | None,
        typer.Option(
            "--to-amount",
            help="Amount to receive in display units. Provide this OR --from-amount.",
        ),
    ] = None,
    from_layer: Annotated[
        str | None,
        typer.Option(
            "--from-layer",
            help="Source layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN. Defaults from the requested pair direction.",
        ),
    ] = None,
    to_layer: Annotated[
        str | None,
        typer.Option(
            "--to-layer",
            help="Destination layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN. Defaults from the requested pair direction.",
        ),
    ] = None,
    taker_pubkey: Annotated[
        str | None,
        typer.Option(
            "--taker-pubkey", help="Taker node pubkey. Defaults to the local node taker pubkey."
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Accept the displayed quote and skip later confirmations. Required in non-interactive mode.",
        ),
    ] = False,
) -> None:
    """Run an atomic swap end-to-end using the local node as taker."""
    resolved_pair = _resolve_pair(pair)
    resolved_from_amount, resolved_to_amount = _resolve_amount_pair(
        from_amount,
        to_amount,
        prompt_prefix="Atomic swap",
        default_choice="R",
        pair=resolved_pair,
    )
    resolved_from_layer, resolved_to_layer = resolve_quote_layers(
        resolved_pair, from_layer, to_layer
    )
    asyncio.run(
        _atomic_run(
            resolved_pair,
            resolved_from_amount,
            resolved_to_amount,
            resolved_from_layer,
            resolved_to_layer,
            taker_pubkey,
            yes,
        )
    )


async def _atomic_run(
    pair: str,
    from_amount: str | None,
    to_amount: str | None,
    from_layer: str,
    to_layer: str,
    taker_pubkey_override: str | None,
    yes: bool,
) -> None:
    try:
        client = get_client(require_node=True)
        quote = await _fetch_quote(pair, from_amount, to_amount, from_layer, to_layer)
        _confirm_quote_or_exit(quote, title=f"Quote — {pair.upper()}", yes=yes)
        init_resp: SwapResponse = await client.maker.init_swap(
            SwapRequest(
                rfq_id=quote.rfq_id,
                from_asset=quote.from_asset.asset_id,
                from_amount=quote.from_asset.amount,
                to_asset=quote.to_asset.asset_id,
                to_amount=quote.to_asset.amount,
            )
        )
        resolved_taker_pubkey = taker_pubkey_override or await client.rln.get_taker_pubkey()

        if not yes and is_interactive():
            confirmed = typer.confirm(
                "Whitelist this atomic swap on the local taker node and execute it now?",
                default=True,
            )
            if not confirmed:
                print_error("Swap cancelled after atomic init.")
                raise typer.Exit(0)

        await client.rln.whitelist_swap(TakerRequest(swapstring=init_resp.swapstring))
        execute_resp: ConfirmSwapResponse = await client.maker.execute_swap(
            ConfirmSwapRequest(
                swapstring=init_resp.swapstring,
                taker_pubkey=resolved_taker_pubkey,
                payment_hash=init_resp.payment_hash,
            )
        )

        if is_json_mode():
            print_json(
                {
                    "init": init_resp.model_dump(),
                    "whitelisted": True,
                    "taker_pubkey": resolved_taker_pubkey,
                    "execute": execute_resp.model_dump(),
                }
            )
        else:
            print_success(f"Atomic swap initialized: {init_resp.payment_hash}")
            output_model(init_resp, title="Atomic Swap Init")
            print_success("Swap whitelisted on local taker node")
            print_success("Atomic swap execution submitted")
            output_model(
                {
                    "taker_pubkey": resolved_taker_pubkey,
                    **execute_resp.model_dump(),
                },
                title="Atomic Swap Execute",
            )
    except typer.Exit:
        raise
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@node_app.command(
    "init",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Initialize a local node swap:\n"
        "  [cyan]kaleido swap node init --qty-from 30 --to-asset rgb:abc... --qty-to 10[/cyan]"
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


@node_app.command(
    "whitelist",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Whitelist a swap on the local taker node:\n"
        "  [cyan]kaleido swap node whitelist --swapstring '<swapstring>'[/cyan]"
    ),
)
def node_whitelist(
    swapstring: Annotated[
        str | None,
        typer.Option("--swapstring", help="Swap string returned by node init or atomic init."),
    ] = None,
) -> None:
    """Whitelist a swap on the local taker node via /taker."""
    resolved_swapstring = _resolve_required_text(swapstring, "Swap string", "--swapstring")
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


@node_app.command(
    "execute",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Execute a previously initialized local node swap:\n"
        "  [cyan]kaleido swap node execute --swapstring '<swapstring>' "
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
    resolved_swapstring = _resolve_required_text(swapstring, "Swap string", "--swapstring")
    resolved_payment_secret = _resolve_required_text(
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


@node_app.command(
    "status",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Check the taker-side swap status:\n"
        "  [cyan]kaleido swap node status <payment-hash> --taker[/cyan]\n\n"
        "  Check the maker-side swap status:\n"
        "  [cyan]kaleido swap node status <payment-hash> --maker[/cyan]"
    ),
)
def node_status(
    payment_hash: Annotated[str | None, typer.Argument(help="Swap payment hash.")] = None,
    taker: Annotated[bool, typer.Option("--taker", help="Look up the taker-side swap.")] = False,
    maker: Annotated[bool, typer.Option("--maker", help="Look up the maker-side swap.")] = False,
) -> None:
    """Check a local node swap by payment hash."""
    resolved_payment_hash = _resolve_required_text(
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


@node_app.command(
    "list",
    epilog=(
        "[bold]Examples[/bold]\n\n  List all node swaps:\n  [cyan]kaleido swap node list[/cyan]"
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
