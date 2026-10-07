"""Tests for RLN 0.10 request shapes in `asset` and `payment` commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from kaleido_sdk.rln import AssetFilterAnyOrNone, AssetFilterId, AssetFilterNone

from kaleido_cli.app import app


def _transfers_request(mock_client):
    return mock_client.rln.list_transfers.call_args.args[0]


def test_asset_transfers_defaults_to_all(runner, mock_client):
    mock_client.rln.list_transfers = AsyncMock(return_value=MagicMock(transfers=[]))
    result = runner.invoke(app, ["asset", "transfers"])
    assert result.exit_code == 0, result.output
    req = _transfers_request(mock_client)
    assert isinstance(req.asset_filter, AssetFilterAnyOrNone)
    assert req.txid is None


def test_asset_transfers_by_asset_and_txid(runner, mock_client):
    mock_client.rln.list_transfers = AsyncMock(return_value=MagicMock(transfers=[]))
    result = runner.invoke(app, ["asset", "transfers", "rgb:abc", "--txid", "ff" * 32])
    assert result.exit_code == 0, result.output
    req = _transfers_request(mock_client)
    assert isinstance(req.asset_filter, AssetFilterId)
    assert req.asset_filter.value == "rgb:abc"
    assert req.txid == "ff" * 32


def test_asset_transfers_no_asset(runner, mock_client):
    mock_client.rln.list_transfers = AsyncMock(return_value=MagicMock(transfers=[]))
    result = runner.invoke(app, ["asset", "transfers", "--no-asset"])
    assert result.exit_code == 0, result.output
    assert isinstance(_transfers_request(mock_client).asset_filter, AssetFilterNone)


def test_asset_transfers_rejects_asset_with_no_asset(runner, mock_client):
    result = runner.invoke(app, ["asset", "transfers", "rgb:abc", "--no-asset"])
    assert result.exit_code == 1
    mock_client.rln.list_transfers.assert_not_called()


def test_payment_invoice_description(runner, mock_client):
    mock_client.rln.create_ln_invoice = AsyncMock(return_value=MagicMock(invoice="lnbc1"))
    result = runner.invoke(app, ["payment", "invoice", "-a", "1000", "-d", "Coffee"])
    assert result.exit_code == 0, result.output
    body = mock_client.rln.create_ln_invoice.call_args.args[0]
    assert body.description == "Coffee"
    assert body.description_hash is None


def test_payment_invoice_rejects_both_descriptions(runner, mock_client):
    result = runner.invoke(
        app, ["payment", "invoice", "-d", "Coffee", "--description-hash", "00" * 32]
    )
    assert result.exit_code == 1
    mock_client.rln.create_ln_invoice.assert_not_called()
