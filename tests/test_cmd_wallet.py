"""Tests for `kaleido wallet` CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock

from kaleido_cli.app import app

# ---------------------------------------------------------------------------
# wallet balance
# ---------------------------------------------------------------------------


def test_wallet_balance_panel(runner, mock_client):
    resp = MagicMock()
    resp.model_dump.return_value = {"vanilla": 100000, "colored": 0}
    mock_client.rln.get_btc_balance.return_value = resp

    result = runner.invoke(app, ["wallet", "balance"])
    assert result.exit_code == 0
    mock_client.rln.get_btc_balance.assert_awaited_once()


def test_wallet_balance_json(runner, mock_client):
    resp = MagicMock()
    resp.model_dump.return_value = {"vanilla": 100000, "colored": 0}
    mock_client.rln.get_btc_balance.return_value = resp

    result = runner.invoke(app, ["--json", "wallet", "balance"])
    assert result.exit_code == 0


def test_wallet_balance_skip_sync(runner, mock_client):
    resp = MagicMock()
    resp.model_dump.return_value = {}
    mock_client.rln.get_btc_balance.return_value = resp

    result = runner.invoke(app, ["wallet", "balance", "--skip-sync"])
    assert result.exit_code == 0
    call_kwargs = mock_client.rln.get_btc_balance.call_args
    assert call_kwargs.kwargs.get("skip_sync") is True


# ---------------------------------------------------------------------------
# wallet address
# ---------------------------------------------------------------------------


def test_wallet_address(runner, mock_client):
    resp = MagicMock()
    resp.address = "bc1qtest123"
    resp.model_dump.return_value = {"address": "bc1qtest123"}
    mock_client.rln.get_address.return_value = resp

    result = runner.invoke(app, ["wallet", "address"])
    assert result.exit_code == 0
    assert "bc1qtest123" in result.output


def test_wallet_address_json(runner, mock_client):
    resp = MagicMock()
    resp.address = "bc1qtest123"
    resp.model_dump.return_value = {"address": "bc1qtest123"}
    mock_client.rln.get_address.return_value = resp

    result = runner.invoke(app, ["--json", "wallet", "address"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# wallet send
# ---------------------------------------------------------------------------


def test_wallet_send_happy_path(runner, mock_client):
    resp = MagicMock()
    resp.txid = "deadbeef"
    resp.model_dump.return_value = {"txid": "deadbeef"}
    mock_client.rln.send_btc.return_value = resp

    result = runner.invoke(app, ["wallet", "send", "50000", "bc1qdest"])
    assert result.exit_code == 0
    assert "deadbeef" in result.output


def test_wallet_send_no_args_agent_mode_exits_1(runner, mock_client):
    result = runner.invoke(app, ["--agent", "wallet", "send"])
    assert result.exit_code == 1


def test_wallet_send_no_address_agent_mode_exits_1(runner, mock_client):
    result = runner.invoke(app, ["--agent", "wallet", "send", "1000"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# wallet utxos
# ---------------------------------------------------------------------------


def test_wallet_utxos_table(runner, mock_client):
    utxo = MagicMock()
    utxo.utxo = MagicMock(outpoint="txid:0", btc_amount=10000)
    utxo.rgb_allocations = []

    resp = MagicMock()
    resp.unspents = [utxo]
    resp.model_dump.return_value = {}
    mock_client.rln.list_unspents.return_value = resp

    result = runner.invoke(app, ["wallet", "utxos"])
    assert result.exit_code == 0


def test_wallet_utxos_empty(runner, mock_client):
    resp = MagicMock()
    resp.unspents = []
    mock_client.rln.list_unspents.return_value = resp

    result = runner.invoke(app, ["wallet", "utxos"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# wallet transactions
# ---------------------------------------------------------------------------


def test_wallet_transactions_table(runner, mock_client):
    tx = MagicMock()
    tx.txid = "abc"
    tx.received = 5000
    tx.sent = 0
    tx.fee = 100
    tx.confirmation_time = "2024-01-01"

    resp = MagicMock()
    resp.transactions = [tx]
    mock_client.rln.list_transactions.return_value = resp

    result = runner.invoke(app, ["wallet", "transactions"])
    assert result.exit_code == 0


def test_wallet_transactions_empty(runner, mock_client):
    resp = MagicMock()
    resp.transactions = []
    mock_client.rln.list_transactions.return_value = resp

    result = runner.invoke(app, ["wallet", "transactions"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# wallet estimate-fee
# ---------------------------------------------------------------------------


def test_wallet_estimate_fee(runner, mock_client):
    resp = MagicMock()
    resp.fee_rate = 4.5
    resp.model_dump.return_value = {"fee_rate": 4.5}
    mock_client.rln.estimate_fee.return_value = resp

    result = runner.invoke(app, ["wallet", "estimate-fee", "--blocks", "3"])
    assert result.exit_code == 0
    assert "4.5" in result.output


def test_wallet_estimate_fee_json(runner, mock_client):
    resp = MagicMock()
    resp.fee_rate = 2.0
    resp.model_dump.return_value = {"fee_rate": 2.0}
    mock_client.rln.estimate_fee.return_value = resp

    result = runner.invoke(app, ["--json", "wallet", "estimate-fee"])
    assert result.exit_code == 0
