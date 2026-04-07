"""Tests for `kaleido market` CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock

from kaleido_cli.app import app

# ---------------------------------------------------------------------------
# Helpers — build lightweight mock Pydantic-like objects
# ---------------------------------------------------------------------------


def _asset(ticker="BTC", name="Bitcoin", protocol_ids=None, precision=8):
    m = MagicMock()
    m.ticker = ticker
    m.name = name
    m.protocol_ids = protocol_ids or {"RGB": f"rgb:{ticker.lower()}"}
    m.precision = precision
    return m


def _pair(base_ticker="BTC", quote_ticker="USDT", routes=None, is_active=True):
    p = MagicMock()
    p.base = _asset(base_ticker, precision=8)
    p.quote = _asset(quote_ticker, precision=6)
    p.routes = routes or [MagicMock()]
    p.is_active = is_active
    return p


def _quote_response(rfq_id="rfq-1"):
    m = MagicMock()
    m.model_dump.return_value = {"rfq_id": rfq_id, "from_amount": 100, "to_amount": 50}
    return m


def _route(from_layer="BTC_LN", to_layer="RGB_LN"):
    m = MagicMock()
    m.from_layer = from_layer
    m.to_layer = to_layer
    m.model_dump.return_value = {"from_layer": from_layer, "to_layer": to_layer}
    return m


# ---------------------------------------------------------------------------
# market assets
# ---------------------------------------------------------------------------


def test_market_assets_table(runner, mock_client):
    assets_resp = MagicMock()
    assets_resp.assets = [_asset()]
    mock_client.maker.list_assets.return_value = assets_resp

    result = runner.invoke(app, ["market", "assets"])
    assert result.exit_code == 0


def test_market_assets_empty(runner, mock_client):
    assets_resp = MagicMock()
    assets_resp.assets = []
    mock_client.maker.list_assets.return_value = assets_resp

    result = runner.invoke(app, ["market", "assets"])
    assert result.exit_code == 0


def test_market_assets_json(runner, mock_client):
    assets_resp = MagicMock()
    assets_resp.assets = [_asset()]
    assets_resp.model_dump.return_value = {"assets": []}
    mock_client.maker.list_assets.return_value = assets_resp

    result = runner.invoke(app, ["--json", "market", "assets"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# market pairs
# ---------------------------------------------------------------------------


def test_market_pairs_table(runner, mock_client):
    pairs_resp = MagicMock()
    pairs_resp.pairs = [_pair()]
    mock_client.maker.list_pairs.return_value = pairs_resp

    result = runner.invoke(app, ["market", "pairs"])
    assert result.exit_code == 0


def test_market_pairs_empty(runner, mock_client):
    pairs_resp = MagicMock()
    pairs_resp.pairs = []
    mock_client.maker.list_pairs.return_value = pairs_resp

    result = runner.invoke(app, ["market", "pairs"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# market quote
# ---------------------------------------------------------------------------


def test_market_quote_from_amount(runner, mock_client):
    pairs_resp = MagicMock()
    pairs_resp.pairs = [_pair()]
    mock_client.maker.list_pairs.return_value = pairs_resp
    mock_client.maker.get_quote.return_value = _quote_response()

    result = runner.invoke(app, ["market", "quote", "BTC/USDT", "--from-amount", "100000"])
    assert result.exit_code == 0


def test_market_quote_both_amounts_exits_1(runner, mock_client):
    result = runner.invoke(
        app, ["market", "quote", "BTC/USDT", "--from-amount", "100", "--to-amount", "50"]
    )
    assert result.exit_code == 1


def test_market_quote_no_amount_agent_mode_exits_1(runner, mock_client):
    result = runner.invoke(app, ["--agent", "market", "quote", "BTC/USDT"])
    assert result.exit_code == 1


def test_market_quote_pair_not_found_exits_1(runner, mock_client):
    pairs_resp = MagicMock()
    pairs_resp.pairs = [_pair()]  # only BTC/USDT
    mock_client.maker.list_pairs.return_value = pairs_resp

    result = runner.invoke(app, ["market", "quote", "ETH/BTC", "--from-amount", "1"])
    assert result.exit_code == 1


def test_market_quote_no_pair_agent_mode_exits_1(runner, mock_client):
    result = runner.invoke(app, ["--agent", "market", "quote", "--from-amount", "100"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# market info
# ---------------------------------------------------------------------------


def test_market_info(runner, mock_client):
    info = MagicMock()
    info.model_dump.return_value = {"node_id": "abc123"}
    mock_client.maker.get_swap_node_info.return_value = info

    result = runner.invoke(app, ["market", "info"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# market routes
# ---------------------------------------------------------------------------


def test_market_routes(runner, mock_client):
    pairs_resp = MagicMock()
    pairs_resp.pairs = [_pair()]
    mock_client.maker.list_pairs.return_value = pairs_resp
    mock_client.maker.get_pair_routes.return_value = [_route(), _route("RGB_LN", "BTC_LN")]

    result = runner.invoke(app, ["market", "routes", "BTC/USDT"])
    assert result.exit_code == 0


def test_market_routes_no_pair_agent_mode_exits_1(runner, mock_client):
    result = runner.invoke(app, ["--agent", "market", "routes"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# market analytics
# ---------------------------------------------------------------------------


def test_market_analytics(runner, mock_client):
    stats = MagicMock()
    stats.model_dump.return_value = {"total_orders": 42}
    mock_client.maker.get_order_analytics.return_value = stats

    result = runner.invoke(app, ["market", "analytics"])
    assert result.exit_code == 0
