"""Lightning channel commands — list, open, close, and LSP orders."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk import (
    ChannelFees,
    ChannelOrderResponse,
    CreateOrderRequest,
    OrderRequest,
    RateDecisionRequest,
    RateDecisionResponse,
)
from kaleido_sdk.rln import (
    CloseChannelRequest,
    ListChannelsResponse,
    OpenChannelRequest,
    OpenChannelResponse,
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

channel_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Manage Lightning channels — list, open, close, and place LSP orders.",
)


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
        rows = [
            [
                c.channel_id[:16] + "…" if c.channel_id else "-",
                c.peer_pubkey[:16] + "…" if c.peer_pubkey else "-",
                c.capacity_sat,
                c.outbound_balance_msat,
                c.inbound_balance_msat,
                "yes" if c.is_usable else "no",
                "yes" if c.ready else "no",
            ]
            for c in (resp.channels or [])
        ]
        print_table(
            "Channels",
            [
                "Channel ID",
                "Peer",
                "Capacity (sat)",
                "Outbound (msat)",
                "Inbound (msat)",
                "Usable",
                "Ready",
            ],
            rows,
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


@channel_app.command(
    "order-create",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Create a basic channel order:\n"
        "  [cyan]kaleido channel order-create 03abc... --lsp-balance 1000000 --client-balance 500000[/cyan]\n\n"
        "  RGB colored channel order:\n"
        "  [cyan]kaleido channel order-create 03abc... --lsp-balance 1000000 --client-balance 500000 \\'\n"
        "      --asset-id rgb:xyz... --lsp-asset-amount 5000 --client-asset-amount 2000[/cyan]\n\n"
        "  With custom confirmations and refund address:\n"
        "  [cyan]kaleido channel order-create 03abc... --lsp-balance 1000000 --client-balance 500000 \\'\n"
        "      --confirmations 3 --refund-address bc1q...[/cyan]"
    ),
)
def channel_order_create(
    client_pubkey: Annotated[
        str | None,
        typer.Argument(help="Client Lightning node public key."),
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
    token: Annotated[str | None, typer.Option("--token", help="Authentication token.")] = None,
    refund_onchain_address: Annotated[
        str | None,
        typer.Option("--refund-address", help="Bitcoin address for refunds."),
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
        typer.Option("--lsp-asset-amount", help="LSP's RGB asset amount."),
    ] = None,
    client_asset_amount: Annotated[
        int | None,
        typer.Option("--client-asset-amount", help="Client's RGB asset amount."),
    ] = None,
    rfq_id: Annotated[
        str | None,
        typer.Option("--rfq-id", help="Request for quote ID."),
    ] = None,
    email: Annotated[str | None, typer.Option("--email", help="Contact email.")] = None,
) -> None:
    """Create an LSP channel order."""
    if (lsp_asset_amount is not None or client_asset_amount is not None) and asset_id is None:
        print_error("--lsp-asset-amount and --client-asset-amount require --asset-id.")
        raise typer.Exit(1)

    resolved_client_pubkey: str
    if client_pubkey is not None:
        resolved_client_pubkey = client_pubkey
    elif is_interactive():
        resolved_client_pubkey = typer.prompt("Client Lightning node public key")
    else:
        print_error("CLIENT_PUBKEY argument is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_lsp_balance_sat: int
    if lsp_balance_sat is not None:
        resolved_lsp_balance_sat = lsp_balance_sat
    elif is_interactive():
        resolved_lsp_balance_sat = typer.prompt("LSP balance in channel (satoshis)", type=int)
    else:
        print_error("--lsp-balance is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_client_balance_sat: int
    if client_balance_sat is not None:
        resolved_client_balance_sat = client_balance_sat
    elif is_interactive():
        resolved_client_balance_sat = typer.prompt("Client balance in channel (satoshis)", type=int)
    else:
        print_error("--client-balance is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(
        _channel_order_create(
            client_pubkey=resolved_client_pubkey,
            lsp_balance_sat=resolved_lsp_balance_sat,
            client_balance_sat=resolved_client_balance_sat,
            required_channel_confirmations=required_channel_confirmations,
            funding_confirms_within_blocks=funding_confirms_within_blocks,
            channel_expiry_blocks=channel_expiry_blocks,
            token=token,
            refund_onchain_address=refund_onchain_address,
            announce_channel=announce_channel,
            asset_id=asset_id,
            lsp_asset_amount=lsp_asset_amount,
            client_asset_amount=client_asset_amount,
            rfq_id=rfq_id,
            email=email,
        )
    )


async def _channel_order_create(
    client_pubkey: str,
    lsp_balance_sat: int,
    client_balance_sat: int,
    required_channel_confirmations: int,
    funding_confirms_within_blocks: int,
    channel_expiry_blocks: int,
    token: str | None,
    refund_onchain_address: str | None,
    announce_channel: bool,
    asset_id: str | None,
    lsp_asset_amount: int | None,
    client_asset_amount: int | None,
    rfq_id: str | None,
    email: str | None,
) -> None:
    try:
        client = get_client()
        body = CreateOrderRequest(
            client_pubkey=client_pubkey,
            lsp_balance_sat=lsp_balance_sat,
            client_balance_sat=client_balance_sat,
            required_channel_confirmations=required_channel_confirmations,
            funding_confirms_within_blocks=funding_confirms_within_blocks,
            channel_expiry_blocks=channel_expiry_blocks,
            token=token,
            refund_onchain_address=refund_onchain_address,
            announce_channel=announce_channel,
            asset_id=asset_id,
            lsp_asset_amount=lsp_asset_amount,
            client_asset_amount=client_asset_amount,
            rfq_id=rfq_id,
            email=email,
        )
        resp: ChannelOrderResponse = await client.maker.create_lsp_order(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"LSP order created: {resp.order_id}")
            output_model(resp, title="Channel Order")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@channel_app.command(
    "order-get",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Get order status:\n"
        "  [cyan]kaleido channel order-get <order-id>[/cyan]"
    ),
)
def channel_order_get(
    order_id: Annotated[str, typer.Argument(help="LSP order ID.")],
    access_token: Annotated[
        str,
        typer.Option("--access-token", help="Optional access token returned for the order."),
    ] = "",
) -> None:
    """Get the status and details of an LSP channel order."""
    asyncio.run(_channel_order_get(order_id, access_token))


async def _channel_order_get(order_id: str, access_token: str) -> None:
    try:
        client = get_client()
        resp: ChannelOrderResponse = await client.maker.get_lsp_order(
            OrderRequest(order_id=order_id, access_token=access_token)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title=f"Order {order_id}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@channel_app.command(
    "order-decide",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Accept an order:\n"
        "  [cyan]kaleido channel order-decide <order-id> --accept[/cyan]\n\n"
        "  Reject an order:\n"
        "  [cyan]kaleido channel order-decide <order-id> --reject[/cyan]"
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

    asyncio.run(_channel_order_decide(resolved_order_id, accept, access_token))


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


@channel_app.command(
    "estimate-fees",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Estimate fees for a channel:\n"
        "  [cyan]kaleido channel estimate-fees 03abc... --lsp-balance 1000000 --client-balance 500000[/cyan]"
    ),
)
def channel_estimate_fees(
    client_pubkey: Annotated[
        str | None,
        typer.Argument(help="Client Lightning node public key."),
    ] = None,
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
        typer.Option("--lsp-asset-amount", help="LSP's RGB asset amount."),
    ] = None,
    client_asset_amount: Annotated[
        int | None,
        typer.Option("--client-asset-amount", help="Client's RGB asset amount."),
    ] = None,
    required_channel_confirmations: Annotated[
        int,
        typer.Option("--confirmations", help="Required confirmations before channel is considered open."),
    ] = 6,
    funding_confirms_within_blocks: Annotated[
        int,
        typer.Option("--funding-within", help="Number of blocks within which funding must confirm."),
    ] = 144,
    channel_expiry_blocks: Annotated[
        int,
        typer.Option("--expiry-blocks", help="Channel expiry in blocks (must be at least 1)."),
    ] = 1,
    token: Annotated[str | None, typer.Option("--token", help="Authentication token.")] = None,
    refund_onchain_address: Annotated[
        str | None,
        typer.Option("--refund-address", help="Bitcoin address for refunds."),
    ] = None,
    announce_channel: Annotated[
        bool,
        typer.Option("--announce/--private", help="Announce channel publicly."),
    ] = True,
    rfq_id: Annotated[
        str | None,
        typer.Option("--rfq-id", help="Request for quote ID."),
    ] = None,
    email: Annotated[str | None, typer.Option("--email", help="Contact email.")] = None,
) -> None:
    """Estimate fees for opening an LSP channel."""
    if (lsp_asset_amount is not None or client_asset_amount is not None) and asset_id is None:
        print_error("--lsp-asset-amount and --client-asset-amount require --asset-id.")
        raise typer.Exit(1)

    resolved_client_pubkey: str
    if client_pubkey is not None:
        resolved_client_pubkey = client_pubkey
    elif is_interactive():
        resolved_client_pubkey = typer.prompt("Client Lightning node public key")
    else:
        print_error("CLIENT_PUBKEY argument is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_lsp_balance_sat: int
    if lsp_balance_sat is not None:
        resolved_lsp_balance_sat = lsp_balance_sat
    elif is_interactive():
        resolved_lsp_balance_sat = typer.prompt("LSP balance in channel (satoshis)", type=int)
    else:
        print_error("--lsp-balance is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_client_balance_sat: int
    if client_balance_sat is not None:
        resolved_client_balance_sat = client_balance_sat
    elif is_interactive():
        resolved_client_balance_sat = typer.prompt("Client balance in channel (satoshis)", type=int)
    else:
        print_error("--client-balance is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(
        _channel_estimate_fees(
            resolved_client_pubkey,
            resolved_lsp_balance_sat,
            resolved_client_balance_sat,
            asset_id,
            lsp_asset_amount,
            client_asset_amount,
            required_channel_confirmations,
            funding_confirms_within_blocks,
            channel_expiry_blocks,
            token,
            refund_onchain_address,
            announce_channel,
            rfq_id,
            email,
        )
    )


async def _channel_estimate_fees(
    client_pubkey: str,
    lsp_balance_sat: int,
    client_balance_sat: int,
    asset_id: str | None,
    lsp_asset_amount: int | None,
    client_asset_amount: int | None,
    required_channel_confirmations: int,
    funding_confirms_within_blocks: int,
    channel_expiry_blocks: int,
    token: str | None,
    refund_onchain_address: str | None,
    announce_channel: bool,
    rfq_id: str | None,
    email: str | None,
) -> None:
    try:
        client = get_client()
        body = CreateOrderRequest(
            client_pubkey=client_pubkey,
            lsp_balance_sat=lsp_balance_sat,
            client_balance_sat=client_balance_sat,
            required_channel_confirmations=required_channel_confirmations,
            funding_confirms_within_blocks=funding_confirms_within_blocks,
            channel_expiry_blocks=channel_expiry_blocks,
            token=token,
            refund_onchain_address=refund_onchain_address,
            asset_id=asset_id,
            lsp_asset_amount=lsp_asset_amount,
            client_asset_amount=client_asset_amount,
            announce_channel=announce_channel,
            rfq_id=rfq_id,
            email=email,
        )
        resp: ChannelFees = await client.maker.estimate_lsp_fees(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title="Estimated Fees")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
