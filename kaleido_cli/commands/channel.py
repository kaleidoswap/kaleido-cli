"""Lightning channel commands — list, open, close, and LSP orders."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any

import typer
from kaleido_sdk import (
    ChannelFees,
    ChannelOrderResponse,
    CreateOrderRequest,
    LspInfoResponse,
    NetworkInfoResponse,
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
    output_collection,
    output_model,
    print_error,
    print_json,
    print_panel,
    print_success,
)
from kaleido_cli.utils.prompts import resolve_required_text

channel_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Manage Lightning channels — list, open, close, and place LSP orders.",
)
order_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="LSP-backed channel order flow: create, inspect, decide, and estimate fees.",
)
lsp_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Inspect Kaleidoswap LSP metadata and network details.",
)

channel_app.add_typer(order_app, name="order")
channel_app.add_typer(lsp_app, name="lsp")

CHANNEL_LSP_CREATE_ORDER_PATH = "/api/v1/lsps1/create_order"
CHANNEL_LSP_GET_ORDER_PATH = "/api/v1/lsps1/get_order"


@dataclass(slots=True)
class ChannelOrderParams:
    client_pubkey: str
    lsp_balance_sat: int
    client_balance_sat: int
    required_channel_confirmations: int
    funding_confirms_within_blocks: int
    channel_expiry_blocks: int
    token: str | None
    refund_onchain_address: str | None
    announce_channel: bool
    asset_id: str | None
    lsp_asset_amount: int | None
    client_asset_amount: int | None
    rfq_id: str | None
    email: str | None


def _parse_iso_datetime(value: str) -> datetime | None:
    candidate = value
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _normalize_channel_lsp_datetimes(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {k: _normalize_channel_lsp_datetimes(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_channel_lsp_datetimes(item, key) for item in value]
    if key is not None and key.endswith("_at") and isinstance(value, str):
        parsed = _parse_iso_datetime(value)
        if parsed is not None and parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc).isoformat()
    return value


async def _post_channel_lsp(client: Any, path: str, body: Any) -> dict[str, Any]:
    data = await client.maker._http.maker_post(path, data=body)
    if not isinstance(data, dict):
        raise TypeError(f"Unexpected channel LSP response type for {path}: {type(data).__name__}")
    return data


def _normalize_channel_order_response(data: dict[str, Any]) -> ChannelOrderResponse:
    return ChannelOrderResponse.model_validate(_normalize_channel_lsp_datetimes(data))


async def _submit_channel_order(client: Any, body: CreateOrderRequest) -> ChannelOrderResponse:
    data = await _post_channel_lsp(client, CHANNEL_LSP_CREATE_ORDER_PATH, body)
    return _normalize_channel_order_response(data)


async def _fetch_channel_order(client: Any, body: OrderRequest) -> ChannelOrderResponse:
    data = await _post_channel_lsp(client, CHANNEL_LSP_GET_ORDER_PATH, body)
    return _normalize_channel_order_response(data)


def _prompt_optional_text(prompt: str) -> str | None:
    raw = typer.prompt(prompt, default="")
    return raw.strip() or None


def _prompt_optional_int(prompt: str) -> int | None:
    raw = typer.prompt(prompt, default="")
    if raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError:
        print_error(f"{prompt} must be an integer.")
        raise typer.Exit(1)


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_channel_order_params(
    *,
    client_pubkey: str | None,
    lsp_balance_sat: int | None,
    client_balance_sat: int | None,
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
) -> ChannelOrderParams:
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

    if is_interactive():
        required_channel_confirmations = typer.prompt(
            "Required channel confirmations",
            type=int,
            default=required_channel_confirmations,
        )
        funding_confirms_within_blocks = typer.prompt(
            "Funding confirms within blocks",
            type=int,
            default=funding_confirms_within_blocks,
        )
        channel_expiry_blocks = typer.prompt(
            "Channel expiry blocks",
            type=int,
            default=channel_expiry_blocks,
        )

    resolved_token = _normalize_optional_text(token)
    resolved_refund_onchain_address = _normalize_optional_text(refund_onchain_address)
    resolved_asset_id = _normalize_optional_text(asset_id)
    resolved_rfq_id = _normalize_optional_text(rfq_id)
    resolved_email = _normalize_optional_text(email)

    if is_interactive():
        if resolved_asset_id is None and typer.confirm(
            "Attach an RGB asset to the channel order?", default=False
        ):
            resolved_asset_id = _prompt_optional_text("Asset ID (rgb:...)")

        if resolved_asset_id is not None:
            if lsp_asset_amount is None:
                lsp_asset_amount = _prompt_optional_int(
                    "[OPTIONAL] LSP RGB asset amount (Enter to skip)"
                )
            if client_asset_amount is None:
                client_asset_amount = _prompt_optional_int(
                    "[OPTIONAL] Client RGB asset amount (Enter to skip)"
                )
        else:
            lsp_asset_amount = None
            client_asset_amount = None

        announce_channel = typer.confirm("Announce channel publicly?", default=announce_channel)

        if resolved_token is None:
            resolved_token = _prompt_optional_text(
                "[OPTIONAL] Authentication token (Enter to skip)"
            )
        if resolved_refund_onchain_address is None:
            resolved_refund_onchain_address = _prompt_optional_text(
                "[OPTIONAL] Refund onchain address (Enter to skip)"
            )
        if resolved_rfq_id is None:
            resolved_rfq_id = _prompt_optional_text("[OPTIONAL] RFQ ID (Enter to skip)")
        if resolved_email is None:
            resolved_email = _prompt_optional_text("[OPTIONAL] Contact email (Enter to skip)")

    if (
        lsp_asset_amount is not None or client_asset_amount is not None
    ) and resolved_asset_id is None:
        print_error("--lsp-asset-amount and --client-asset-amount require --asset-id.")
        raise typer.Exit(1)

    return ChannelOrderParams(
        client_pubkey=resolved_client_pubkey,
        lsp_balance_sat=resolved_lsp_balance_sat,
        client_balance_sat=resolved_client_balance_sat,
        required_channel_confirmations=required_channel_confirmations,
        funding_confirms_within_blocks=funding_confirms_within_blocks,
        channel_expiry_blocks=channel_expiry_blocks,
        token=resolved_token,
        refund_onchain_address=resolved_refund_onchain_address,
        announce_channel=announce_channel,
        asset_id=resolved_asset_id,
        lsp_asset_amount=lsp_asset_amount,
        client_asset_amount=client_asset_amount,
        rfq_id=resolved_rfq_id,
        email=resolved_email,
    )


def _build_channel_order_request(params: ChannelOrderParams) -> CreateOrderRequest:
    return CreateOrderRequest(
        client_pubkey=params.client_pubkey,
        lsp_balance_sat=params.lsp_balance_sat,
        client_balance_sat=params.client_balance_sat,
        required_channel_confirmations=params.required_channel_confirmations,
        funding_confirms_within_blocks=params.funding_confirms_within_blocks,
        channel_expiry_blocks=params.channel_expiry_blocks,
        token=params.token,
        refund_onchain_address=params.refund_onchain_address,
        announce_channel=params.announce_channel,
        asset_id=params.asset_id,
        lsp_asset_amount=params.lsp_asset_amount,
        client_asset_amount=params.client_asset_amount,
        rfq_id=params.rfq_id,
        email=params.email,
    )


async def _create_channel_order(client: Any, params: ChannelOrderParams) -> ChannelOrderResponse:
    return await _submit_channel_order(client, _build_channel_order_request(params))


async def _get_channel_order(
    client: Any, order_id: str, access_token: str = ""
) -> ChannelOrderResponse:
    return await _fetch_channel_order(
        client,
        OrderRequest(order_id=order_id, access_token=access_token),
    )


async def _estimate_channel_order_fees(client: Any, params: ChannelOrderParams) -> ChannelFees:
    return await client.maker.estimate_lsp_fees(_build_channel_order_request(params))


def _print_channel_order_fees(resp: ChannelFees, *, title: str) -> None:
    output_model(resp, title=title)


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
        "  [cyan]kaleido channel order create 03abc... --lsp-balance 1000000 --client-balance 500000[/cyan]\n\n"
        "  RGB colored channel order:\n"
        "  [cyan]kaleido channel order create 03abc... --lsp-balance 1000000 --client-balance 500000 \\'\n"
        "      --asset-id rgb:xyz... --lsp-asset-amount 5000 --client-asset-amount 2000[/cyan]\n\n"
        "  With custom confirmations and refund address:\n"
        "  [cyan]kaleido channel order create 03abc... --lsp-balance 1000000 --client-balance 500000 \\'\n"
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
    params = _resolve_channel_order_params(
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

    asyncio.run(_channel_order_create(params))


async def _channel_order_create(params) -> None:
    try:
        client = get_client()
        resp: ChannelOrderResponse = await _create_channel_order(client, params)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"LSP order created: {resp.order_id}")
            output_model(resp, title="Channel Order")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@order_app.command(
    "get",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Get order status:\n"
        "  [cyan]kaleido channel order get <order-id>[/cyan]"
    ),
)
def channel_order_get(
    order_id: Annotated[str | None, typer.Argument(help="LSP order ID.")] = None,
    access_token: Annotated[
        str | None,
        typer.Option("--access-token", help="Access token returned for the order."),
    ] = None,
) -> None:
    """Get the status and details of an LSP channel order."""
    resolved_order_id = resolve_required_text(order_id, "LSP order ID", "ORDER_ID argument")
    resolved_access_token = resolve_required_text(access_token, "Access token", "--access-token")

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
    "decide",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Accept an order:\n"
        "  [cyan]kaleido channel order decide <order-id> --accept[/cyan]\n\n"
        "  Reject an order:\n"
        "  [cyan]kaleido channel order decide <order-id> --reject[/cyan]"
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


@order_app.command(
    "estimate-fees",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Estimate fees for a channel:\n"
        "  [cyan]kaleido channel order estimate-fees 03abc... --lsp-balance 1000000 --client-balance 500000[/cyan]"
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
        typer.Option(
            "--confirmations", help="Required confirmations before channel is considered open."
        ),
    ] = 6,
    funding_confirms_within_blocks: Annotated[
        int,
        typer.Option(
            "--funding-within", help="Number of blocks within which funding must confirm."
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
    rfq_id: Annotated[
        str | None,
        typer.Option("--rfq-id", help="Request for quote ID."),
    ] = None,
    email: Annotated[str | None, typer.Option("--email", help="Contact email.")] = None,
) -> None:
    """Estimate fees for opening an LSP channel."""
    params = _resolve_channel_order_params(
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

    asyncio.run(_channel_estimate_fees(params))


async def _channel_estimate_fees(params) -> None:
    try:
        client = get_client()
        resp: ChannelFees = await _estimate_channel_order_fees(client, params)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            _print_channel_order_fees(resp, title="Estimated Fees")
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


def _humanize_key(key: str) -> str:
    return key.replace("_", " ").capitalize()


def _short_id(value: str | None, *, prefix: int = 16, suffix: int = 8) -> str:
    if not value:
        return "-"
    if len(value) <= prefix + suffix + 1:
        return value
    return f"{value[:prefix]}…{value[-suffix:]}"


def _print_lsp_info(resp: LspInfoResponse) -> None:
    print_panel("LSP Connection", resp.lsp_connection_url or "-", style="blue")

    if resp.options is not None:
        output_model(
            {_humanize_key(key): value for key, value in resp.options.model_dump().items()},
            title="Channel Options",
        )
    output_collection(
        "LSP Assets",
        [
            {
                **asset.model_dump(),
                "asset_id": _short_id(asset.asset_id),
                "client_range": f"{asset.min_initial_client_amount} -> {asset.max_initial_client_amount}",
                "lsp_range": f"{asset.min_initial_lsp_amount} -> {asset.max_initial_lsp_amount}",
                "channel_range": f"{asset.min_channel_amount} -> {asset.max_channel_amount}",
            }
            for asset in (resp.assets or [])
        ],
        item_title="LSP Asset — {index}",
        empty_msg="No asset-backed channel options reported.",
    )


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
