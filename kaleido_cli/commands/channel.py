"""Lightning channel commands — list, open, close, and LSP orders."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Annotated, Any, TypeVar

import typer
from kaleido_sdk import (
    ChannelFees,
    ChannelOrderResponse,
    CreateOrderRequest,
    Layer,
    LspInfoResponse,
    NetworkInfoResponse,
    OrderRequest,
    PairQuoteRequest,
    PaymentState,
    RateDecisionRequest,
    RateDecisionResponse,
    SwapLegInput,
)
from kaleido_sdk.rln import (
    CloseChannelRequest,
    ConnectPeerRequest,
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
    help="LSP-backed channel order flow: create, inspect, pay, decide, and estimate fees.",
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
CHANNEL_ORDER_HTTP_TIMEOUT = 30.0

T = TypeVar("T")


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


def _range_text(min_value: int | None, max_value: int | None) -> str:
    if min_value is None and max_value is None:
        return "any"
    if min_value is None:
        return f"<= {max_value}"
    if max_value is None:
        return f">= {min_value}"
    return f"{min_value} -> {max_value}"


def _validate_int_range(
    value: int,
    label: str,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    if min_value is not None and value < min_value:
        print_error(f"{label} must be at least {min_value}.")
        raise typer.Exit(1)
    if max_value is not None and value > max_value:
        print_error(f"{label} must be at most {max_value}.")
        raise typer.Exit(1)
    return value


def _prompt_int_in_range(
    prompt: str,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
    default: int | None = None,
) -> int:
    suffix = f" ({_range_text(min_value, max_value)})"
    prompt_kwargs: dict[str, Any] = {"type": int, "show_default": default is not None}
    if default is not None:
        prompt_kwargs["default"] = default
    value = typer.prompt(f"{prompt}{suffix}", **prompt_kwargs)
    return _validate_int_range(value, prompt, min_value=min_value, max_value=max_value)


def _lsp_options_limits(lsp_info: LspInfoResponse | None) -> dict[str, int | None]:
    options = lsp_info.options if lsp_info is not None else None
    return {
        "min_lsp_balance_sat": getattr(options, "min_initial_lsp_balance_sat", None),
        "max_lsp_balance_sat": getattr(options, "max_initial_lsp_balance_sat", None),
        "min_client_balance_sat": getattr(options, "min_initial_client_balance_sat", None),
        "max_client_balance_sat": getattr(options, "max_initial_client_balance_sat", None),
        "min_channel_balance_sat": getattr(options, "min_channel_balance_sat", None),
        "max_channel_balance_sat": getattr(options, "max_channel_balance_sat", None),
        "min_required_confirmations": getattr(options, "min_required_channel_confirmations", None),
        "min_funding_within_blocks": getattr(options, "min_funding_confirms_within_blocks", None),
        "max_expiry_blocks": getattr(options, "max_channel_expiry_blocks", None),
    }


def _print_lsp_order_limits(lsp_info: LspInfoResponse) -> None:
    limits = _lsp_options_limits(lsp_info)
    output_model(
        {
            "lsp_balance_sat": _range_text(
                limits["min_lsp_balance_sat"], limits["max_lsp_balance_sat"]
            ),
            "client_balance_sat": _range_text(
                limits["min_client_balance_sat"], limits["max_client_balance_sat"]
            ),
            "total_channel_balance_sat": _range_text(
                limits["min_channel_balance_sat"], limits["max_channel_balance_sat"]
            ),
            "required_confirmations_min": limits["min_required_confirmations"],
            "funding_within_blocks_min": limits["min_funding_within_blocks"],
            "expiry_blocks_max": limits["max_expiry_blocks"],
        },
        title="LSP Channel Limits",
    )


def _find_lsp_asset(lsp_info: LspInfoResponse | None, asset_id_or_ticker: str | None):
    if lsp_info is None or not asset_id_or_ticker:
        return None
    normalized = asset_id_or_ticker.lower()
    for asset in lsp_info.assets or []:
        if (asset.asset_id or "").lower() == normalized or asset.ticker.lower() == normalized:
            return asset
    return None


def _format_elapsed(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    return f"{seconds:.1f}s"


async def _timed_step(label: str, awaitable: Awaitable[T]) -> T:
    if not is_json_mode():
        print_info(f"{label}...")
    started_at = perf_counter()
    try:
        result = await awaitable
    except Exception:
        if not is_json_mode():
            print_error(f"{label} failed after {_format_elapsed(perf_counter() - started_at)}")
        raise
    if not is_json_mode():
        print_success(f"{label} finished in {_format_elapsed(perf_counter() - started_at)}")
    return result


def _print_lsp_asset_options(lsp_info: LspInfoResponse) -> None:
    for idx, asset in enumerate(lsp_info.assets or [], start=1):
        print_info(
            f"{idx}. {asset.ticker} ({asset.name}) "
            f"asset={asset.asset_id} "
            f"lsp={asset.min_initial_lsp_amount}->{asset.max_initial_lsp_amount} "
            f"client={asset.min_initial_client_amount}->{asset.max_initial_client_amount} "
            f"channel={asset.min_channel_amount}->{asset.max_channel_amount}"
        )


def _prompt_lsp_asset(lsp_info: LspInfoResponse) -> str | None:
    assets = lsp_info.assets or []
    if not assets:
        print_info("The LSP did not report asset-backed channel options.")
        return _prompt_optional_text("Asset ID (rgb:...)")
    _print_lsp_asset_options(lsp_info)
    selected = _prompt_int_in_range(
        "Select asset option number", min_value=1, max_value=len(assets)
    )
    return assets[selected - 1].asset_id


def _validate_lsp_amounts(
    *,
    lsp_info: LspInfoResponse | None,
    lsp_balance_sat: int,
    client_balance_sat: int,
    required_channel_confirmations: int,
    funding_confirms_within_blocks: int,
    channel_expiry_blocks: int,
) -> None:
    limits = _lsp_options_limits(lsp_info)
    _validate_int_range(
        lsp_balance_sat,
        "--lsp-balance",
        min_value=limits["min_lsp_balance_sat"],
        max_value=limits["max_lsp_balance_sat"],
    )
    _validate_int_range(
        client_balance_sat,
        "--client-balance",
        min_value=limits["min_client_balance_sat"],
        max_value=limits["max_client_balance_sat"],
    )
    _validate_int_range(
        lsp_balance_sat + client_balance_sat,
        "Total channel balance",
        min_value=limits["min_channel_balance_sat"],
        max_value=limits["max_channel_balance_sat"],
    )
    _validate_int_range(
        required_channel_confirmations,
        "--confirmations",
        min_value=limits["min_required_confirmations"],
    )
    _validate_int_range(
        funding_confirms_within_blocks,
        "--funding-within",
        min_value=limits["min_funding_within_blocks"],
    )
    _validate_int_range(
        channel_expiry_blocks,
        "--expiry-blocks",
        min_value=1,
        max_value=limits["max_expiry_blocks"],
    )


def _validate_asset_amounts(
    *,
    lsp_asset: Any,
    lsp_asset_amount: int | None,
    client_asset_amount: int | None,
) -> None:
    if lsp_asset_amount is None:
        print_error("--lsp-asset-amount is required when --asset-id is set.")
        raise typer.Exit(1)
    _validate_int_range(
        lsp_asset_amount,
        "--lsp-asset-amount",
        min_value=lsp_asset.min_initial_lsp_amount,
        max_value=lsp_asset.max_initial_lsp_amount,
    )
    if client_asset_amount is not None:
        _validate_int_range(
            client_asset_amount,
            "--client-asset-amount",
            min_value=lsp_asset.min_initial_client_amount,
            max_value=min(lsp_asset.max_initial_client_amount, lsp_asset_amount),
        )
        if client_asset_amount > lsp_asset_amount:
            print_error("--client-asset-amount must be less than or equal to --lsp-asset-amount.")
            raise typer.Exit(1)
    total_asset_amount = lsp_asset_amount + (client_asset_amount or 0)
    _validate_int_range(
        total_asset_amount,
        "Total channel asset amount",
        min_value=lsp_asset.min_channel_amount,
        max_value=lsp_asset.max_channel_amount,
    )


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_channel_order_params(
    *,
    client_pubkey: str | None,
    default_client_pubkey: str | None,
    lsp_info: LspInfoResponse | None,
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
) -> ChannelOrderParams:
    resolved_client_pubkey: str
    if client_pubkey is not None:
        resolved_client_pubkey = client_pubkey
    elif default_client_pubkey is not None:
        resolved_client_pubkey = default_client_pubkey
        if is_interactive():
            print_info(f"Using local node pubkey: {resolved_client_pubkey}")
    elif is_interactive():
        resolved_client_pubkey = typer.prompt("Client Lightning node public key")
    else:
        print_error("CLIENT_PUBKEY argument is required in non-interactive mode.")
        raise typer.Exit(1)

    if is_interactive() and lsp_info is not None:
        _print_lsp_order_limits(lsp_info)

    limits = _lsp_options_limits(lsp_info)
    resolved_lsp_balance_sat: int
    if lsp_balance_sat is not None:
        resolved_lsp_balance_sat = _validate_int_range(
            lsp_balance_sat,
            "--lsp-balance",
            min_value=limits["min_lsp_balance_sat"],
            max_value=limits["max_lsp_balance_sat"],
        )
    elif is_interactive():
        resolved_lsp_balance_sat = _prompt_int_in_range(
            "LSP balance in channel (satoshis)",
            min_value=limits["min_lsp_balance_sat"],
            max_value=limits["max_lsp_balance_sat"],
        )
    else:
        print_error("--lsp-balance is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_client_balance_sat: int
    if client_balance_sat is not None:
        resolved_client_balance_sat = _validate_int_range(
            client_balance_sat,
            "--client-balance",
            min_value=limits["min_client_balance_sat"],
            max_value=limits["max_client_balance_sat"],
        )
    elif is_interactive():
        resolved_client_balance_sat = _prompt_int_in_range(
            "Client balance in channel (satoshis)",
            min_value=limits["min_client_balance_sat"],
            max_value=limits["max_client_balance_sat"],
        )
    else:
        print_error("--client-balance is required in non-interactive mode.")
        raise typer.Exit(1)

    if is_interactive():
        required_channel_confirmations = _prompt_int_in_range(
            "Required channel confirmations",
            min_value=limits["min_required_confirmations"],
            default=required_channel_confirmations,
        )
        funding_confirms_within_blocks = _prompt_int_in_range(
            "Funding confirms within blocks",
            min_value=limits["min_funding_within_blocks"],
            default=funding_confirms_within_blocks,
        )
        channel_expiry_blocks = _prompt_int_in_range(
            "Channel expiry blocks",
            min_value=1,
            max_value=limits["max_expiry_blocks"],
            default=channel_expiry_blocks,
        )

    resolved_refund_onchain_address = _normalize_optional_text(refund_onchain_address)
    resolved_asset_id = _normalize_optional_text(asset_id)
    resolved_email = _normalize_optional_text(email)

    if is_interactive():
        if resolved_asset_id is None and typer.confirm(
            "Attach an RGB asset to the channel order?", default=False
        ):
            if lsp_info is not None:
                resolved_asset_id = _prompt_lsp_asset(lsp_info)
            else:
                resolved_asset_id = _prompt_optional_text("Asset ID (rgb:...)")

        if resolved_asset_id is not None:
            lsp_asset = _find_lsp_asset(lsp_info, resolved_asset_id)
            if lsp_info is not None and lsp_asset is None:
                print_error(f"Asset {resolved_asset_id!r} is not available from the LSP.")
                raise typer.Exit(1)
            if lsp_asset_amount is None:
                if lsp_asset is not None:
                    lsp_asset_amount = _prompt_int_in_range(
                        "LSP RGB asset amount (raw units)",
                        min_value=lsp_asset.min_initial_lsp_amount,
                        max_value=lsp_asset.max_initial_lsp_amount,
                    )
                else:
                    lsp_asset_amount = typer.prompt("LSP RGB asset amount (raw units)", type=int)
            if client_asset_amount is None:
                if lsp_asset is not None:
                    max_client_asset_amount = lsp_asset.max_initial_client_amount
                    if lsp_asset_amount is not None:
                        max_client_asset_amount = min(max_client_asset_amount, lsp_asset_amount)
                    client_asset_amount = _prompt_int_in_range(
                        "Client RGB asset amount (raw units)",
                        min_value=lsp_asset.min_initial_client_amount,
                        max_value=max_client_asset_amount,
                        default=0,
                    )
                else:
                    client_asset_amount = typer.prompt(
                        "Client RGB asset amount (raw units)", type=int, default=0
                    )
        else:
            lsp_asset_amount = None
            client_asset_amount = None

        announce_channel = typer.confirm("Announce channel publicly?", default=announce_channel)

        if resolved_email is None:
            resolved_email = _prompt_optional_text("[OPTIONAL] Contact email (Enter to skip)")

    if (
        lsp_asset_amount is not None or client_asset_amount is not None
    ) and resolved_asset_id is None:
        print_error("--lsp-asset-amount and --client-asset-amount require --asset-id.")
        raise typer.Exit(1)
    if resolved_asset_id is not None:
        lsp_asset = _find_lsp_asset(lsp_info, resolved_asset_id)
        if lsp_info is not None and lsp_asset is None:
            print_error(f"Asset {resolved_asset_id!r} is not available from the LSP.")
            raise typer.Exit(1)
        if lsp_asset is not None:
            resolved_asset_id = lsp_asset.asset_id or resolved_asset_id
            _validate_asset_amounts(
                lsp_asset=lsp_asset,
                lsp_asset_amount=lsp_asset_amount,
                client_asset_amount=client_asset_amount,
            )
        elif lsp_asset_amount is None:
            print_error("--lsp-asset-amount is required when --asset-id is set.")
            raise typer.Exit(1)

    _validate_lsp_amounts(
        lsp_info=lsp_info,
        lsp_balance_sat=resolved_lsp_balance_sat,
        client_balance_sat=resolved_client_balance_sat,
        required_channel_confirmations=required_channel_confirmations,
        funding_confirms_within_blocks=funding_confirms_within_blocks,
        channel_expiry_blocks=channel_expiry_blocks,
    )

    return ChannelOrderParams(
        client_pubkey=resolved_client_pubkey,
        lsp_balance_sat=resolved_lsp_balance_sat,
        client_balance_sat=resolved_client_balance_sat,
        required_channel_confirmations=required_channel_confirmations,
        funding_confirms_within_blocks=funding_confirms_within_blocks,
        channel_expiry_blocks=channel_expiry_blocks,
        token=None,
        refund_onchain_address=resolved_refund_onchain_address,
        announce_channel=announce_channel,
        asset_id=resolved_asset_id,
        lsp_asset_amount=lsp_asset_amount,
        client_asset_amount=client_asset_amount or None,
        rfq_id=None,
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


def _peer_pubkey_from_connection_url(connection_url: str | None) -> str | None:
    if not connection_url:
        return None
    return connection_url.split("@", 1)[0].strip() or None


async def _ensure_lsp_peer_connected(client: Any, lsp_info: LspInfoResponse) -> None:
    connection_url = lsp_info.lsp_connection_url
    lsp_pubkey = _peer_pubkey_from_connection_url(connection_url)
    if not connection_url or not lsp_pubkey:
        print_error("LSP did not report a connection URL.")
        raise typer.Exit(1)

    peers = await _timed_step(
        f"Checking LSP peer connection: {lsp_pubkey}",
        client.rln.list_peers(),
    )
    connected_pubkeys = {peer.pubkey for peer in (peers.peers or [])}
    if lsp_pubkey in connected_pubkeys:
        print_info(f"Already connected to LSP peer: {lsp_pubkey}")
        return
    await _timed_step(
        f"Connecting to LSP peer: {connection_url}",
        client.rln.connect_peer(ConnectPeerRequest(peer_pubkey_and_addr=connection_url)),
    )
    print_success(f"LSP peer connected: {lsp_pubkey}")


async def _autofill_refund_address(client: Any, params: ChannelOrderParams) -> None:
    if params.refund_onchain_address:
        return
    address = await _timed_step("Fetching refund onchain address", client.rln.get_address())
    params.refund_onchain_address = address.address
    print_info(f"Using refund onchain address from local node: {params.refund_onchain_address}")


def _quote_leg_summary(leg: Any) -> str:
    ticker = getattr(leg, "ticker", None) or getattr(leg, "asset_id", "asset")
    amount = getattr(leg, "amount", None)
    if amount is None:
        return str(ticker)
    return f"{amount} {ticker}"


def _quote_amount_summary(quote: Any) -> str:
    return (
        f"receive {_quote_leg_summary(quote.to_asset)} for {_quote_leg_summary(quote.from_asset)}"
    )


async def _attach_client_asset_quote(
    client: Any,
    params: ChannelOrderParams,
    *,
    yes: bool,
) -> None:
    if not params.asset_id or not params.client_asset_amount or params.client_asset_amount <= 0:
        params.rfq_id = None
        return

    quote = await _timed_step(
        "Fetching RFQ quote",
        client.maker.get_quote(
            PairQuoteRequest(
                from_asset=SwapLegInput(
                    asset_id=params.asset_id,
                    layer=Layer.RGB_LN,
                    amount=params.client_asset_amount,
                ),
                to_asset=SwapLegInput(asset_id="BTC", layer=Layer.BTC_LN, amount=None),
            )
        ),
    )
    if is_json_mode():
        if not yes:
            print_error("--yes is required in JSON mode to accept the RFQ price.")
            raise typer.Exit(1)
    else:
        quote_summary = _quote_amount_summary(quote)
        print_info(f"Quoted amount: {quote_summary}")
        if is_interactive():
            if not typer.confirm(f"Accept quoted amount ({quote_summary})?", default=False):
                print_error("Channel order cancelled before creation.")
                raise typer.Exit(0)
        elif not yes:
            print_error("--yes is required in non-interactive mode to accept the RFQ price.")
            raise typer.Exit(1)
    params.rfq_id = quote.rfq_id
    print_info(f"Using RFQ ID: {params.rfq_id}")


async def _get_channel_order(
    client: Any, order_id: str, access_token: str = ""
) -> ChannelOrderResponse:
    return await _fetch_channel_order(
        client,
        OrderRequest(order_id=order_id, access_token=access_token),
    )


def _channel_wallet_payment_summary(order: ChannelOrderResponse) -> dict[str, Any]:
    payment = order.payment.bolt11
    return {
        "order_id": order.order_id,
        "order_state": order.order_state,
        "payment_state": payment.state,
        "order_total_sat": payment.order_total_sat,
        "fee_total_sat": payment.fee_total_sat,
        "expires_at": payment.expires_at,
    }


def _can_pay_channel_order(order: ChannelOrderResponse) -> bool:
    return order.payment.bolt11.state == PaymentState.EXPECT_PAYMENT


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
            if _can_pay_channel_order(resp):
                print_info(
                    f"Pay from local wallet funds with: kaleido channel order pay {resp.order_id}"
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
        "  [cyan]kaleido channel order get <order-id>[/cyan]"
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
    resolved_access_token = access_token or ""

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
        "  [cyan]kaleido channel order pay <order-id>[/cyan]\n\n"
        "  Non-interactive payment:\n"
        "  [cyan]kaleido channel order pay <order-id> --yes[/cyan]"
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
    asyncio.run(_channel_order_pay(resolved_order_id, access_token or "", yes=yes))


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
        "  [cyan]kaleido channel order estimate-fees --lsp-balance 1000000 --client-balance 500000[/cyan]"
    ),
)
def channel_estimate_fees(
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
    refund_onchain_address: Annotated[
        str | None,
        typer.Option("--refund-address", help="Bitcoin address for refunds."),
    ] = None,
    announce_channel: Annotated[
        bool,
        typer.Option("--announce/--private", help="Announce channel publicly."),
    ] = True,
    email: Annotated[str | None, typer.Option("--email", help="Contact email.")] = None,
) -> None:
    """Estimate fees for opening an LSP channel."""
    asyncio.run(
        _channel_estimate_fees_flow(
            client_pubkey=client_pubkey,
            lsp_balance_sat=lsp_balance_sat,
            client_balance_sat=client_balance_sat,
            asset_id=asset_id,
            lsp_asset_amount=lsp_asset_amount,
            client_asset_amount=client_asset_amount,
            required_channel_confirmations=required_channel_confirmations,
            funding_confirms_within_blocks=funding_confirms_within_blocks,
            channel_expiry_blocks=channel_expiry_blocks,
            refund_onchain_address=refund_onchain_address,
            announce_channel=announce_channel,
            email=email,
        )
    )


async def _channel_estimate_fees_flow(
    *,
    client_pubkey: str | None,
    lsp_balance_sat: int | None,
    client_balance_sat: int | None,
    asset_id: str | None,
    lsp_asset_amount: int | None,
    client_asset_amount: int | None,
    required_channel_confirmations: int,
    funding_confirms_within_blocks: int,
    channel_expiry_blocks: int,
    refund_onchain_address: str | None,
    announce_channel: bool,
    email: str | None,
) -> None:
    try:
        client = get_client(require_node=True)
        node_info = await client.rln.get_node_info()
        lsp_info = await client.maker.get_lsp_info()
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
        resp: ChannelFees = await _estimate_channel_order_fees(client, params)
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
