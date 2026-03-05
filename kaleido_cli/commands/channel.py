"""Lightning channel commands — list, open, close, and LSP orders."""

from __future__ import annotations

import asyncio
from typing import Annotated, Optional

import typer

from ..app import get_client
from ..output import (
    is_json_mode,
    output_model,
    print_error,
    print_json,
    print_success,
    print_table,
)
from kaleidoswap_sdk import (
    ChannelFees,
    ChannelOrderResponse,
    CreateOrderRequest,
    GetOrderRequest,
    RateDecisionRequest,
    RateDecisionResponse,
)
from kaleidoswap_sdk.rln import (
    CloseChannelRequest,
    ListChannelsResponse,
    OpenChannelRequest,
    OpenChannelResponse,
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
        str, typer.Argument(help="Peer in [green]pubkey@host:port[/green] format.")
    ],
    capacity: Annotated[
        int, typer.Option("--capacity", "-c", help="Channel capacity in satoshis.")
    ],
    push_msat: Annotated[
        Optional[int],
        typer.Option(
            "--push-msat", help="Millisatoshis to push to the remote side on open."
        ),
    ] = None,
    asset_id: Annotated[
        Optional[str],
        typer.Option(
            "--asset-id", help="RGB asset ID to attach (creates a colored channel)."
        ),
    ] = None,
    asset_amount: Annotated[
        Optional[int],
        typer.Option(
            "--asset-amount", help="Amount of RGB asset to place in the channel."
        ),
    ] = None,
    public: Annotated[
        bool,
        typer.Option(
            "--public/--private",
            help="Announce the channel publicly (default) or keep it private.",
        ),
    ] = True,
) -> None:
    """Open a Lightning channel to a peer."""
    # Parse pubkey@host:port
    if "@" in peer:
        pubkey, addr = peer.split("@", 1)
    else:
        pubkey = peer
        addr = typer.prompt("Peer address (host:port)")

    asyncio.run(
        _channel_open(pubkey, addr, capacity, push_msat, asset_id, asset_amount, public)
    )


