"""RGB asset commands — list, issue, send, invoices, transfers."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Annotated

import typer
from kaleido_sdk.rln import (
    AssetBalanceRequest,
    AssetBalanceResponse,
    AssetMetadataRequest,
    AssetMetadataResponse,
    AssignmentFungible,
    FailTransfersRequest,
    FailTransfersResponse,
    GetAssetMediaRequest,
    GetAssetMediaResponse,
    IssueAssetCFARequest,
    IssueAssetCFAResponse,
    IssueAssetNIARequest,
    IssueAssetNIAResponse,
    IssueAssetUDARequest,
    IssueAssetUDAResponse,
    ListAssetsResponse,
    ListTransfersRequest,
    ListTransfersResponse,
    Recipient,
    RefreshRequest,
    RgbInvoiceRequest,
    RgbInvoiceResponse,
    SendRgbRequest,
    SendRgbResponse,
    WitnessData,
)

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_interactive,
    is_json_mode,
    output_collection,
    output_model,
    print_error,
    print_json,
    print_success,
)

asset_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Manage RGB assets — list, issue, send (single or batch), invoices, and transfer history.",
)
issue_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Issue new RGB assets by schema: NIA, CFA, or UDA.",
)

asset_app.add_typer(issue_app, name="issue")


@asset_app.command(
    "list",
    epilog=(
        "  [cyan]kaleido asset list[/cyan]          Table view\n"
        "  [cyan]kaleido --json asset list[/cyan]   Raw JSON output"
    ),
)
def asset_list() -> None:
    """List all RGB assets held by the node."""
    asyncio.run(_asset_list())


async def _asset_list() -> None:
    try:
        client = get_client(require_node=True)
        resp: ListAssetsResponse = await client.rln.list_assets()
        if is_json_mode():
            print_json(resp.model_dump())
            return
        items = []
        if resp.nia:
            for asset in resp.nia:
                items.append({**asset.model_dump(), "schema": "NIA"})
        if resp.cfa:
            for asset in resp.cfa:
                items.append({**asset.model_dump(), "schema": "CFA"})
        if resp.uda:
            for asset in resp.uda:
                items.append({**asset.model_dump(), "schema": "UDA"})
        output_collection("RGB Assets", items, item_title="RGB Asset — {index}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@asset_app.command("balance")
def asset_balance(
    asset_id: Annotated[str, typer.Argument(help="RGB asset ID.")],
) -> None:
    """Show balance for a specific RGB asset."""
    asyncio.run(_asset_balance(asset_id))


async def _asset_balance(asset_id: str) -> None:
    try:
        client = get_client(require_node=True)
        resp: AssetBalanceResponse = await client.rln.get_asset_balance(
            AssetBalanceRequest(asset_id=asset_id)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title=f"Balance — {asset_id[:20]}…")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@asset_app.command("metadata")
def asset_metadata(
    asset_id: Annotated[str, typer.Argument(help="RGB asset ID.")],
) -> None:
    """Show metadata for a specific RGB asset."""
    asyncio.run(_asset_metadata(asset_id))


async def _asset_metadata(asset_id: str) -> None:
    try:
        client = get_client(require_node=True)
        resp: AssetMetadataResponse = await client.rln.get_asset_metadata(
            AssetMetadataRequest(asset_id=asset_id)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title=f"Metadata — {asset_id[:20]}…")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@issue_app.command(
    "nia",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Issue 1 000 000 USDT tokens with 6 decimal places:\n"
        '  [cyan]kaleido asset issue nia --name "Tether USD" --ticker USDT --supply 1000000 --precision 6[/cyan]\n\n'
        "  Issue a simple whole-unit token:\n"
        "  [cyan]kaleido asset issue nia --name MyToken --ticker MTK --supply 21000000[/cyan]\n\n"
        "[dim]NIA = Non-Inflatable Asset (fixed-supply fungible token).[/dim]"
    ),
)
def asset_issue_nia(
    name: Annotated[
        str | None,
        typer.Option("--name", help="Human-readable asset name."),
    ] = None,
    ticker: Annotated[
        str | None,
        typer.Option("--ticker", help="Short ticker symbol, e.g. USDT."),
    ] = None,
    supply: Annotated[
        int | None,
        typer.Option("--supply", help="Total supply expressed in the smallest raw unit."),
    ] = None,
    precision: Annotated[
        int,
        typer.Option("--precision", help="Number of decimal places (0 = whole units)."),
    ] = 0,
) -> None:
    """Issue a new NIA (Non-Inflatable Asset) RGB token."""
    resolved_name: str
    if name is not None:
        resolved_name = name
    elif is_interactive():
        resolved_name = typer.prompt("Asset name")
    else:
        print_error("--name is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_ticker: str
    if ticker is not None:
        resolved_ticker = ticker
    elif is_interactive():
        resolved_ticker = typer.prompt("Ticker symbol (e.g. USDT)")
    else:
        print_error("--ticker is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_supply: int
    if supply is not None:
        resolved_supply = supply
    elif is_interactive():
        resolved_supply = typer.prompt("Total supply (raw units)", type=int)
    else:
        print_error("--supply is required in non-interactive mode.")
        raise typer.Exit(1)

    if is_interactive():
        precision = typer.prompt("[OPTIONAL] Decimal places (0 = whole units)", default=0, type=int)

    asyncio.run(_issue_nia(resolved_name, resolved_ticker, resolved_supply, precision))


async def _issue_nia(name: str, ticker: str, supply: int, precision: int) -> None:
    try:
        client = get_client(require_node=True)
        resp: IssueAssetNIAResponse = await client.rln.issue_asset_nia(
            IssueAssetNIARequest(name=name, ticker=ticker, amounts=[supply], precision=precision)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"NIA asset issued: {resp.asset.asset_id}")
            output_model(resp, title="Issued Asset")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@issue_app.command(
    "cfa",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Basic CFA with no media:\n"
        '  [cyan]kaleido asset issue cfa --name "My NFT" --supply 1[/cyan]\n\n'
        "  With description and attached media file:\n"
        '  [cyan]kaleido asset issue cfa --name "Art Piece" --supply 100 --description "Limited series" --file ./art.png[/cyan]\n\n'
        "[dim]CFA = Collectible Fungible Asset.[/dim]"
    ),
)
def asset_issue_cfa(
    name: Annotated[
        str | None,
        typer.Option("--name", help="Asset name."),
    ] = None,
    supply: Annotated[
        int | None,
        typer.Option("--supply", help="Total supply in raw units."),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="Optional description shown in wallets."),
    ] = None,
    file_path: Annotated[
        str | None,
        typer.Option("--file", help="Path to a media file (image, etc.) to embed."),
    ] = None,
    precision: Annotated[
        int,
        typer.Option("--precision", help="Number of decimal places (0 = whole units)."),
    ] = 0,
) -> None:
    """Issue a new CFA (Collectible Fungible Asset) RGB token."""
    resolved_name: str
    if name is not None:
        resolved_name = name
    elif is_interactive():
        resolved_name = typer.prompt("Asset name")
    else:
        print_error("--name is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_supply: int
    if supply is not None:
        resolved_supply = supply
    elif is_interactive():
        resolved_supply = typer.prompt("Total supply (raw units)", type=int)
    else:
        print_error("--supply is required in non-interactive mode.")
        raise typer.Exit(1)

    if is_interactive():
        raw = typer.prompt("[OPTIONAL] Description (Enter to skip)", default="")
        if raw.strip():
            description = raw.strip()
        raw = typer.prompt("[OPTIONAL] Media file path (Enter to skip)", default="")
        if raw.strip():
            file_path = raw.strip()
        precision = typer.prompt("[OPTIONAL] Decimal places (0 = whole units)", default=0, type=int)

    asyncio.run(_issue_cfa(resolved_name, resolved_supply, description, file_path, precision))


async def _issue_cfa(
    name: str,
    supply: int,
    description: str | None,
    file_path: str | None,
    precision: int,
) -> None:
    try:
        client = get_client(require_node=True)
        file_digest: str | None = None
        if file_path:
            with open(file_path, "rb") as f:
                file_digest = hashlib.sha256(f.read()).hexdigest()
        body = IssueAssetCFARequest(
            name=name,
            amounts=[supply],
            precision=precision,
            details=description,
            file_digest=file_digest,
        )
        resp: IssueAssetCFAResponse = await client.rln.issue_asset_cfa(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"CFA asset issued: {resp.asset.asset_id}")
            output_model(resp, title="Issued Asset")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@asset_app.command(
    "invoice",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Request any amount of an asset:\n"
        "  [cyan]kaleido asset invoice rgb:abc123...[/cyan]\n\n"
        "  Request exactly 500 units:\n"
        "  [cyan]kaleido asset invoice rgb:abc123... --amount 500[/cyan]\n\n"
        "  With expiration time (1 hour):\n"
        "  [cyan]kaleido asset invoice rgb:abc123... --amount 500 --duration 3600[/cyan]\n\n"
        "  With minimum confirmations:\n"
        "  [cyan]kaleido asset invoice rgb:abc123... --amount 500 --min-confirmations 3[/cyan]"
    ),
)
def asset_invoice(
    asset_id: Annotated[str | None, typer.Argument(help="RGB asset ID to receive.")] = None,
    amount: Annotated[
        int | None,
        typer.Option(
            "--amount",
            "-a",
            help="Amount to request (raw units). Omit for any-amount invoice.",
        ),
    ] = None,
    min_confirmations: Annotated[
        int,
        typer.Option(
            "--min-confirmations",
            help="Minimum number of confirmations required for the transfer.",
        ),
    ] = 0,
    duration_seconds: Annotated[
        int | None,
        typer.Option(
            "--duration",
            help="Invoice validity duration in seconds.",
        ),
    ] = None,
    witness: Annotated[
        bool,
        typer.Option(
            "--witness/--no-witness",
            help="Use witness-based transaction.",
        ),
    ] = False,
) -> None:
    """Create an RGB invoice to receive assets."""
    resolved_asset_id: str
    if asset_id is not None:
        resolved_asset_id = asset_id
    elif is_interactive():
        resolved_asset_id = typer.prompt("RGB asset ID (rgb:...)")
    else:
        print_error("ASSET_ID argument is required in non-interactive mode.")
        raise typer.Exit(1)

    if is_interactive() and amount is None:
        raw = typer.prompt("[OPTIONAL] Amount to request (Enter for any-amount invoice)", default="")
        if raw.strip():
            amount = int(raw.strip())

    asyncio.run(_asset_invoice(resolved_asset_id, amount, min_confirmations, duration_seconds, witness))


async def _asset_invoice(
    asset_id: str,
    amount: int | None,
    min_confirmations: int,
    duration_seconds: int | None,
    witness: bool,
) -> None:
    try:
        client = get_client(require_node=True)
        resp: RgbInvoiceResponse = await client.rln.create_rgb_invoice(
            RgbInvoiceRequest(
                asset_id=asset_id,
                assignment=(
                    AssignmentFungible(type="Fungible", value=amount) if amount is not None else None
                ),
                min_confirmations=min_confirmations,
                duration_seconds=duration_seconds,
                witness=witness,
            )
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"Invoice: {resp.invoice}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@asset_app.command(
    "send",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Send 100 units to an RGB invoice:\n"
        "  [cyan]kaleido asset send rgb:abc123... 100 rgb:invoice...[/cyan]\n\n"
        "  With a custom on-chain fee rate:\n"
        "  [cyan]kaleido asset send rgb:abc123... 100 rgb:invoice... --fee-rate 3.0[/cyan]\n\n"
        "  Mark as donation with minimum confirmations:\n"
        "  [cyan]kaleido asset send rgb:abc123... 100 rgb:invoice... --donation --min-confirmations 3[/cyan]\n\n"
        "  Skip sync before sending:\n"
        "  [cyan]kaleido asset send rgb:abc123... 100 rgb:invoice... --skip-sync[/cyan]"
    ),
)
def asset_send(
    asset_id: Annotated[str | None, typer.Argument(help="RGB asset ID to send.")] = None,
    amount: Annotated[int | None, typer.Argument(help="Amount to send in raw asset units.")] = None,
    invoice: Annotated[str | None, typer.Argument(help="Recipient RGB invoice.")] = None,
    fee_rate: Annotated[
        int,
        typer.Option(
            "--fee-rate",
            help="On-chain fee rate in sat/vbyte.",
        ),
    ] = 1,
    min_confirmations: Annotated[
        int,
        typer.Option(
            "--min-confirmations",
            help="Minimum number of confirmations required for the transfer.",
        ),
    ] = 0,
    donation: Annotated[
        bool,
        typer.Option(
            "--donation",
            help="Mark this transfer as a donation.",
        ),
    ] = False,
    transport_endpoints: Annotated[
        list[str],
        typer.Option(
            "--transport-endpoint",
            help="Transport endpoint(s) for the recipient; can be repeated.",
        ),
    ] = [],
    witness_amount_sat: Annotated[
        int | None,
        typer.Option("--witness-amount-sat", help="Optional witness UTXO amount in satoshis."),
    ] = None,
    witness_blinding: Annotated[
        int | None,
        typer.Option("--witness-blinding", help="Optional witness blinding factor."),
    ] = None,
    skip_sync: Annotated[
        bool,
        typer.Option(
            "--skip-sync",
            help="Skip syncing before sending the transfer.",
        ),
    ] = False,
) -> None:
    """Send RGB assets to an invoice."""
    resolved_asset_id: str
    if asset_id is not None:
        resolved_asset_id = asset_id
    elif is_interactive():
        resolved_asset_id = typer.prompt("RGB asset ID (rgb:...)")
    else:
        print_error("ASSET_ID argument is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_amount: int
    if amount is not None:
        resolved_amount = amount
    elif is_interactive():
        resolved_amount = typer.prompt("Amount to send (raw units)", type=int)
    else:
        print_error("AMOUNT argument is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_invoice: str
    if invoice is not None:
        resolved_invoice = invoice
    elif is_interactive():
        resolved_invoice = typer.prompt("Recipient RGB invoice")
    else:
        print_error("INVOICE argument is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(
        _asset_send(
            resolved_asset_id,
            resolved_amount,
            resolved_invoice,
            fee_rate,
            min_confirmations,
            donation,
            transport_endpoints,
            witness_amount_sat,
            witness_blinding,
            skip_sync,
        )
    )


async def _asset_send(
    asset_id: str,
    amount: int,
    invoice: str,
    fee_rate: int,
    min_confirmations: int,
    donation: bool,
    transport_endpoints: list[str],
    witness_amount_sat: int | None,
    witness_blinding: int | None,
    skip_sync: bool,
) -> None:
    try:
        client = get_client(require_node=True)
        witness_data = None
        if witness_amount_sat is not None:
            witness_data = WitnessData(amount_sat=witness_amount_sat, blinding=witness_blinding)
        body = SendRgbRequest(
            recipient_map={
                asset_id: [
                    Recipient(
                        recipient_id=invoice,
                        witness_data=witness_data,
                        assignment=AssignmentFungible(type="Fungible", value=amount),
                        transport_endpoints=transport_endpoints,
                    )
                ]
            },
            fee_rate=fee_rate,
            min_confirmations=min_confirmations,
            donation=donation,
            skip_sync=skip_sync,
        )
        resp: SendRgbResponse = await client.rln.send_rgb(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"Sent! TXID: {resp.txid}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@asset_app.command(
    "send-batch",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Batch send from JSON file:\n"
        "  [cyan]kaleido asset send-batch batch.json[/cyan]\n\n"
        "[bold]JSON format example:[/bold]\n"
        "{\n"
        '  "recipient_map": {\n'
        '    "rgb:asset1...": [\n'
        '      {"recipient_id": "rgb:invoice1...", "assignment": {"type": "Fungible", "value": 100}},\n'
        '      {"recipient_id": "rgb:invoice2...", "assignment": {"type": "Fungible", "value": 200}}\n'
        "    ],\n"
        '    "rgb:asset2...": [\n'
        '      {"recipient_id": "rgb:invoice3...", "assignment": {"type": "Fungible", "value": 50}}\n'
        "    ]\n"
        "  },\n"
        '  "fee_rate": 2,\n'
        '  "min_confirmations": 3,\n'
        '  "donation": false,\n'
        '  "skip_sync": false\n'
        "}"
    ),
)
def asset_send_batch(
    json_file: Annotated[str, typer.Argument(help="Path to JSON file with batch transfer data.")],
) -> None:
    """Send RGB assets to multiple recipients in a single transaction."""
    asyncio.run(_asset_send_batch(json_file))


async def _asset_send_batch(json_file: str) -> None:
    import json
    from pathlib import Path

    try:
        path = Path(json_file).expanduser().resolve()
        if not path.exists():
            print_error(f"File not found: {json_file}")
            raise typer.Exit(1)

        with open(path) as f:
            data = json.load(f)

        client = get_client(require_node=True)

        recipient_map = {}
        for asset_id, recipients in data.get("recipient_map", {}).items():
            recipient_map[asset_id] = [Recipient.model_validate(recipient) for recipient in recipients]

        body = SendRgbRequest(
            recipient_map=recipient_map,
            fee_rate=data.get("fee_rate", 1),
            min_confirmations=data.get("min_confirmations", 0),
            donation=bool(data.get("donation", False)),
            skip_sync=bool(data.get("skip_sync", False)),
        )

        resp: SendRgbResponse = await client.rln.send_rgb(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            total_recipients = sum(len(recipients) for recipients in recipient_map.values())
            print_success(f"Batch send complete! Sent to {total_recipients} recipient(s)")
            print_success(f"TXID: {resp.txid}")
    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON: {e}")
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@asset_app.command(
    "transfers",
    epilog=(
        "  [cyan]kaleido asset transfers[/cyan]               All transfers\n"
        "  [cyan]kaleido asset transfers rgb:abc123...[/cyan]  Filtered by asset"
    ),
)
def asset_transfers(
    asset_id: Annotated[
        str,
        typer.Argument(help="RGB asset ID to list transfers for."),
    ],
) -> None:
    """List RGB transfers for a specific asset."""
    asyncio.run(_asset_transfers(asset_id))


async def _asset_transfers(asset_id: str) -> None:
    try:
        client = get_client(require_node=True)
        resp: ListTransfersResponse = await client.rln.list_transfers(
            ListTransfersRequest(asset_id=asset_id)
        )
        if is_json_mode():
            print_json(resp.model_dump())
            return
        items = []
        for t in resp.transfers or []:
            payload = t.model_dump()
            payload["amount"] = (
                t.requested_assignment.value
                if isinstance(t.requested_assignment, AssignmentFungible)
                else None
            )
            items.append(payload)
        output_collection("RGB Transfers", items, item_title="RGB Transfer — {index}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@asset_app.command(
    "refresh",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Refresh pending transfers (with sync):\n"
        "  [cyan]kaleido asset refresh[/cyan]\n\n"
        "  Refresh without syncing blockchain data:\n"
        "  [cyan]kaleido asset refresh --skip-sync[/cyan]\n\n"
        "[bold]Note:[/bold] --skip-sync skips synchronization with the blockchain before refreshing,\n"
        "which is faster but may not include the latest on-chain state."
    ),
)
def asset_refresh(
    skip_sync: Annotated[
        bool,
        typer.Option(
            "--skip-sync",
            help="Skip blockchain synchronization before refreshing transfers.",
        ),
    ] = False,
) -> None:
    """Refresh pending RGB transfers to update their status."""
    asyncio.run(_asset_refresh(skip_sync))


async def _asset_refresh(skip_sync: bool) -> None:
    try:
        client = get_client(require_node=True)
        body = RefreshRequest(skip_sync=skip_sync)
        await client.rln.refresh_transfers(body)
        print_success("Transfers refreshed.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@issue_app.command(
    "uda",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Issue a simple UDA (NFT):\n"
        '  [cyan]kaleido asset issue uda --ticker NFT1 --name "My NFT"[/cyan]\n\n'
        "  With a description and a media file:\n"
        '  [cyan]kaleido asset issue uda --ticker ART1 --name "Art NFT" --description "Limited edition" --file ./art.png[/cyan]\n\n'
        "[dim]UDA = Unique Digital Asset (non-fungible). Supply is always 1.[/dim]"
    ),
)
def asset_issue_uda(
    ticker: Annotated[
        str | None,
        typer.Option("--ticker", help="Short ticker symbol, e.g. NFT1."),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option("--name", help="Human-readable asset name."),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="Optional description."),
    ] = None,
    file_path: Annotated[
        str | None,
        typer.Option("--file", help="Path to a media file (image, etc.) to embed."),
    ] = None,
    precision: Annotated[
        int,
        typer.Option("--precision", help="Number of decimal places (usually 0 for NFTs)."),
    ] = 0,
) -> None:
    """Issue a new UDA (Unique Digital Asset / NFT) RGB token."""
    resolved_ticker: str
    if ticker is not None:
        resolved_ticker = ticker
    elif is_interactive():
        resolved_ticker = typer.prompt("Ticker symbol (e.g. NFT1)")
    else:
        print_error("--ticker is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_name: str
    if name is not None:
        resolved_name = name
    elif is_interactive():
        resolved_name = typer.prompt("Asset name")
    else:
        print_error("--name is required in non-interactive mode.")
        raise typer.Exit(1)

    if is_interactive():
        raw = typer.prompt("[OPTIONAL] Description (Enter to skip)", default="")
        if raw.strip():
            description = raw.strip()
        raw = typer.prompt("[OPTIONAL] Media file path (Enter to skip)", default="")
        if raw.strip():
            file_path = raw.strip()

    asyncio.run(_issue_uda(resolved_ticker, resolved_name, description, file_path, precision))


async def _issue_uda(
    ticker: str,
    name: str,
    description: str | None,
    file_path: str | None,
    precision: int,
) -> None:
    try:
        client = get_client(require_node=True)
        media_file_digest: str | None = None
        if file_path:
            with open(file_path, "rb") as f:
                media_file_digest = hashlib.sha256(f.read()).hexdigest()
        body = IssueAssetUDARequest(
            ticker=ticker,
            name=name,
            details=description,
            precision=precision,
            media_file_digest=media_file_digest,
            attachments_file_digests=[],
        )
        resp: IssueAssetUDAResponse = await client.rln.issue_asset_uda(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"UDA asset issued: {resp.asset.asset_id}")
            output_model(resp, title="Issued Asset")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@asset_app.command(
    "sync",
    epilog="  [cyan]kaleido asset sync[/cyan]   Synchronize RGB wallet with the blockchain.",
)
def asset_sync() -> None:
    """Synchronize the RGB wallet with the blockchain."""
    asyncio.run(_asset_sync())


async def _asset_sync() -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.sync_rgb_wallet()
        print_success("RGB wallet synced.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@asset_app.command(
    "fail-transfers",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Fail all pending transfers with no asset assigned:\n"
        "  [cyan]kaleido asset fail-transfers[/cyan]\n\n"
        "  Fail a specific batch transfer:\n"
        "  [cyan]kaleido asset fail-transfers --batch-idx 3[/cyan]"
    ),
)
def asset_fail_transfers(
    batch_idx: Annotated[
        int | None,
        typer.Option("--batch-idx", help="Specific batch transfer index to fail. Omit for all."),
    ] = None,
    no_asset_only: Annotated[
        bool,
        typer.Option("--no-asset-only", help="Only fail transfers with no associated asset."),
    ] = False,
    skip_sync: Annotated[
        bool,
        typer.Option("--skip-sync", help="Skip blockchain sync before processing."),
    ] = False,
) -> None:
    """Mark pending RGB transfers as failed."""
    asyncio.run(_asset_fail_transfers(batch_idx, no_asset_only, skip_sync))


async def _asset_fail_transfers(batch_idx: int | None, no_asset_only: bool, skip_sync: bool) -> None:
    try:
        client = get_client(require_node=True)
        resp: FailTransfersResponse = await client.rln.fail_transfers(
            FailTransfersRequest(
                batch_transfer_idx=batch_idx,
                no_asset_only=no_asset_only,
                skip_sync=skip_sync,
            )
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            changed = "yes" if resp.transfers_changed else "no"
            print_success(f"Done. Transfers changed: {changed}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@asset_app.command(
    "media",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Fetch and print the hex bytes of an asset's media:\n"
        "  [cyan]kaleido asset media 5891b5b5...[/cyan]\n\n"
        "  Save the raw bytes to a file:\n"
        "  [cyan]kaleido --json asset media 5891b5b5... | jq -r .bytes_hex | xxd -r -p > out.png[/cyan]"
    ),
)
def asset_media(
    digest: Annotated[
        str,
        typer.Argument(help="SHA-256 digest of the media file to retrieve."),
    ],
) -> None:
    """Fetch raw media bytes for an RGB asset by file digest."""
    asyncio.run(_asset_media(digest))


async def _asset_media(digest: str) -> None:
    try:
        client = get_client(require_node=True)
        resp: GetAssetMediaResponse = await client.rln.get_asset_media(
            GetAssetMediaRequest(digest=digest)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title=f"Asset Media — {digest[:20]}…")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
