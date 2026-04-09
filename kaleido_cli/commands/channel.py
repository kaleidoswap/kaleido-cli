"""Lightning channel commands — list, open, close, and LSP orders."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk import (
    ChannelOrderResponse,
    LspInfoResponse,
    NetworkInfoResponse,
    RateDecisionRequest,
    RateDecisionResponse,
)
from kaleido_sdk.rln import (
    CloseChannelRequest,
    ListChannelsResponse,
    OpenChannelRequest,
    OpenChannelResponse,
    SendPaymentRequest,
    SendPaymentResponse,
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
from kaleido_cli.utils.channel_orders import (
    CHANNEL_ORDER_HTTP_TIMEOUT,
    _attach_client_asset_quote,
    _autofill_refund_address,
    _can_pay_channel_order,
    _channel_wallet_payment_summary,
    _create_channel_order,
    _ensure_lsp_peer_connected,
    _estimate_channel_order_fees,
    _get_channel_order,
    _print_channel_order_fees,
    _print_lsp_info,
    _resolve_channel_fee_estimate_params,
    _resolve_channel_order_params,
    _timed_step,
)
from kaleido_cli.utils.prompts import resolve_required_text


def _resolve_optional_access_token(access_token: str | None) -> str:
    if access_token is not None:
        return access_token
    if is_interactive():
        return typer.prompt("Access token", default="")
    return ""


def _access_token_args(access_token: str | None) -> str:
    if not access_token:
        return ""
    return f" --access-token {access_token}"


channel_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Manage Lightning channels — list, open, close, and place LSP orders.",
)
order_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="LSP-backed channel order flow: create, inspect, pay, decide, and estimate fees.",
)
lsp_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Inspect Kaleidoswap LSP metadata and network details.",
)

channel_app.add_typer(order_app, name="order")
channel_app.add_typer(lsp_app, name="lsp")


@channel_app.command("list")
def channel_list() -> None:
    """List Lightning channels."""
    asyncio.run(_channel_list())


async def _channel_list() -> None:
    try:
        client = get_client(require_node=True)
        resp: ListChannelsResponse = await client.rln.list_channels()
        if is_json_mode():
            print_json(resp.model_dump())
            return
        output_collection(
            "Channels",
            [c for c in (resp.channels or [])],
            item_title="Channel Details — {index}",
            empty_msg="No channels.",
        )
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@channel_app.command(
    "open",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Plain BTC channel (100 000 sat):\n"
        "  [cyan]kaleido channel open 03abc...@peer.host:9735 --capacity 100000[/cyan]\n\n"
        "  Push 10 000 msat to the remote side on open:\n"
        "  [cyan]kaleido channel open 03abc...@peer.host:9735 --capacity 100000 --push-msat 10000[/cyan]\n\n"
        "  RGB colored channel (attach USDT):\n"
        "  [cyan]kaleido channel open 03abc...@peer.host:9735 --capacity 100000 \\'\n"
        "      --asset-id rgb:abc... --asset-amount 5000[/cyan]\n\n"
        "  Private channel:\n"
        "  [cyan]kaleido channel open 03abc...@peer.host:9735 --capacity 100000 --private[/cyan]\n\n"
        "[dim]Peer format: pubkey@host:port[/dim]"
    ),
)
def channel_open(
    peer: Annotated[
        str | None,
        typer.Argument(help="Peer in [green]pubkey@host:port[/green] format."),
    ] = None,
    capacity: Annotated[
        int | None,
        typer.Option("--capacity", "-c", help="Channel capacity in satoshis."),
    ] = None,
    push_msat: Annotated[
        int,
        typer.Option("--push-msat", help="Millisatoshis to push to the remote side on open."),
    ] = 0,
    asset_id: Annotated[
        str | None,
        typer.Option("--asset-id", help="RGB asset ID to attach (creates a colored channel)."),
    ] = None,
    asset_amount: Annotated[
        int | None,
        typer.Option("--asset-amount", help="Amount of RGB asset to place in the channel."),
    ] = None,
    push_asset_amount: Annotated[
        int | None,
        typer.Option(
            "--push-asset-amount",
            help="RGB asset amount to push to the remote side when opening the channel.",
        ),
    ] = None,
    public: Annotated[
        bool,
        typer.Option(
            "--public/--private",
            help="Announce the channel publicly (default) or keep it private.",
        ),
    ] = True,
    with_anchors: Annotated[
        bool,
        typer.Option(
            "--with-anchors/--without-anchors",
            help="Enable or disable anchor outputs for the channel.",
        ),
    ] = False,
    fee_base_msat: Annotated[
        int | None,
        typer.Option("--fee-base-msat", help="Optional base routing fee for the channel."),
    ] = None,
    fee_proportional_millionths: Annotated[
        int | None,
        typer.Option(
            "--fee-proportional-millionths",
            help="Optional proportional routing fee for the channel.",
        ),
    ] = None,
    temporary_channel_id: Annotated[
        str | None,
        typer.Option("--temporary-channel-id", help="Optional temporary channel ID override."),
    ] = None,
) -> None:
    """Open a Lightning channel to a peer."""
    if (asset_amount is not None or push_asset_amount is not None) and asset_id is None:
        print_error("--asset-amount and --push-asset-amount require --asset-id.")
        raise typer.Exit(1)

    resolved_peer: str
    if peer is not None:
        resolved_peer = peer
    elif is_interactive():
        resolved_peer = typer.prompt("Peer (pubkey@host:port)")
    else:
        print_error("PEER argument is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_capacity: int
    if capacity is not None:
        resolved_capacity = capacity
    elif is_interactive():
        resolved_capacity = typer.prompt("Channel capacity (satoshis)", type=int)
    else:
        print_error("--capacity is required in non-interactive mode.")
        raise typer.Exit(1)

    if is_interactive():
        push_msat = typer.prompt("[OPTIONAL] Push msat to remote side", default=push_msat, type=int)
        if asset_id is None and typer.confirm("Attach an RGB asset?", default=False):
            asset_id = typer.prompt("Asset ID (rgb:...)")
            asset_amount = typer.prompt("Asset amount", type=int)
        public = typer.confirm("Announce channel publicly?", default=True)

    # Parse pubkey@host:port
    if "@" in resolved_peer:
        pubkey, addr = resolved_peer.split("@", 1)
    else:
        pubkey = resolved_peer
        if is_interactive():
            addr = typer.prompt("Peer address (host:port)")
        else:
            print_error("Peer must be in pubkey@host:port format in non-interactive mode.")
            raise typer.Exit(1)

    asyncio.run(
        _channel_open(
            pubkey,
            addr,
            resolved_capacity,
            push_msat,
            asset_id,
            asset_amount,
            push_asset_amount,
            public,
            with_anchors,
            fee_base_msat,
            fee_proportional_millionths,
            temporary_channel_id,
        )
    )


async def _channel_open(
    pubkey: str,
    addr: str,
    capacity: int,
    push_msat: int,
    asset_id: str | None,
    asset_amount: int | None,
    push_asset_amount: int | None,
    public: bool,
    with_anchors: bool,
    fee_base_msat: int | None,
    fee_proportional_millionths: int | None,
    temporary_channel_id: str | None,
) -> None:
    try:
        client = get_client(require_node=True)
        body = OpenChannelRequest(
            peer_pubkey_and_opt_addr=f"{pubkey}@{addr}",
            capacity_sat=capacity,
            push_msat=push_msat,
            asset_id=asset_id,
            asset_amount=asset_amount,
            push_asset_amount=push_asset_amount,
            public=public,
            with_anchors=with_anchors,
            fee_base_msat=fee_base_msat,
            fee_proportional_millionths=fee_proportional_millionths,
            temporary_channel_id=temporary_channel_id,
        )
        resp: OpenChannelResponse = await client.rln.open_channel(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(
                f"Channel opening initiated. Temporary channel ID: {resp.temporary_channel_id}"
            )
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@channel_app.command(
    "close",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Cooperative close:\n"
        "  [cyan]kaleido channel close <channel-id> --peer 03abc...[/cyan]\n\n"
        "  Force close (unilateral, use only if peer is unresponsive):\n"
        "  [cyan]kaleido channel close <channel-id> --peer 03abc... --force[/cyan]\n\n"
        "[dim]Use 'kaleido channel list' to find channel IDs.[/dim]"
    ),
)
def channel_close(
    channel_id: Annotated[
        str | None,
        typer.Argument(help="Channel ID to close (from 'kaleido channel list')."),
    ] = None,
    peer_pubkey: Annotated[
        str | None,
        typer.Option("--peer", help="Pubkey of the channel peer."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Force (unilateral) close. Use only if peer is offline."),
    ] = False,
) -> None:
    """Close a Lightning channel."""
    resolved_channel_id: str
    if channel_id is not None:
        resolved_channel_id = channel_id
    elif is_interactive():
        resolved_channel_id = typer.prompt("Channel ID (from 'kaleido channel list')")
    else:
        print_error("CHANNEL_ID argument is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_peer_pubkey: str
    if peer_pubkey is not None:
        resolved_peer_pubkey = peer_pubkey
    elif is_interactive():
        resolved_peer_pubkey = typer.prompt("Peer pubkey")
    else:
        print_error("--peer is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(_channel_close(resolved_channel_id, resolved_peer_pubkey, force))


async def _channel_close(channel_id: str, peer_pubkey: str, force: bool) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.close_channel(
            CloseChannelRequest(
                channel_id=channel_id,
                peer_pubkey=peer_pubkey,
                force=force,
            )
        )
        print_success("Channel close initiated.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# LSP Order Commands
# ---------------------------------------------------------------------------


@order_app.command(
    "create",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Create a basic channel order:\n"
        "  [cyan]kaleido channel order create --lsp-balance 1000000 --client-balance 500000[/cyan]\n\n"
        "  RGB colored channel order:\n"
        "  [cyan]kaleido channel order create --lsp-balance 1000000 --client-balance 500000 \\'\n"
        "      --asset-id rgb:xyz... --lsp-asset-amount 5000 --client-asset-amount 2000[/cyan]\n\n"
        "  With custom confirmations and refund address:\n"
        "  [cyan]kaleido channel order create --lsp-balance 1000000 --client-balance 500000 \\'\n"
        "      --confirmations 3 --refund-address bc1q...[/cyan]"
    ),
)
def channel_order_create(
    client_pubkey: Annotated[
        str | None,
        typer.Argument(help="Client Lightning node public key. Defaults to local node pubkey."),
    ] = None,
    lsp_balance_sat: Annotated[
        int | None,
        typer.Option("--lsp-balance", help="LSP's balance in the channel (satoshis)."),
    ] = None,
    client_balance_sat: Annotated[
        int | None,
        typer.Option("--client-balance", help="Client's balance in the channel (satoshis)."),
    ] = None,
    required_channel_confirmations: Annotated[
        int,
        typer.Option(
            "--confirmations",
            help="Required confirmations before channel is considered open.",
        ),
    ] = 6,
    funding_confirms_within_blocks: Annotated[
        int,
        typer.Option(
            "--funding-within",
            help="Number of blocks within which funding must confirm.",
        ),
    ] = 144,
    channel_expiry_blocks: Annotated[
        int,
        typer.Option("--expiry-blocks", help="Channel expiry in blocks (must be at least 1)."),
    ] = 1,
    refund_onchain_address: Annotated[
        str | None,
        typer.Option(
            "--refund-address",
            help="Bitcoin address for refunds. Defaults to a local node address.",
        ),
    ] = None,
    announce_channel: Annotated[
        bool,
        typer.Option("--announce/--private", help="Announce channel publicly."),
    ] = True,
    asset_id: Annotated[
        str | None,
        typer.Option("--asset-id", help="RGB asset ID for colored channel."),
    ] = None,
    lsp_asset_amount: Annotated[
        int | None,
        typer.Option(
            "--lsp-asset-amount", help="LSP's RGB asset amount. Required with --asset-id."
        ),
    ] = None,
    client_asset_amount: Annotated[
        int | None,
        typer.Option("--client-asset-amount", help="Client's RGB asset amount."),
    ] = None,
    email: Annotated[str | None, typer.Option("--email", help="Contact email.")] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Accept an automatically fetched RFQ price."),
    ] = False,
) -> None:
    """Create an LSP channel order."""
    asyncio.run(
        _channel_order_create_flow(
            client_pubkey=client_pubkey,
            lsp_balance_sat=lsp_balance_sat,
            client_balance_sat=client_balance_sat,
            required_channel_confirmations=required_channel_confirmations,
            funding_confirms_within_blocks=funding_confirms_within_blocks,
            channel_expiry_blocks=channel_expiry_blocks,
            refund_onchain_address=refund_onchain_address,
            announce_channel=announce_channel,
            asset_id=asset_id,
            lsp_asset_amount=lsp_asset_amount,
            client_asset_amount=client_asset_amount,
            email=email,
            yes=yes,
        )
    )


async def _channel_order_create_flow(
    *,
    client_pubkey: str | None,
    lsp_balance_sat: int | None,
    client_balance_sat: int | None,
    required_channel_confirmations: int,
    funding_confirms_within_blocks: int,
    channel_expiry_blocks: int,
    refund_onchain_address: str | None,
    announce_channel: bool,
    asset_id: str | None,
    lsp_asset_amount: int | None,
    client_asset_amount: int | None,
    email: str | None,
    yes: bool,
) -> None:
    try:
        client = get_client(
            require_node=True,
            timeout=CHANNEL_ORDER_HTTP_TIMEOUT,
            max_retries=0,
        )
        node_info = await _timed_step("Fetching local node info", client.rln.get_node_info())
        lsp_info = await _timed_step("Fetching LSP info", client.maker.get_lsp_info())
        params = _resolve_channel_order_params(
            client_pubkey=client_pubkey,
            default_client_pubkey=node_info.pubkey,
            lsp_info=lsp_info,
            lsp_balance_sat=lsp_balance_sat,
            client_balance_sat=client_balance_sat,
            required_channel_confirmations=required_channel_confirmations,
            funding_confirms_within_blocks=funding_confirms_within_blocks,
            channel_expiry_blocks=channel_expiry_blocks,
            refund_onchain_address=refund_onchain_address,
            announce_channel=announce_channel,
            asset_id=asset_id,
            lsp_asset_amount=lsp_asset_amount,
            client_asset_amount=client_asset_amount,
            email=email,
        )
        await _autofill_refund_address(client, params)
        await _attach_client_asset_quote(client, params, yes=yes)
        await _ensure_lsp_peer_connected(client, lsp_info)
        resp: ChannelOrderResponse = await _timed_step(
            "Submitting LSP channel order",
            _create_channel_order(client, params),
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"LSP order created: {resp.order_id}")
            output_model(resp, title="Channel Order")
            access_token_args = _access_token_args(resp.access_token)
            print_info(
                "Inspect the order with: "
                f"kaleido channel order get {resp.order_id}{access_token_args}"
            )
            if _can_pay_channel_order(resp):
                print_info(
                    "Pay from local wallet funds with: "
                    f"kaleido channel order pay {resp.order_id}{access_token_args}"
                )
    except typer.Exit:
        raise
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@order_app.command(
    "get",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Get order status:\n"
        "  [cyan]kaleido channel order get <order-id> --access-token <token>[/cyan]"
    ),
)
def channel_order_get(
    order_id: Annotated[str | None, typer.Argument(help="LSP order ID.")] = None,
    access_token: Annotated[
        str | None,
        typer.Option("--access-token", help="Optional access token returned for the order."),
    ] = None,
) -> None:
    """Get the status and details of an LSP channel order."""
    resolved_order_id = resolve_required_text(order_id, "LSP order ID", "ORDER_ID argument")
    resolved_access_token = _resolve_optional_access_token(access_token)

    asyncio.run(_channel_order_get(resolved_order_id, resolved_access_token))


async def _channel_order_get(order_id: str, access_token: str) -> None:
    try:
        client = get_client()
        resp: ChannelOrderResponse = await _get_channel_order(client, order_id, access_token)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title=f"Order {order_id}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@order_app.command(
    "pay",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Pay an order from local wallet funds:\n"
        "  [cyan]kaleido channel order pay <order-id> --access-token <token>[/cyan]\n\n"
        "  Non-interactive payment:\n"
        "  [cyan]kaleido channel order pay <order-id> --access-token <token> --yes[/cyan]"
    ),
)
def channel_order_pay(
    order_id: Annotated[str | None, typer.Argument(help="LSP order ID.")] = None,
    access_token: Annotated[
        str | None,
        typer.Option("--access-token", help="Optional access token returned for the order."),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Pay the order invoice without confirmation."),
    ] = False,
) -> None:
    """Pay an LSP channel order with local wallet funds."""
    resolved_order_id = resolve_required_text(order_id, "LSP order ID", "ORDER_ID argument")
    resolved_access_token = _resolve_optional_access_token(access_token)
    asyncio.run(_channel_order_pay(resolved_order_id, resolved_access_token, yes=yes))


async def _channel_order_pay(order_id: str, access_token: str, *, yes: bool) -> None:
    try:
        client = get_client(
            require_node=True,
            timeout=CHANNEL_ORDER_HTTP_TIMEOUT,
            max_retries=0,
        )
        order = await _timed_step(
            f"Fetching LSP order {order_id}",
            _get_channel_order(client, order_id, access_token),
        )
        if is_json_mode():
            if not yes:
                print_error("--yes is required in JSON mode to pay the order.")
                raise typer.Exit(1)
        else:
            output_model(_channel_wallet_payment_summary(order), title="Wallet Payment")
        if not _can_pay_channel_order(order):
            if is_json_mode():
                print_json(order.model_dump())
            else:
                print_info(
                    "This order is not awaiting a wallet payment. Current payment state: "
                    f"{order.payment.bolt11.state}"
                )
                output_model(order, title=f"Order {order_id}")
            return
        if is_interactive() and not yes:
            confirmed = typer.confirm(
                (
                    "Pay this order from local wallet funds "
                    f"({order.payment.bolt11.order_total_sat} sat + "
                    f"{order.payment.bolt11.fee_total_sat} sat fee)?"
                ),
                default=False,
            )
            if not confirmed:
                print_error("Channel order payment cancelled.")
                raise typer.Exit(0)
        elif not yes:
            print_error("--yes is required in non-interactive mode to pay the order.")
            raise typer.Exit(1)

        payment_resp: SendPaymentResponse = await _timed_step(
            "Paying order invoice from local wallet funds",
            client.rln.send_payment(SendPaymentRequest(invoice=order.payment.bolt11.invoice)),
        )
        refreshed_order = await _timed_step(
            f"Refreshing LSP order {order_id}",
            _get_channel_order(client, order_id, access_token),
        )
        if is_json_mode():
            print_json(
                {
                    "payment": payment_resp.model_dump(),
                    "order": refreshed_order.model_dump(),
                }
            )
        else:
            print_success(f"Wallet payment submitted for order {order_id}")
            output_model(payment_resp, title="Payment Result")
            output_model(refreshed_order, title=f"Order {order_id}")
    except typer.Exit:
        raise
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@order_app.command(
    "decide",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Accept an order:\n"
        "  [cyan]kaleido channel order decide <order-id> --access-token <token> --accept[/cyan]\n\n"
        "  Reject an order:\n"
        "  [cyan]kaleido channel order decide <order-id> --access-token <token> --reject[/cyan]"
    ),
)
def channel_order_decide(
    order_id: Annotated[str | None, typer.Argument(help="LSP order ID.")] = None,
    accept: Annotated[bool, typer.Option("--accept", help="Accept the order.")] = False,
    reject: Annotated[bool, typer.Option("--reject", help="Reject the order.")] = False,
    access_token: Annotated[
        str,
        typer.Option("--access-token", help="Optional access token returned for the order."),
    ] = "",
) -> None:
    """Submit a rate decision for an LSP channel order."""
    resolved_order_id: str
    if order_id is not None:
        resolved_order_id = order_id
    elif is_interactive():
        resolved_order_id = typer.prompt("LSP order ID")
    else:
        print_error("ORDER_ID argument is required in non-interactive mode.")
        raise typer.Exit(1)

    if is_interactive() and not accept and not reject:
        accept = typer.confirm("Accept this order?", default=False)
        reject = not accept
    elif accept == reject:
        print_error("Must specify exactly one of --accept or --reject")
        raise typer.Exit(1)

    resolved_access_token = _resolve_optional_access_token(access_token)

    asyncio.run(_channel_order_decide(resolved_order_id, accept, resolved_access_token))


async def _channel_order_decide(order_id: str, accept: bool, access_token: str) -> None:
    try:
        client = get_client()
        body = RateDecisionRequest(
            order_id=order_id,
            access_token=access_token,
            accept_new_rate=accept,
        )
        resp: RateDecisionResponse = await client.maker.submit_lsp_rate_decision(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            action = "accepted" if accept else "rejected"
            print_success(f"Order {order_id} {action}")
            output_model(resp, title="Rate Decision Response")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@order_app.command(
    "estimate-fees",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Estimate fees for a channel:\n"
        "  [cyan]kaleido channel order estimate-fees --lsp-balance 1000000 --client-balance 500000[/cyan]\n\n"
        "  Estimate fees for an RGB-backed channel:\n"
        "  [cyan]kaleido channel order estimate-fees --lsp-balance 1000000 --client-balance 500000 \\\n"
        "      --asset-id rgb:xyz... --lsp-asset-amount 5000 --client-asset-amount 2000[/cyan]"
    ),
)
def channel_estimate_fees(
    lsp_balance_sat: Annotated[
        int | None,
        typer.Option("--lsp-balance", help="LSP's balance in the channel (satoshis)."),
    ] = None,
    client_balance_sat: Annotated[
        int | None,
        typer.Option("--client-balance", help="Client's balance in the channel (satoshis)."),
    ] = None,
    asset_id: Annotated[
        str | None,
        typer.Option("--asset-id", help="RGB asset ID for colored channel."),
    ] = None,
    lsp_asset_amount: Annotated[
        int | None,
        typer.Option(
            "--lsp-asset-amount", help="LSP's RGB asset amount. Required with --asset-id."
        ),
    ] = None,
    client_asset_amount: Annotated[
        int | None,
        typer.Option("--client-asset-amount", help="Client's RGB asset amount."),
    ] = None,
    channel_expiry_blocks: Annotated[
        int,
        typer.Option("--expiry-blocks", help="Channel expiry in blocks (must be at least 1)."),
    ] = 1,
    token: Annotated[str | None, typer.Option("--token", help="Authentication token.")] = None,
    rfq_id: Annotated[
        str | None,
        typer.Option("--rfq-id", help="Request for quote ID."),
    ] = None,
) -> None:
    """Estimate fees for opening an LSP channel."""
    params = _resolve_channel_fee_estimate_params(
        lsp_balance_sat=lsp_balance_sat,
        client_balance_sat=client_balance_sat,
        channel_expiry_blocks=channel_expiry_blocks,
        token=token,
        asset_id=asset_id,
        lsp_asset_amount=lsp_asset_amount,
        client_asset_amount=client_asset_amount,
        rfq_id=rfq_id,
    )

    asyncio.run(_channel_estimate_fees_flow(params))


async def _channel_estimate_fees_flow(params) -> None:
    try:
        client = get_client()
        resp = await _estimate_channel_order_fees(client, params)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            _print_channel_order_fees(resp, title="Estimated Fees")
    except typer.Exit:
        raise
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@lsp_app.command(
    "info",
    epilog="  [cyan]kaleido channel lsp info[/cyan]   Show LSP capabilities and options.",
)
def channel_lsp_info() -> None:
    """Show LSP information and available channel options."""
    asyncio.run(_channel_lsp_info())


async def _channel_lsp_info() -> None:
    try:
        client = get_client()
        resp: LspInfoResponse = await client.maker.get_lsp_info()
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            _print_lsp_info(resp)
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@lsp_app.command(
    "network-info",
    epilog="  [cyan]kaleido channel lsp network-info[/cyan]   Show LSP network/node information.",
)
def channel_lsp_network_info() -> None:
    """Show LSP Lightning network information."""
    asyncio.run(_channel_lsp_network_info())


async def _channel_lsp_network_info() -> None:
    try:
        client = get_client()
        resp: NetworkInfoResponse = await client.maker.get_lsp_network_info()
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title="LSP Network Info")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
