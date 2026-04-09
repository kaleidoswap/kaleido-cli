"""Tests for `kaleido swap` CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock

from kaleido_cli.app import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pair(base_ticker="BTC", quote_ticker="USDT"):
    p = MagicMock()
    p.base = MagicMock(
        ticker=base_ticker,
        protocol_ids={"RGB": f"rgb:{base_ticker.lower()}"},
        precision=8,
    )
    p.quote = MagicMock(
        ticker=quote_ticker,
        protocol_ids={"RGB": f"rgb:{quote_ticker.lower()}"},
        precision=6,
    )
    p.routes = [MagicMock()]
    p.is_active = True
    return p


def _pairs_resp(pairs=None):
    resp = MagicMock()
    resp.pairs = pairs if pairs is not None else [_pair()]
    return resp


def _quote(rfq_id="rfq-1"):
    m = MagicMock()
    m.rfq_id = rfq_id
    m.from_asset = MagicMock(asset_id="BTC", amount=100000)
    m.to_asset = MagicMock(asset_id="rgb:usdt", amount=500)
    m.model_dump.return_value = {"rfq_id": rfq_id}
    return m


def _order(order_id="order-1"):
    m = MagicMock()
    m.id = order_id
    return m


def _swap_resp(payment_hash="hash-abc"):
    m = MagicMock()
    m.payment_hash = payment_hash
    m.swapstring = "swapstring"
    return m


def _confirm_resp():
    m = MagicMock()
    m.model_dump.return_value = {"status": "ok"}
    return m


# ---------------------------------------------------------------------------
# swap atomic init
# ---------------------------------------------------------------------------


def test_swap_atomic_init_from_amount(runner, mock_client):
    mock_client.maker.list_pairs.return_value = _pairs_resp()
    mock_client.maker.get_quote.return_value = _quote()
    mock_client.maker.init_swap.return_value = _swap_resp()

    result = runner.invoke(
        app, ["swap", "atomic", "init", "BTC/USDT", "--from-amount", "100000", "--yes"]
    )
    assert result.exit_code == 0


def test_swap_atomic_init_to_amount(runner, mock_client):
    mock_client.maker.list_pairs.return_value = _pairs_resp()
    mock_client.maker.get_quote.return_value = _quote()
    mock_client.maker.init_swap.return_value = _swap_resp()

    result = runner.invoke(
        app, ["swap", "atomic", "init", "BTC/USDT", "--to-amount", "500", "--yes"]
    )
    assert result.exit_code == 0


def test_swap_atomic_init_both_amounts_exits_1(runner, mock_client):
    result = runner.invoke(
        app, ["swap", "atomic", "init", "BTC/USDT", "--from-amount", "100", "--to-amount", "50"]
    )
    assert result.exit_code == 1


def test_swap_atomic_init_no_amount_agent_mode_exits_1(runner, mock_client):
    result = runner.invoke(app, ["--agent", "swap", "atomic", "init", "BTC/USDT"])
    assert result.exit_code == 1


def test_swap_atomic_init_pair_not_found_exits_1(runner, mock_client):
    mock_client.maker.list_pairs.return_value = _pairs_resp([_pair()])
    result = runner.invoke(
        app, ["swap", "atomic", "init", "ETH/BTC", "--from-amount", "1", "--yes"]
    )
    assert result.exit_code == 1


def test_swap_atomic_init_no_pair_agent_mode_exits_1(runner, mock_client):
    result = runner.invoke(app, ["--agent", "swap", "atomic", "init", "--from-amount", "100"])
    assert result.exit_code != 0


def test_swap_atomic_init_json(runner, mock_client):
    mock_client.maker.list_pairs.return_value = _pairs_resp()
    mock_client.maker.get_quote.return_value = _quote()
    mock_client.maker.init_swap.return_value = _swap_resp()

    result = runner.invoke(
        app, ["--json", "swap", "atomic", "init", "BTC/USDT", "--from-amount", "1", "--yes"]
    )
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# swap history
# ---------------------------------------------------------------------------


def test_swap_history_table(runner, mock_client):
    order = MagicMock()
    order.id = "abc123456789abcd"
    order.status = "FILLED"
    order.from_asset = "BTC"
    order.to_asset = "USDT"
    order.created_at = "2024-01-01"

    resp = MagicMock()
    resp.data = [order]
    resp.model_dump.return_value = {}
    mock_client.maker.get_order_history.return_value = resp

    result = runner.invoke(app, ["swap", "order", "history"])
    assert result.exit_code == 0
    mock_client.maker.get_order_history.assert_awaited_once_with(status=None, limit=20)


def test_swap_history_status_filter(runner, mock_client):
    resp = MagicMock()
    resp.data = []
    mock_client.maker.get_order_history.return_value = resp

    result = runner.invoke(app, ["swap", "order", "history", "--status", "FAILED", "--limit", "5"])
    assert result.exit_code == 0
    mock_client.maker.get_order_history.assert_awaited_once_with(status="FAILED", limit=5)


def test_swap_history_json(runner, mock_client):
    resp = MagicMock()
    resp.data = []
    resp.model_dump.return_value = {"data": []}
    mock_client.maker.get_order_history.return_value = resp

    result = runner.invoke(app, ["--json", "swap", "order", "history"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# swap status
# ---------------------------------------------------------------------------


def test_swap_status(runner, mock_client):
    resp = MagicMock()
    resp.model_dump.return_value = {"status": "FILLED"}
    mock_client.maker.get_swap_order_status.return_value = resp

    result = runner.invoke(app, ["swap", "order", "status", "abc123456789abcd"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# swap node-swaps
# ---------------------------------------------------------------------------


def test_swap_node_swaps_table(runner, mock_client):
    swap = MagicMock()
    swap.payment_hash = "abcdef1234567890"
    swap.status = "PENDING"

    resp = MagicMock()
    resp.taker = [swap]
    resp.maker = []
    resp.model_dump.return_value = {}
    mock_client.rln.list_swaps.return_value = resp

    result = runner.invoke(app, ["swap", "node", "list"])
    assert result.exit_code == 0


def test_swap_node_swaps_empty(runner, mock_client):
    resp = MagicMock()
    resp.taker = []
    resp.maker = []
    mock_client.rln.list_swaps.return_value = resp

    result = runner.invoke(app, ["swap", "node", "list"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# swap atomic execute
# ---------------------------------------------------------------------------


def test_swap_atomic_execute_happy_path(runner, mock_client):
    mock_client.maker.execute_swap.return_value = _confirm_resp()

    result = runner.invoke(
        app,
        [
            "swap",
            "atomic",
            "execute",
            "--swapstring",
            "swapstring",
            "--taker-pubkey",
            "taker-pub-key",
            "--payment-hash",
            "hash-1",
        ],
    )
    assert result.exit_code == 0
    mock_client.maker.execute_swap.assert_awaited_once()


def test_swap_atomic_execute_missing_swapstring_agent_mode_exits_1(runner, mock_client):
    result = runner.invoke(
        app,
        [
            "--agent",
            "swap",
            "atomic",
            "execute",
            "--taker-pubkey",
            "taker-pub-key",
            "--payment-hash",
            "hash-1",
        ],
    )
    assert result.exit_code != 0


def test_swap_atomic_execute_missing_taker_pubkey_agent_mode_exits_1(runner, mock_client):
    result = runner.invoke(
        app,
        [
            "--agent",
            "swap",
            "atomic",
            "execute",
            "--swapstring",
            "swapstring",
            "--payment-hash",
            "hash-1",
        ],
    )
    assert result.exit_code != 0


def test_swap_atomic_execute_missing_payment_hash_agent_mode_exits_1(runner, mock_client):
    result = runner.invoke(
        app,
        [
            "--agent",
            "swap",
            "atomic",
            "execute",
            "--swapstring",
            "swapstring",
            "--taker-pubkey",
            "taker-pub-key",
        ],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# swap atomic status
# ---------------------------------------------------------------------------


def test_swap_atomic_status(runner, mock_client):
    resp = MagicMock()
    resp.model_dump.return_value = {"status": "confirmed"}
    mock_client.maker.get_atomic_swap_status.return_value = resp

    result = runner.invoke(app, ["swap", "atomic", "status", "abc123"])
    assert result.exit_code == 0


def test_swap_atomic_status_no_hash_agent_mode_exits_1(runner, mock_client):
    result = runner.invoke(app, ["--agent", "swap", "atomic", "status"])
    assert result.exit_code != 0
