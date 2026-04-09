"""Tests for kaleido_cli.config."""

from __future__ import annotations

import json

import pytest

from kaleido_cli.config import (
    DEFAULT_API_URL,
    DEFAULT_NETWORK,
    DEFAULT_NODE_URL,
    CliConfig,
    load_config,
    normalize_network_name,
    save_config,
    set_config_key,
)

# ---------------------------------------------------------------------------
# CliConfig dataclass
# ---------------------------------------------------------------------------


def test_climconfig_defaults():
    cfg = CliConfig()
    assert cfg.api_url == DEFAULT_API_URL
    assert cfg.node_url == DEFAULT_NODE_URL
    assert cfg.network == DEFAULT_NETWORK
    assert cfg.spawn_dir == ""


def test_cliconfig_from_dict_roundtrip():
    original = CliConfig(
        api_url="http://a", node_url="http://b", network="regtest", spawn_dir="/tmp"
    )
    restored = CliConfig.from_dict(original.to_dict())
    assert restored == original


def test_cliconfig_from_dict_ignores_unknown_keys():
    data = {"api_url": "http://x", "unknown_field": "ignored"}
    cfg = CliConfig.from_dict(data)
    assert cfg.api_url == "http://x"
    assert not hasattr(cfg, "unknown_field")


def test_normalize_network_name_aliases_mutinynet_to_rln_network():
    assert normalize_network_name("mutinynet") == "signetcustom"
    assert normalize_network_name("signetcustom") == "signetcustom"
    assert normalize_network_name("customsignet") == "signetcustom"
    assert normalize_network_name(" SignetCustom ") == "signetcustom"
    assert normalize_network_name("signet") == "signet"


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def test_load_config_returns_defaults_when_file_missing(isolated_config):
    assert not isolated_config.exists()
    cfg = load_config()
    assert cfg.api_url == DEFAULT_API_URL


def test_load_config_reads_existing_file(isolated_config):
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text(json.dumps({"api_url": "http://custom", "node_url": "http://n"}))
    cfg = load_config()
    assert cfg.api_url == "http://custom"
    assert cfg.node_url == "http://n"


def test_load_config_returns_defaults_on_corrupt_file(isolated_config):
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text("NOT JSON {{")
    cfg = load_config()
    assert cfg.api_url == DEFAULT_API_URL


# ---------------------------------------------------------------------------
# save_config
# ---------------------------------------------------------------------------


def test_save_config_creates_file(isolated_config):
    cfg = CliConfig(api_url="http://saved")
    save_config(cfg)
    assert isolated_config.exists()
    data = json.loads(isolated_config.read_text())
    assert data["api_url"] == "http://saved"


def test_save_config_creates_parent_dirs(isolated_config):
    assert not isolated_config.parent.exists()
    save_config(CliConfig())
    assert isolated_config.exists()


# ---------------------------------------------------------------------------
# set_config_key
# ---------------------------------------------------------------------------


def test_set_config_key_updates_node_url(isolated_config):
    set_config_key("node-url", "http://new-node")
    cfg = load_config()
    assert cfg.node_url == "http://new-node"


def test_set_config_key_updates_api_url(isolated_config):
    set_config_key("api-url", "http://new-api")
    cfg = load_config()
    assert cfg.api_url == "http://new-api"


def test_set_config_key_updates_network(isolated_config):
    set_config_key("network", "mainnet")
    cfg = load_config()
    assert cfg.network == "mainnet"


def test_set_config_key_raises_for_unknown_key(isolated_config):
    with pytest.raises(KeyError, match="Unknown config key"):
        set_config_key("totally-unknown", "value")