async def _channel_open(
    pubkey: str,
    addr: str,
    capacity: int,
    push_msat: int | None,
    asset_id: str | None,
    asset_amount: int | None,
    public: bool,
) -> None:
    try:
        client = get_client(require_node=True)
        body = OpenChannelRequest(
            peer_pubkey_and_opt_addr=f"{pubkey}@{addr}",
            capacity_sat=capacity,
            push_msat=push_msat,
            asset_id=asset_id,
            asset_amount=asset_amount,
            public=public,
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
        str, typer.Argument(help="Channel ID to close (from 'kaleido channel list').")
    ],
    peer_pubkey: Annotated[
        str, typer.Option("--peer", help="Pubkey of the channel peer.")
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force", help="Force (unilateral) close. Use only if peer is offline."
        ),
    ] = False,
) -> None:
    """Close a Lightning channel."""
    asyncio.run(_channel_close(channel_id, peer_pubkey, force))


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
        str, typer.Argument(help="Client Lightning node public key.")
    ],
    lsp_balance_sat: Annotated[
        int,
        typer.Option("--lsp-balance", help="LSP's balance in the channel (satoshis)."),
    ],
    client_balance_sat: Annotated[
        int,
        typer.Option(
            "--client-balance", help="Client's balance in the channel (satoshis)."
        ),
    ],
    required_channel_confirmations: Annotated[
        Optional[int],
        typer.Option(
            "--confirmations",
            help="Required confirmations before channel is considered open.",
        ),
    ] = None,
    funding_confirms_within_blocks: Annotated[
        Optional[int],
        typer.Option(
            "--funding-within",
            help="Number of blocks within which funding must confirm.",
        ),
    ] = None,
    channel_expiry_blocks: Annotated[
        Optional[int],
        typer.Option("--expiry-blocks", help="Channel expiry in blocks."),
    ] = None,
    token: Annotated[
        Optional[str], typer.Option("--token", help="Authentication token.")
    ] = None,
    refund_onchain_address: Annotated[
        Optional[str],
        typer.Option("--refund-address", help="Bitcoin address for refunds."),
    ] = None,
    announce_channel: Annotated[
        bool,
        typer.Option("--announce/--private", help="Announce channel publicly."),
    ] = True,
    asset_id: Annotated[
        Optional[str],
        typer.Option("--asset-id", help="RGB asset ID for colored channel."),
    ] = None,
    lsp_asset_amount: Annotated[
        Optional[int],
        typer.Option("--lsp-asset-amount", help="LSP's RGB asset amount."),
    ] = None,
    client_asset_amount: Annotated[
        Optional[int],
        typer.Option("--client-asset-amount", help="Client's RGB asset amount."),
    ] = None,
    rfq_id: Annotated[
        Optional[str],
        typer.Option("--rfq-id", help="Request for quote ID."),
    ] = None,
    email: Annotated[
        Optional[str], typer.Option("--email", help="Contact email.")
    ] = None,
) -> None:
    """Create an LSP channel order."""
    asyncio.run(
        _channel_order_create(
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
    )


async def _channel_order_create(
    client_pubkey: str,
    lsp_balance_sat: int,
    client_balance_sat: int,
    required_channel_confirmations: int | None,
    funding_confirms_within_blocks: int | None,
    channel_expiry_blocks: int | None,
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
) -> None:
    """Get the status and details of an LSP channel order."""
    asyncio.run(_channel_order_get(order_id))


async def _channel_order_get(order_id: str) -> None:
    try:
        client = get_client()
        resp: ChannelOrderResponse = await client.maker.get_lsp_order(
            GetOrderRequest(order_id=order_id)
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
    order_id: Annotated[str, typer.Argument(help="LSP order ID.")],
    accept: Annotated[bool, typer.Option("--accept", help="Accept the order.")] = False,
    reject: Annotated[bool, typer.Option("--reject", help="Reject the order.")] = False,
) -> None:
    """Submit a rate decision for an LSP channel order."""
    if accept == reject:
        print_error("Must specify exactly one of --accept or --reject")
        raise typer.Exit(1)

    asyncio.run(_channel_order_decide(order_id, accept))


async def _channel_order_decide(order_id: str, accept: bool) -> None:
    try:
        client = get_client()
        body = RateDecisionRequest(order_id=order_id, accept=accept)
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
        str, typer.Argument(help="Client Lightning node public key.")
    ],
    lsp_balance_sat: Annotated[
        int,
        typer.Option("--lsp-balance", help="LSP's balance in the channel (satoshis)."),
    ],
    client_balance_sat: Annotated[
        int,
        typer.Option(
            "--client-balance", help="Client's balance in the channel (satoshis)."
        ),
    ],
    asset_id: Annotated[
        Optional[str],
        typer.Option("--asset-id", help="RGB asset ID for colored channel."),
    ] = None,
    lsp_asset_amount: Annotated[
        Optional[int],
        typer.Option("--lsp-asset-amount", help="LSP's RGB asset amount."),
    ] = None,
    client_asset_amount: Annotated[
        Optional[int],
        typer.Option("--client-asset-amount", help="Client's RGB asset amount."),
    ] = None,
) -> None:
    """Estimate fees for opening an LSP channel."""
    asyncio.run(
        _channel_estimate_fees(
            client_pubkey,
            lsp_balance_sat,
            client_balance_sat,
            asset_id,
            lsp_asset_amount,
            client_asset_amount,
        )
    )


async def _channel_estimate_fees(
    client_pubkey: str,
    lsp_balance_sat: int,
    client_balance_sat: int,
    asset_id: str | None,
    lsp_asset_amount: int | None,
    client_asset_amount: int | None,
) -> None:
    try:
        client = get_client()
        body = CreateOrderRequest(
            client_pubkey=client_pubkey,
            lsp_balance_sat=lsp_balance_sat,
            client_balance_sat=client_balance_sat,
            asset_id=asset_id,
            lsp_asset_amount=lsp_asset_amount,
            client_asset_amount=client_asset_amount,
            announce_channel=True,
        )
        resp: ChannelFees = await client.maker.estimate_lsp_fees(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title="Estimated Fees")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
