"""Lightning payment and invoice commands."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk.rln import (
    DecodeLNInvoiceRequest,
    DecodeLNInvoiceResponse,
    DecodeRGBInvoiceRequest,
    DecodeRGBInvoiceResponse,
    GetPaymentRequest,
    GetPaymentResponse,
    InvoiceStatusRequest,
    InvoiceStatusResponse,
    ListPaymentsResponse,
    LNInvoiceRequest,
    LNInvoiceResponse,
    SendPaymentRequest,
    SendPaymentResponse,
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

payment_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Lightning payments — create invoices, pay, decode, check status.",
)


@payment_app.command(
    "invoice",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  BTC invoice for 10 000 msat:\n"
        "  [cyan]kaleido payment invoice --amount-msat 10000[/cyan]\n\n"
        "  Zero-amount (any-amount) invoice:\n"
        "  [cyan]kaleido payment invoice[/cyan]\n\n"
        "  RGB+LN invoice (receive USDT tokens over Lightning):\n"
        "  [cyan]kaleido payment invoice --asset-id rgb:abc... --asset-amount 500[/cyan]\n\n"
        "  With custom expiry (1 hour):\n"
        "  [cyan]kaleido payment invoice --amount-msat 10000 --expiry 3600[/cyan]"
    ),
)
def payment_invoice(
    amount_msat: Annotated[
        int | None,
        typer.Option(
            "--amount-msat",
            "-a",
            help="Invoice amount in millisatoshis. Omit for a zero-amount invoice.",
        ),
    ] = None,
    expiry: Annotated[
        int,
        typer.Option(
            "--expiry",
            "-e",
            help="Invoice expiry in seconds.",
        ),
    ] = 3600,
    asset_id: Annotated[
        str | None,
        typer.Option(
            "--asset-id",
            help="RGB asset ID to request over Lightning (creates an RGB+LN invoice).",
        ),
    ] = None,
    asset_amount: Annotated[
        int | None,
        typer.Option("--asset-amount", help="Amount of RGB asset to request."),
    ] = None,
) -> None:
    """Create a Lightning invoice (BOLT11)."""
    if asset_amount is not None and asset_id is None:
        print_error("--asset-amount requires --asset-id.")
        raise typer.Exit(1)
    asyncio.run(_payment_invoice(amount_msat, expiry, asset_id, asset_amount))


async def _payment_invoice(
    amount_msat: int | None,
    expiry: int,
    asset_id: str | None,
    asset_amount: int | None,
) -> None:
    try:
        client = get_client(require_node=True)
        body = LNInvoiceRequest(
            amt_msat=amount_msat,
            expiry_sec=expiry,
            asset_id=asset_id,
            asset_amount=asset_amount,
        )
        resp: LNInvoiceResponse = await client.rln.create_ln_invoice(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"Invoice: {resp.invoice}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@payment_app.command(
    "send",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Pay an invoice:\n"
        "  [cyan]kaleido payment send lnbc...[/cyan]\n\n"
        "  Pay a zero-amount invoice with an explicit amount:\n"
        "  [cyan]kaleido payment send lnbc... --amount-msat 5000[/cyan]"
    ),
)
def payment_send(
    invoice: Annotated[str | None, typer.Argument(help="BOLT11 invoice string to pay.")] = None,
    amount_msat: Annotated[
        int | None,
        typer.Option("--amount-msat", help="Amount in msat. Required for zero-amount invoices."),
    ] = None,
    asset_id: Annotated[
        str | None,
        typer.Option("--asset-id", help="RGB asset ID for RGB+LN payments."),
    ] = None,
    asset_amount: Annotated[
        int | None,
        typer.Option("--asset-amount", help="RGB asset amount for RGB+LN payments."),
    ] = None,
) -> None:
    """Send a Lightning payment."""
    resolved_invoice: str
    if invoice is not None:
        resolved_invoice = invoice
    elif is_interactive():
        resolved_invoice = typer.prompt("BOLT11 invoice")
    else:
        print_error("INVOICE argument is required in non-interactive mode.")
        raise typer.Exit(1)

    if asset_amount is not None and asset_id is None:
        print_error("--asset-amount requires --asset-id.")
        raise typer.Exit(1)

    asyncio.run(_payment_send(resolved_invoice, amount_msat, asset_id, asset_amount))


async def _payment_send(
    invoice: str,
    amount_msat: int | None,
    asset_id: str | None,
    asset_amount: int | None,
) -> None:
    try:
        client = get_client(require_node=True)
        body = SendPaymentRequest(
            invoice=invoice,
            amt_msat=amount_msat,
            asset_id=asset_id,
            asset_amount=asset_amount,
        )
        resp: SendPaymentResponse = await client.rln.send_payment(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title="Payment Result")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@payment_app.command("list")
def payment_list() -> None:
    """List Lightning payments."""
    asyncio.run(_payment_list())


async def _payment_list() -> None:
    try:
        client = get_client(require_node=True)
        resp: ListPaymentsResponse = await client.rln.list_payments()
        if is_json_mode():
            print_json(resp.model_dump())
            return
        rows = [
            [
                p.payment_hash[:16] + "…" if p.payment_hash else "-",
                p.status,
                p.amt_msat,
                "inbound" if p.inbound else "outbound",
            ]
            for p in (resp.payments or [])
        ]
        print_table("Payments", ["Payment Hash", "Status", "Amount (msat)", "Direction"], rows)
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@payment_app.command("status")
def payment_status(
    payment_hash: Annotated[str, typer.Argument(help="Payment hash to look up.")],
) -> None:
    """Get the status of a payment."""
    asyncio.run(_payment_status(payment_hash))


async def _payment_status(payment_hash: str) -> None:
    try:
        client = get_client(require_node=True)
        resp: GetPaymentResponse = await client.rln.get_payment(
            GetPaymentRequest(payment_hash=payment_hash)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title="Payment")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@payment_app.command(
    "decode",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Decode a BOLT11 invoice:\n"
        "  [cyan]kaleido payment decode lnbc...[/cyan]\n\n"
        "  Decode an RGB invoice:\n"
        "  [cyan]kaleido payment decode rgb:...[/cyan]"
    ),
)
def payment_decode(
    invoice: Annotated[str, typer.Argument(help="BOLT11 or RGB invoice string to inspect.")],
) -> None:
    """Decode a Lightning or RGB invoice."""
    asyncio.run(_payment_decode(invoice))


async def _payment_decode(invoice: str) -> None:
    try:
        client = get_client(require_node=True)
        # Try BOLT11 first, then RGB
        try:
            resp: (
                DecodeLNInvoiceResponse | DecodeRGBInvoiceResponse
            ) = await client.rln.decode_ln_invoice(DecodeLNInvoiceRequest(invoice=invoice))
            kind = "Lightning (BOLT11)"
        except Exception:
            resp = await client.rln.decode_rgb_invoice(DecodeRGBInvoiceRequest(invoice=invoice))
            kind = "RGB Invoice"

        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title=f"Decoded {kind}")
    except Exception as e:
        print_error(f"Error decoding invoice: {e}")
        raise typer.Exit(1)


@payment_app.command("invoice-status")
def payment_invoice_status(
    invoice: Annotated[str, typer.Argument(help="BOLT11 invoice to check.")],
) -> None:
    """Check the status of an invoice."""
    asyncio.run(_payment_invoice_status(invoice))


async def _payment_invoice_status(invoice: str) -> None:
    try:
        client = get_client(require_node=True)
        resp: InvoiceStatusResponse = await client.rln.get_invoice_status(
            InvoiceStatusRequest(invoice=invoice)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title="Invoice Status")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
