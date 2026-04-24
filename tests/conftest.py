"""Shared fixtures for kaleido-cli tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    """Typer CliRunner used by all CLI command tests."""
    return CliRunner()


# ---------------------------------------------------------------------------
# Isolated config (never touches ~/.kaleido)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Redirect config reads/writes to a temp directory."""
    import kaleido_cli.config as cfg_mod

    config_dir = tmp_path / ".kaleido"
    config_file = config_dir / "config.json"

    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", config_file)
    # Also patch the names imported by config_cmd.py
    import kaleido_cli.commands.config_cmd as cmd_mod

    monkeypatch.setattr(cmd_mod, "CONFIG_FILE", config_file)
    return config_file


# ---------------------------------------------------------------------------
# Output mode reset (json/agent flags are module-level globals)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_output_flags():
    """Ensure json/agent flags are reset to defaults between tests."""
    import kaleido_cli.output as out

    out.set_json_mode(False)
    out.set_agent_mode(False)
    yield
    out.set_json_mode(False)
    out.set_agent_mode(False)


# ---------------------------------------------------------------------------
# Mocked KaleidoClient
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_client(mocker):
    """
    Return a MagicMock KaleidoClient whose .maker and .rln sub-objects
    expose AsyncMock methods.

    Because each command module does `from kaleido_cli.context import get_client`,
    we must patch the name in every module that references it, not just in context.
    """
    client = MagicMock()

    # ---- maker sub-client ----
    maker = MagicMock()
    maker.list_assets = AsyncMock()
    maker.list_pairs = AsyncMock()
    maker.get_quote = AsyncMock()
    maker.get_swap_node_info = AsyncMock()
    maker.get_pair_routes = AsyncMock()
    maker.get_order_analytics = AsyncMock()
    maker.get_order_history = AsyncMock()
    maker.get_swap_order_status = AsyncMock()
    maker.get_atomic_swap_status = AsyncMock()
    maker.create_swap_order = AsyncMock()
    maker.init_swap = AsyncMock()
    maker.execute_swap = AsyncMock()
    client.maker = maker

    # ---- rln sub-client ----
    rln = MagicMock()
    rln.get_address = AsyncMock()
    rln.get_btc_balance = AsyncMock()
    rln.send_btc = AsyncMock()
    rln.list_unspents = AsyncMock()
    rln.list_transactions = AsyncMock()
    rln.estimate_fee = AsyncMock()
    rln.shutdown = AsyncMock()
    rln.unlock_wallet = AsyncMock()
    rln.backup = AsyncMock()
    rln.restore = AsyncMock()
    rln.change_password = AsyncMock()
    rln.create_utxos = AsyncMock()
    rln.list_swaps = AsyncMock()
    rln.get_taker_pubkey = AsyncMock()
    rln.maker_init = AsyncMock()
    rln.whitelist_swap = AsyncMock()
    rln.maker_execute = AsyncMock()
    client.rln = rln

    # Patch get_client in the context module AND in every command module that
    # imported it locally via `from kaleido_cli.context import get_client`.
    _targets = [
        "kaleido_cli.context.get_client",
        "kaleido_cli.commands.market.get_client",
        "kaleido_cli.commands.wallet.get_client",
        "kaleido_cli.commands.swap.get_client",
        "kaleido_cli.commands.node_swap.get_client",
        "kaleido_cli.commands.asset.get_client",
        "kaleido_cli.commands.channel.get_client",
        "kaleido_cli.commands.node.get_client",
        "kaleido_cli.commands.payment.get_client",
        "kaleido_cli.commands.peer.get_client",
    ]
    for target in _targets:
        mocker.patch(target, return_value=client)

    return client
