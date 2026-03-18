"""RGB asset commands — list, issue, send, invoices, transfers."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk.rln import (
    AssetBalanceRequest,
    AssetBalanceResponse,
    AssetMetadataRequest,
    AssetMetadataResponse,
    AssignmentFungible,
    IssueAssetCFARequest,
    IssueAssetCFAResponse,
    IssueAssetNIARequest,
    IssueAssetNIAResponse,
    ListAssetsResponse,
    ListTransfersRequest,
    ListTransfersResponse,
    Recipient,
    RefreshRequest,
    RgbInvoiceRequest,
    RgbInvoiceResponse,
    SendRgbRequest,
    SendRgbResponse,
)

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_json_mode,
    output_model,
    print_error,
    print_json,
    print_success,
    print_table,
)

asset_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Manage RGB assets — list, issue, send (single or batch), invoices, and transfer history.",
)


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
        rows = []
        # Add NIA assets
        if resp.nia:
            for asset in resp.nia:
                rows.append([asset.asset_id or "", asset.ticker or "-", asset.name or "", "NIA"])
        # Add CFA assets
        if resp.cfa:
            for asset in resp.cfa:
                rows.append([asset.asset_id or "", "-", asset.name or "", "CFA"])
        # Add UDA assets
        if resp.uda:
            for asset in resp.uda:
                rows.append([asset.asset_id or "", asset.ticker or "-", asset.name or "", "UDA"])
        print_table("RGB Assets", ["Asset ID", "Ticker", "Name", "Schema"], rows)
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


@asset_app.command(
    "issue-nia",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Issue 1 000 000 USDT tokens with 6 decimal places:\n"
        '  [cyan]kaleido asset issue-nia --name "Tether USD" --ticker USDT --supply 1000000 --precision 6[/cyan]\n\n'
        "  Issue a simple whole-unit token:\n"
        "  [cyan]kaleido asset issue-nia --name MyToken --ticker MTK --supply 21000000[/cyan]\n\n"
        "[dim]NIA = Non-Inflatable Asset (fixed-supply fungible token).[/dim]"
    ),
)
def asset_issue_nia(
    name: Annotated[str, typer.Option("--name", help="Human-readable asset name.")],
    ticker: Annotated[str, typer.Option("--ticker", help="Short ticker symbol, e.g. USDT.")],
    supply: Annotated[
        int,
        typer.Option("--supply", help="Total supply expressed in the smallest raw unit."),
    ],
    precision: Annotated[
        int,
        typer.Option("--precision", help="Number of decimal places (0 = whole units)."),
    ] = 0,
) -> None:
    """Issue a new NIA (Non-Inflatable Asset) RGB token."""
    asyncio.run(_issue_nia(name, ticker, supply, precision))


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


@asset_app.command(
    "issue-cfa",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Basic CFA with no media:\n"
        '  [cyan]kaleido asset issue-cfa --name "My NFT" --supply 1[/cyan]\n\n'
        "  With description and attached media file:\n"
        '  [cyan]kaleido asset issue-cfa --name "Art Piece" --supply 100 --description "Limited series" --file ./art.png[/cyan]\n\n'
        "[dim]CFA = Collectible Fungible Asset.[/dim]"
    ),
)
def asset_issue_cfa(
    name: Annotated[str, typer.Option("--name", help="Asset name.")],
    supply: Annotated[int, typer.Option("--supply", help="Total supply in raw units.")],
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
    asyncio.run(_issue_cfa(name, supply, description, file_path, precision))


async def _issue_cfa(
    name: str,
    supply: int,
    description: str | None,
    file_path: str | None,
    precision: int,
) -> None:
    try:
        client = get_client(require_node=True)
        body = IssueAssetCFARequest(
            name=name,
            amounts=[supply],
            precision=precision,
            description=description,
            file_path=file_path,
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
    asset_id: Annotated[str, typer.Argument(help="RGB asset ID to receive.")],
    amount: Annotated[
        int | None,
        typer.Option(
            "--amount",
            "-a",
            help="Amount to request (raw units). Omit for any-amount invoice.",
        ),
    ] = None,
    min_confirmations: Annotated[
        int | None,
        typer.Option(
            "--min-confirmations",
            help="Minimum number of confirmations required for the transfer.",
        ),
    ] = None,
    duration_seconds: Annotated[
        int | None,
        typer.Option(
            "--duration",
            help="Invoice validity duration in seconds.",
        ),
    ] = None,
    witness: Annotated[
        bool | None,
        typer.Option(
            "--witness/--no-witness",
            help="Use witness-based transaction. Default is auto-detect.",
        ),
    ] = None,
) -> None:
    """Create an RGB invoice to receive assets."""
    asyncio.run(_asset_invoice(asset_id, amount, min_confirmations, duration_seconds, witness))


async def _asset_invoice(
    asset_id: str,
    amount: int | None,
    min_confirmations: int | None,
    duration_seconds: int | None,
    witness: bool | None,
) -> None:
    try:
        client = get_client(require_node=True)
        resp: RgbInvoiceResponse = await client.rln.create_rgb_invoice(
            RgbInvoiceRequest(
                asset_id=asset_id,
                assignment=(AssignmentFungible(type="Fungible", value=amount) if amount else None),
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
    asset_id: Annotated[str, typer.Argument(help="RGB asset ID to send.")],
    amount: Annotated[int, typer.Argument(help="Amount to send in raw asset units.")],
    invoice: Annotated[str, typer.Argument(help="Recipient RGB invoice.")],
    fee_rate: Annotated[
        int | None,
        typer.Option(
            "--fee-rate",
            help="On-chain fee rate in sat/vbyte (integer). Uses node default if omitted.",
        ),
    ] = None,
    min_confirmations: Annotated[
        int | None,
        typer.Option(
            "--min-confirmations",
            help="Minimum number of confirmations required for the transfer.",
        ),
    ] = None,
    donation: Annotated[
        bool,
        typer.Option(
            "--donation",
            help="Mark this transfer as a donation.",
        ),
    ] = False,
    skip_sync: Annotated[
        bool,
        typer.Option(
            "--skip-sync",
            help="Skip syncing before sending the transfer.",
        ),
    ] = False,
) -> None:
    """Send RGB assets to an invoice."""
    asyncio.run(
        _asset_send(asset_id, amount, invoice, fee_rate, min_confirmations, donation, skip_sync)
    )


async def _asset_send(
    asset_id: str,
    amount: int,
    invoice: str,
    fee_rate: int | None,
    min_confirmations: int | None,
    donation: bool,
    skip_sync: bool,
) -> None:
    try:
        client = get_client(require_node=True)
        body = SendRgbRequest(
            recipient_map={
                asset_id: [
                    Recipient(
                        recipient_id=invoice,
                        assignment=AssignmentFungible(type="Fungible", value=amount),
                    )
                ]
            },
            fee_rate=fee_rate,
            min_confirmations=min_confirmations,
            donation=donation if donation else None,
            skip_sync=skip_sync if skip_sync else None,
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

        # Parse recipient_map to ensure proper types
        recipient_map = {}
        for asset_id, recipients in data.get("recipient_map", {}).items():
            recipient_list = []
            for r in recipients:
                assignment_data = r["assignment"]
                if assignment_data["type"] == "Fungible":
                    assignment = AssignmentFungible(type="Fungible", value=assignment_data["value"])
                else:
                    # Handle other assignment types if needed
                    assignment = assignment_data

                recipient_list.append(
                    Recipient(
                        recipient_id=r["recipient_id"],
                        assignment=assignment,
                    )
                )
            recipient_map[asset_id] = recipient_list

        body = SendRgbRequest(
            recipient_map=recipient_map,
            fee_rate=data.get("fee_rate"),
            min_confirmations=data.get("min_confirmations"),
            donation=data.get("donation"),
            skip_sync=data.get("skip_sync"),
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
        str | None,
        typer.Argument(help="Filter by asset ID. Omit to show all transfers."),
    ] = None,
) -> None:
    """List RGB transfers."""
    asyncio.run(_asset_transfers(asset_id))


async def _asset_transfers(asset_id: str | None) -> None:
    try:
        client = get_client(require_node=True)
        resp: ListTransfersResponse = await client.rln.list_transfers(
            ListTransfersRequest(asset_id=asset_id)
        )
        if is_json_mode():
            print_json(resp.model_dump())
            return
        rows = [
            [
                t.idx,
                t.status,
                # Amount lives in requested_assignment for fungible transfers
                t.requested_assignment.value if isinstance(t.requested_assignment, AssignmentFungible) else "-",
                t.txid or "-",
            ]
            for t in (resp.transfers or [])
        ]
        print_table("RGB Transfers", ["Index", "Status", "Amount", "TXID"], rows)
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
        body = RefreshRequest(skip_sync=skip_sync if skip_sync else None)
        await client.rln.refresh_transfers(body)
        print_success("Transfers refreshed.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
