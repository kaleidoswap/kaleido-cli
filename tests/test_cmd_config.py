"""Tests for `kaleido config` CLI commands."""

from __future__ import annotations

import json

from kaleido_cli.app import app
from kaleido_cli.config import DEFAULT_NETWORK

# ---------------------------------------------------------------------------
# config show
# ---------------------------------------------------------------------------


def test_config_show_table(runner, isolated_config):
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "api-url" in result.output or "api_url" in result.output


def test_config_show_json(runner, isolated_config):
    result = runner.invoke(app, ["--json", "config", "show"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "api_url" in data
    assert "node_url" in data
    assert "network" in data


# ---------------------------------------------------------------------------
# config set
# ---------------------------------------------------------------------------


def test_config_set_node_url(runner, isolated_config):
    result = runner.invoke(app, ["config", "set", "node-url", "http://mynode:3001"])
    assert result.exit_code == 0
    assert "node-url" in result.output

    # Verify persistence
    saved = json.loads(isolated_config.read_text())
    assert saved["node_url"] == "http://mynode:3001"


def test_config_set_api_url(runner, isolated_config):
    result = runner.invoke(app, ["config", "set", "api-url", "http://myapi"])
    assert result.exit_code == 0
    saved = json.loads(isolated_config.read_text())
    assert saved["api_url"] == "http://myapi"


def test_config_set_network(runner, isolated_config):
    result = runner.invoke(app, ["config", "set", "network", "mainnet"])
    assert result.exit_code == 0
    saved = json.loads(isolated_config.read_text())
    assert saved["network"] == "mainnet"


def test_config_set_unknown_key_exits_1(runner, isolated_config):
    result = runner.invoke(app, ["config", "set", "bad-key", "val"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# config reset
# ---------------------------------------------------------------------------


def test_config_reset_with_yes_flag(runner, isolated_config):
    # First set something custom
    runner.invoke(app, ["config", "set", "network", "regtest"])
    # Then reset
    result = runner.invoke(app, ["config", "reset", "--yes"])
    assert result.exit_code == 0
    saved = json.loads(isolated_config.read_text())
    assert saved["network"] == DEFAULT_NETWORK


# ---------------------------------------------------------------------------
# config path
# ---------------------------------------------------------------------------


def test_config_path(runner, isolated_config):
    result = runner.invoke(app, ["config", "path"])
    assert result.exit_code == 0
    # Rich may line-wrap long paths — join lines to get the logical string
    output_joined = result.output.replace("\n", "")
    assert str(isolated_config) in output_joined
